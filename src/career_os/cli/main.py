from __future__ import annotations

import logging
import sys

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
    STAGES,
    StageTransitionError,
    funnel_counts,
    record_application,
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
def fetch(sources: tuple[str, ...]) -> None:
    """Run scrapers and store new postings."""
    import asyncio
    settings = Settings.load()
    store = Store(settings.database_url)
    keys = list(sources) or None
    results = asyncio.run(crawl(store, keys))
    table = Table(title="Crawl results")
    table.add_column("source")
    table.add_column("new jobs", justify="right")
    for src, count in results.items():
        table.add_row(src, str(count))
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
    "--stage", type=click.Choice(list(STAGES)), default="drafted",
    help="Initial stage. Default: drafted.",
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
    console.print(f"[green]ok[/green] · {app.job_key} → {app.stage}")


@cli.command()
@click.argument("job_key")
@click.option(
    "--to", "to_stage", type=click.Choice(list(STAGES)), default=None,
    help="Target stage. Default: next stage in the pipeline.",
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
    console.print(f"[green]ok[/green] · {app.job_key} → {app.stage}")


@cli.command()
@click.option(
    "--stage", type=click.Choice(list(STAGES)), default=None,
    help="Only show applications in this stage.",
)
def status(stage: str | None) -> None:
    """Show the application pipeline: funnel counts + recent activity."""
    settings = Settings.load()
    store = Store(settings.database_url)
    counts = funnel_counts(store)

    funnel = Table(title="Pipeline funnel", show_lines=False)
    funnel.add_column("stage")
    funnel.add_column("count", justify="right")
    total = sum(counts.values())
    for s in STAGES:
        funnel.add_row(s, str(counts[s]))
    funnel.add_section()
    funnel.add_row("TOTAL", str(total))
    console.print(funnel)

    rows = list_applications(store, stage=stage)
    if not rows:
        return
    listing = Table(title=f"Applications{f' · {stage}' if stage else ''}", show_lines=False)
    listing.add_column("stage")
    listing.add_column("title")
    listing.add_column("key")
    listing.add_column("updated")
    for app, title in rows[:20]:
        listing.add_row(app.stage, title[:48], app.job_key, app.updated_at.date().isoformat())
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
@click.option("--no-open", is_flag=True, help="Do not auto-open a browser tab.")
def dashboard(port: int, no_open: bool) -> None:
    """Launch the Streamlit dashboard. Install with: pip install -e \".[dashboard]\""""
    import os
    import subprocess
    from pathlib import Path
    try:
        import streamlit  # noqa: F401
    except ImportError:
        console.print(
            "[red]Streamlit not installed.[/red] Install dashboard extras with:\n"
            "  [bold]pip install -e \".[dashboard]\"[/bold]"
        )
        sys.exit(1)
    app_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    cmd = [
        "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.headless", "true" if no_open else "false",
        "--browser.gatherUsageStats", "false",
    ]
    console.print(f"[green]Launching dashboard on http://localhost:{port}[/green]")
    subprocess.run(cmd, env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}, check=False)


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
