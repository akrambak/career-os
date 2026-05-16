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
def digest(limit: int, min_fit: int, output_path: str | None) -> None:
    """Render today's top-N digest as Markdown."""
    settings = Settings.load()
    store = Store(settings.database_url)
    rows = store.top_scored(limit=limit, min_fit=min_fit)
    md = render_digest(rows)
    if output_path:
        with open(output_path, "w") as f:
            f.write(md)
        console.print(f"Wrote {output_path}")
    else:
        console.print(md)


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
