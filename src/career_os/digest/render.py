from __future__ import annotations

from datetime import date

from ..models import JobPost, Score


def render_digest(rows: list[tuple[JobPost, Score]]) -> str:
    today = date.today().isoformat()
    if not rows:
        return f"# Career-OS digest — {today}\n\nNo scored jobs to show today.\n"

    lines = [f"# Career-OS digest — {today}", ""]
    lines.append(f"Top {len(rows)} matches across freelance + FT remote channels.")
    lines.append("")
    for i, (job, score) in enumerate(rows, 1):
        lines.append(f"## {i}. [{score.fit}] {job.title} — {job.company or 'Unknown'}")
        lines.append(f"- **Channel:** {job.channel.value}  ·  **Source:** {job.source}")
        if job.compensation:
            lines.append(f"- **Comp:** {job.compensation}")
        lines.append(f"- **Link:** {job.url}")
        lines.append(f"- **Why:** {score.reasoning}")
        if score.pros:
            lines.append(f"- **Pros:** {', '.join(score.pros)}")
        if score.cons:
            lines.append(f"- **Cons:** {', '.join(score.cons)}")
        if score.suggested_angle:
            lines.append(f"- **Angle:** {score.suggested_angle}")
        lines.append("")
    return "\n".join(lines)
