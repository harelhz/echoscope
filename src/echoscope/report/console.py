"""Terminal output for analysts."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from echoscope.detect.pipeline import DetectionResult
from echoscope.models import Campaign

_COLORS = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "dim"}


def print_summary(result: DetectionResult, console: Console | None = None, limit: int = 20) -> None:
    console = console or Console()
    table = Table(title=f"Echoscope: {len(result.campaigns)} candidate campaigns "
                        f"from {result.posts_analyzed:,} posts")
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Conf.")
    table.add_column("Channels", justify="right")
    table.add_column("Span", justify="right")
    table.add_column("Net", justify="right")
    table.add_column("Origin")
    table.add_column("Headline", overflow="fold", max_width=60)
    for c in result.campaigns[:limit]:
        table.add_row(
            str(c.id),
            f"{c.score:.2f}",
            Text(c.confidence, style=_COLORS[c.confidence]),
            str(len(c.channels)),
            f"{c.span_minutes:.0f}m",
            str(c.community or "-"),
            f"@{c.origin.channel}",
            c.headline,
        )
    console.print(table)
    nets = sorted(set(result.communities.values()))
    if nets:
        sizes = ", ".join(
            f"#{n}: {sum(1 for v in result.communities.values() if v == n)} channels" for n in nets
        )
        console.print(f"[bold]Coordinated networks:[/bold] {sizes}")


def print_campaign(c: Campaign, console: Console | None = None) -> None:
    console = console or Console()
    lines = [
        f"[bold]Narrative:[/bold] {c.headline}",
        f"[bold]Origin:[/bold] @{c.origin.channel} at {c.origin.timestamp:%Y-%m-%d %H:%M} UTC",
        f"[bold]Spread:[/bold] {len(c.channels)} channels in {c.span_minutes:.0f} minutes",
    ]
    if c.community:
        lines.append(f"[bold]Network:[/bold] #{c.community}")
    if c.shared_urls:
        lines.append(f"[bold]Shared link:[/bold] {c.shared_urls[0]}")
    if c.shared_media:
        lines.append(f"[bold]Shared image (pHash):[/bold] {c.shared_media[0]}")
    console.print(Panel("\n".join(lines),
                        title=f"Campaign #{c.id}  score {c.score:.2f} ({c.confidence})",
                        border_style=_COLORS[c.confidence].split()[-1]))

    signals = Table("Signal", "Value", "Weight", "Why", box=None)
    for s in c.signals:
        signals.add_row(s.name, f"{s.value:.2f}", f"{s.weight:.2f}", s.reason)
    console.print(signals)

    timeline = Table("+min", "Channel", "Type", box=None)
    t0 = c.origin.timestamp
    shown = [c.origin] + [p for p in c.posts if p is not c.origin]
    for p in shown[:12]:
        kind = "forward" if p.is_forward else "copy"
        timeline.add_row(f"{(p.timestamp - t0).total_seconds() / 60:5.1f}", f"@{p.channel}", kind)
    if len(shown) > 12:
        timeline.add_row("...", f"{len(shown) - 12} more", "")
    console.print(timeline)
