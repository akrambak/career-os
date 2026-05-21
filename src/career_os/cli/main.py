from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..config import Settings
from ..crawler import crawl
from ..db import Store
from ..digest import render_digest
from ..drafter import OutreachDrafter, render_dry_run
from ..models import Score
from ..profile import DEFAULT_PROFILE
from ..scorer import ClaudeScorer, score_pending
from ..scrapers import REGISTRY
from ..tracker import (
    ALL_STAGES,
    TERMINAL,
    StageTransitionError,
    funnel_counts,
    record_application,
    stages_for_channel,
)
from ..tracker import (
    advance as tracker_advance,
)
from ..tracker.pipeline import list_applications

console = Console()


@click.group()
@click.option("-v", "--verbose", is_flag=True)
def cli(verbose: bool) -> None:
    """Career-OS — crawl, score, surface."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


@cli.command()
@click.option(
    "--source", "sources", multiple=True,
    help="Specific scraper key(s). Default: all registered.",
)
@click.option(
    "--full-refresh", is_flag=True,
    help="Ignore source watermarks and re-pull everything. Debug / first-run.",
)
def fetch(sources: tuple[str, ...], full_refresh: bool) -> None:
    """Run scrapers and store new postings."""
    import asyncio
    settings = Settings.load()
    store = Store(settings.database_url)
    keys = list(sources) or None
    results = asyncio.run(crawl(store, keys, use_watermarks=not full_refresh))
    table = Table(title="Crawl results")
    table.add_column("source")
    table.add_column("new jobs", justify="right")
    table.add_column("status")
    for src, count in results.items():
        wm = store.get_watermark(src)
        status = wm.last_status if wm else "—"
        table.add_row(src, str(count), status)
    console.print(table)


@cli.command()
@click.option("--limit", default=50, type=int)
@click.option(
    "--dry-run", is_flag=True,
    help="Score with a deterministic stub instead of Claude — no API key needed.",
)
def score(limit: int, dry_run: bool) -> None:
    """Score unscored jobs against the profile."""
    settings = Settings.load()
    store = Store(settings.database_url)
    if dry_run:
        n = _score_dry_run(store, limit)
        console.print(f"[yellow]dry-run[/yellow] · saved {n} stub score(s).")
        return
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY not set in .env (or use --dry-run)[/red]")
        sys.exit(1)
    scorer = ClaudeScorer(settings.anthropic_api_key)
    try:
        n = score_pending(store, scorer, DEFAULT_PROFILE, limit=limit)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Scoring aborted: {type(exc).__name__}: {exc}[/red]")
        sys.exit(2)
    console.print(f"Scored {n} job(s).")


def _score_dry_run(store: Store, limit: int) -> int:
    """Deterministic profile-aware stub — uses simple keyword overlap for fit."""
    profile_terms = {
        t.lower() for stack in (DEFAULT_PROFILE.proven_stack, DEFAULT_PROFILE.new_stack)
        for term in stack for t in term.replace("/", " ").split()
        if len(t) > 2
    }
    jobs = store.unscored_jobs(limit=limit)
    for job in jobs:
        text = f"{job.title} {' '.join(job.tags)} {job.description[:1500]}".lower()
        hits = sum(1 for term in profile_terms if term in text)
        fit = min(95, 25 + hits * 5)
        store.save_score(Score(
            job_key=job.key, fit=fit,
            reasoning=f"[dry-run] {hits} profile-term matches in title/tags/description.",
            pros=[t for t in profile_terms if t in text][:5],
            cons=[],
            suggested_angle=(
                f"Lead with {DEFAULT_PROFILE.years_experience}y production + "
                "the specific stack overlap." if fit >= 50 else None
            ),
        ))
    return len(jobs)


@cli.command()
@click.option("--limit", default=5, type=int)
@click.option("--min-fit", default=60, type=int)
@click.option("--channel", type=click.Choice(["ft", "freelance", "either", "all"]), default="all")
def top(limit: int, min_fit: int, channel: str) -> None:
    """Show top scored matches as a quick CLI digest."""
    settings = Settings.load()
    store = Store(settings.database_url)
    rows = store.top_scored(limit=limit, min_fit=min_fit)
    if channel != "all":
        rows = [(j, s) for j, s in rows if j.channel.value == channel]
    if not rows:
        console.print(
            "[yellow]No matches at that threshold yet — run `fetch` then `score`.[/yellow]"
        )
        return
    table = Table(title=f"Top {len(rows)} (fit ≥ {min_fit})", show_lines=True)
    table.add_column("fit", justify="right")
    table.add_column("ch")
    table.add_column("title")
    table.add_column("company")
    table.add_column("source")
    for job, score in rows:
        table.add_row(
            str(score.fit), job.channel.value, job.title[:60],
            (job.company or "")[:30], job.source,
        )
    console.print(table)


@cli.command()
@click.option("--limit", default=5, type=int)
@click.option("--min-fit", default=60, type=int)
@click.option("--out", "output_path", type=click.Path(), default=None)
@click.option(
    "--send", is_flag=True,
    help="Send via SMTP_PROVIDER (requires SMTP_API_KEY in .env).",
)
def digest(limit: int, min_fit: int, output_path: str | None, send: bool) -> None:
    """Render today's top-N digest as Markdown. Optionally email it."""
    from datetime import date

    from ..digest import DigestEmailer
    settings = Settings.load()
    store = Store(settings.database_url)
    rows = store.top_scored(limit=limit, min_fit=min_fit)
    md = render_digest(rows)
    if output_path:
        with open(output_path, "w") as f:
            f.write(md)
        console.print(f"Wrote {output_path}")
    elif not send:
        console.print(md)
    if send:
        if not settings.smtp_provider or not settings.smtp_api_key:
            console.print(
                "[red]SMTP_PROVIDER and SMTP_API_KEY required in .env to --send[/red]"
            )
            sys.exit(1)
        emailer = DigestEmailer(
            provider=settings.smtp_provider, api_key=settings.smtp_api_key,
            sender=settings.smtp_from, recipient=settings.smtp_to,
        )
        result = emailer.send(
            subject=f"Top {len(rows)} matches — {date.today().isoformat()}",
            markdown_body=md,
        )
        if result.ok:
            console.print(f"[green]sent via {result.provider}[/green] · {result.detail}")
        else:
            console.print(f"[red]send failed via {result.provider}[/red] · {result.detail}")
            sys.exit(2)


@cli.command()
@click.argument("job_key", required=False)
@click.option(
    "--top", "top_n", type=int, default=None,
    help="Draft for the top-N scored jobs instead of one specific key.",
)
@click.option("--min-fit", default=70, type=int)
@click.option("--dry-run", is_flag=True, help="Skip the API; render a deterministic stub.")
@click.option("--show/--no-show", default=True, help="Print drafts to stdout.")
def draft(job_key: str | None, top_n: int | None, min_fit: int, dry_run: bool, show: bool) -> None:
    """Generate outreach drafts for scored jobs.

    Usage:
      career-os draft <job-key>
      career-os draft --top 5 --min-fit 70
      career-os draft <job-key> --dry-run     # no API key needed
    """
    settings = Settings.load()
    store = Store(settings.database_url)

    targets: list[tuple] = []
    if job_key:
        job = store.get_job(job_key)
        score = store.get_score(job_key) if job else None
        if not job or not score:
            console.print(f"[red]No scored job with key {job_key!r}.[/red]")
            sys.exit(1)
        targets.append((job, score))
    elif top_n is not None:
        targets = store.top_scored(limit=top_n, min_fit=min_fit)
    else:
        console.print("[yellow]Pass a job-key or --top N.[/yellow]")
        sys.exit(1)

    if not targets:
        console.print("[yellow]No matching scored jobs.[/yellow]")
        return

    drafter = None
    model = "dry-run"
    if not dry_run:
        if not settings.anthropic_api_key:
            console.print("[red]ANTHROPIC_API_KEY not set (or use --dry-run)[/red]")
            sys.exit(1)
        drafter = OutreachDrafter(settings.anthropic_api_key)
        model = drafter._model

    for job, score in targets:
        try:
            body = (
                render_dry_run(job, score, DEFAULT_PROFILE) if dry_run
                else drafter.draft(job, score, DEFAULT_PROFILE)
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Draft failed for {job.key}: {type(exc).__name__}: {exc}[/red]")
            continue
        store.save_draft(job.key, fmt=job.channel.value, body=body, model=model)
        if show:
            console.rule(f"[bold]{job.title}[/bold] · fit {score.fit} · {job.key}")
            console.print(body)
            console.print()


@cli.command()
@click.argument("job_key")
@click.option(
    "--stage", type=click.Choice(list(ALL_STAGES)), default="drafted",
    help="Initial stage. Default: drafted. Stage must match the job's channel pipeline.",
)
@click.option("--notes", default=None)
def apply(job_key: str, stage: str, notes: str | None) -> None:
    """Record an application for a job — adds it to the pipeline tracker."""
    settings = Settings.load()
    store = Store(settings.database_url)
    try:
        app = record_application(store, job_key, stage=stage, notes=notes)
    except StageTransitionError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print(f"[green]ok[/green] · {app.job_key} → {app.stage} ({app.channel})")


@cli.command()
@click.argument("job_key")
@click.option(
    "--to", "to_stage", type=click.Choice(list(ALL_STAGES)), default=None,
    help="Target stage. Default: next stage in this application's pipeline.",
)
@click.option("--notes", default=None)
def advance(job_key: str, to_stage: str | None, notes: str | None) -> None:
    """Move an application forward to the next stage (or a specific one)."""
    settings = Settings.load()
    store = Store(settings.database_url)
    try:
        app = tracker_advance(store, job_key, to=to_stage, notes=notes)
    except StageTransitionError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print(f"[green]ok[/green] · {app.job_key} → {app.stage} ({app.channel})")


@cli.command()
@click.option(
    "--stage", type=click.Choice(list(ALL_STAGES)), default=None,
    help="Only show applications in this stage.",
)
@click.option(
    "--channel", type=click.Choice(["ft", "freelance"]), default=None,
    help="Only show applications in this channel's pipeline.",
)
def status(stage: str | None, channel: str | None) -> None:
    """Show the application pipeline: per-channel funnels + recent activity."""
    settings = Settings.load()
    store = Store(settings.database_url)
    counts = funnel_counts(store)

    for channel_label, channel_key in (("FT pipeline", "ft"), ("Freelance pipeline", "freelance")):
        if channel and channel != channel_key:
            continue
        channel_counts = counts.get(channel_key, {})
        funnel = Table(title=channel_label, show_lines=False)
        funnel.add_column("stage")
        funnel.add_column("count", justify="right")
        total = sum(channel_counts.values())
        for s in stages_for_channel(channel_key):
            funnel.add_row(
                s + (" (terminal)" if s in TERMINAL else ""),
                str(channel_counts.get(s, 0)),
            )
        funnel.add_section()
        funnel.add_row("TOTAL", str(total))
        console.print(funnel)

    rows = list_applications(store, stage=stage, channel=channel)
    if not rows:
        return
    title_suffix = []
    if channel:
        title_suffix.append(channel)
    if stage:
        title_suffix.append(stage)
    suffix = f" · {' · '.join(title_suffix)}" if title_suffix else ""
    listing = Table(title=f"Applications{suffix}", show_lines=False)
    listing.add_column("channel")
    listing.add_column("stage")
    listing.add_column("title")
    listing.add_column("key")
    listing.add_column("updated")
    for app, title in rows[:20]:
        listing.add_row(
            app.channel, app.stage, title[:48], app.job_key,
            app.updated_at.date().isoformat(),
        )
    console.print(listing)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Use the keyword stub instead of Claude.")
def eval(dry_run: bool) -> None:
    """Run scorer fixtures and check the score distribution stays calibrated."""
    from ..eval import evaluate_fixtures, evaluate_fixtures_with, summarize
    settings = Settings.load()
    if dry_run:
        rows = evaluate_fixtures_with(_stub_score_fn(), DEFAULT_PROFILE)
    else:
        if not settings.anthropic_api_key:
            console.print("[red]ANTHROPIC_API_KEY not set (or use --dry-run)[/red]")
            sys.exit(1)
        rows = evaluate_fixtures(ClaudeScorer(settings.anthropic_api_key), DEFAULT_PROFILE)

    table = Table(title="Scorer eval", show_lines=False)
    table.add_column("fixture")
    table.add_column("expected", justify="right")
    table.add_column("actual", justify="right")
    table.add_column("ok")
    table.add_column("reasoning")
    for r in rows:
        ok = "[green]✓[/green]" if r.in_range else f"[red]× ({r.deviation})[/red]"
        table.add_row(
            r.fixture_id, f"{r.expected_min}-{r.expected_max}", str(r.actual),
            ok, r.reasoning[:60],
        )
    console.print(table)
    s = summarize(rows)
    console.print(
        f"\n[bold]{s['in_range']}/{s['n']} in range ({s['in_range_pct']}%)[/bold] · "
        f"mean {s['mean_fit']} · median {s['median_fit']} · "
        f"70+: {s['distribution_70_plus']} · 30-55: {s['distribution_30_to_55']}"
    )


def _stub_score_fn():
    """Deterministic profile-aware stub mirroring _score_dry_run."""
    profile_terms = {
        t.lower() for stack in (DEFAULT_PROFILE.proven_stack, DEFAULT_PROFILE.new_stack)
        for term in stack for t in term.replace("/", " ").split()
        if len(t) > 2
    }

    def score_fn(job, profile):
        text = f"{job.title} {' '.join(job.tags)} {job.description[:1500]}".lower()
        hits = sum(1 for term in profile_terms if term in text)
        fit = min(95, 25 + hits * 5)
        return Score(
            job_key=job.key, fit=fit,
            reasoning=f"[stub] {hits} term matches.",
            pros=[t for t in profile_terms if t in text][:3],
            cons=[],
            suggested_angle=None,
        )
    return score_fn


@cli.command()
@click.option("--port", default=8501, type=int)
@click.option(
    "--address", default="0.0.0.0",
    help="Bind address. Default 0.0.0.0 (reachable from WSL host); use 127.0.0.1 for local-only.",
)
@click.option("--no-open", is_flag=True, help="Do not auto-open a browser tab.")
@click.option(
    "--diagnose", is_flag=True,
    help="Print network diagnostics + WSL/Windows-side fix recipes and exit.",
)
def dashboard(port: int, address: str, no_open: bool, diagnose: bool) -> None:
    """Launch the Streamlit dashboard. Install with: pip install -e \".[dashboard]\""""
    from ..dashboard.network import build_reachable_urls, detect_environment, render_diagnostics
    try:
        import streamlit  # noqa: F401
    except ImportError:
        console.print(
            "[red]Streamlit not installed.[/red] Install dashboard extras with:\n"
            "  [bold]pip install -e \".[dashboard]\"[/bold]"
        )
        sys.exit(1)

    env = detect_environment()
    if diagnose:
        console.print(render_diagnostics(env, port))
        return

    app_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    # Use the current interpreter to invoke streamlit. Calling bare `streamlit`
    # only works if .venv/bin is on PATH. Running via `python -m streamlit`
    # always finds the right binary regardless of venv-activation state.
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.address", address,
        "--server.headless", "true" if no_open else "false",
        "--browser.gatherUsageStats", "false",
    ]
    urls = build_reachable_urls(env, address, port)
    console.print("[bold green]Dashboard URLs[/bold green] (try these in your browser):")
    for label, url in urls:
        console.print(f"  • {url}  [dim]{label}[/dim]")
    if env.is_wsl and address != "127.0.0.1":
        console.print(
            "\n[dim]WSL2 detected — if localhost fails from Windows, use the WSL2 IP above.[/dim]"
        )
        console.print(
            "[dim]For deeper diagnostics: [bold]career-os dashboard --diagnose[/bold][/dim]"
        )
    subprocess.run(cmd, check=False)


@cli.command()
@click.option("--limit", default=200, type=int)
@click.option("--max-age-days", default=7, type=int,
              help="Only recheck jobs not rechecked in this many days.")
@click.option("--source", default=None,
              help="Restrict recheck to one scraper key.")
@click.option("--concurrency", default=10, type=int)
def recheck(limit: int, max_age_days: int, source: str | None, concurrency: int) -> None:
    """Re-check job URLs; mark 404/redirected/3-strikes as closed."""
    import asyncio

    from ..recheck import recheck as run_recheck
    from ..recheck import summarize
    settings = Settings.load()
    store = Store(settings.database_url)
    outcomes = asyncio.run(run_recheck(
        store, limit=limit, max_age_days=max_age_days,
        source=source, concurrency=concurrency,
    ))
    if not outcomes:
        console.print("[yellow]No candidates to recheck — DB is fresh.[/yellow]")
        return
    summary = summarize(outcomes)
    table = Table(title=f"Recheck — {len(outcomes)} job(s)")
    table.add_column("decision")
    table.add_column("count", justify="right")
    for decision in ("kept", "closed", "transient"):
        table.add_row(decision, str(summary.get(decision, 0)))
    console.print(table)
    closed = [o for o in outcomes if o.decision == "closed"]
    if closed:
        listing = Table(title="Newly closed", show_lines=False)
        listing.add_column("key")
        listing.add_column("reason")
        listing.add_column("status")
        for o in closed[:20]:
            listing.add_row(o.job_key, o.reason or "", str(o.status_code or "—"))
        console.print(listing)


@cli.command(name="backlinks-recheck")
@click.option("--limit", default=200, type=int)
@click.option("--max-age-days", default=7, type=int,
              help="Only recheck backlinks not checked in this many days.")
def backlinks_recheck(limit: int, max_age_days: int) -> None:
    """Re-walk live backlinks; flip dead/removed where appropriate."""
    import asyncio

    from ..backlinks.recheck import recheck_all, summarize
    settings = Settings.load()
    store = Store(settings.database_url)
    outcomes = asyncio.run(recheck_all(
        store, limit=limit, max_age_days=max_age_days,
    ))
    if not outcomes:
        console.print("[yellow]No backlinks due for recheck.[/yellow]")
        return
    s = summarize(outcomes)
    table = Table(title=f"Recheck — {len(outcomes)} backlink(s)")
    table.add_column("decision")
    table.add_column("count", justify="right")
    for d in ("live", "dead", "removed", "redirect", "transient"):
        table.add_row(d, str(s.get(d, 0)))
    console.print(table)


@cli.command(name="mentions-scan")
@click.option(
    "--source", "sources", multiple=True,
    help="Specific source key(s). Default: all (hn, devto, github).",
)
def mentions_scan(sources: tuple[str, ...]) -> None:
    """Scan HN + dev.to (+ GitHub) for unlinked brand mentions."""
    import asyncio

    from ..mentions.sources import scan_sources
    settings = Settings.load()
    store = Store(settings.database_url)
    selected = list(sources) or None
    results = asyncio.run(scan_sources(store, sources=selected))
    table = Table(title="Mention scan results")
    table.add_column("source")
    table.add_column("rows touched", justify="right")
    for src, n in results.items():
        table.add_row(src, str(n))
    console.print(table)
    if "github" in results and results["github"] == 0 and not settings.github_token:
        console.print(
            "[dim]github skipped — set GITHUB_TOKEN in .env to enable.[/dim]"
        )


@cli.command(name="trends-scan")
@click.option(
    "--source", "sources", multiple=True,
    help="Specific source key(s). Default: all (hn, devto, tavily).",
)
def trends_scan(sources: tuple[str, ...]) -> None:
    """Scrape trend feeds (HN frontpage, dev.to top, Tavily) and upsert
    into the trends table. Idempotent."""
    import asyncio

    from ..profile import DEFAULT_PROFILE
    from ..trends.sources import scan_sources
    settings = Settings.load()
    store = Store(settings.database_url)
    selected = list(sources) or None
    results = asyncio.run(scan_sources(store, DEFAULT_PROFILE, sources=selected))
    table = Table(title="Trend scan results")
    table.add_column("source")
    table.add_column("rows touched", justify="right")
    for src, n in results.items():
        table.add_row(src, str(n))
    console.print(table)
    if "tavily" in results and results["tavily"] == 0 and not settings.tavily_api_key:
        console.print(
            "[dim]tavily skipped — set TAVILY_API_KEY in .env to enable.[/dim]"
        )


@cli.command(name="automations-run-due")
def automations_run_due() -> None:
    """Fire every armed automation whose next-run is in the past.

    Designed for cron — wire it as `* * * * * career-os automations-run-due`.
    Safe to call frequently: only genuinely-due automations execute.
    """
    from ..automations import run_due, seed_defaults
    settings = Settings.load()
    store = Store(settings.database_url)
    seed_defaults(store)
    results = run_due(store)
    if not results:
        console.print("[dim]Nothing due.[/dim]")
        return
    table = Table(title=f"Fired {len(results)} automation(s)")
    table.add_column("name")
    table.add_column("status")
    table.add_column("summary")
    for name, result in results.items():
        color = {"ok": "green", "failed": "red", "skipped": "yellow"}.get(result.status, "white")
        table.add_row(name, f"[{color}]{result.status}[/{color}]", result.summary)
    console.print(table)


@cli.command()
def sources() -> None:
    """List registered scrapers."""
    table = Table(title="Registered scrapers")
    table.add_column("key")
    table.add_column("class")
    for key, cls in REGISTRY.items():
        table.add_row(key, cls.__name__)
    console.print(table)


if __name__ == "__main__":
    cli()
