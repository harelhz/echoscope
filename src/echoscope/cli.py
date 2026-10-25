"""Command-line interface."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from echoscope import __version__
from echoscope.collectors.jsonl import read_jsonl, write_jsonl
from echoscope.detect.pipeline import DetectionConfig, DetectionResult, detect
from echoscope.report.console import print_campaign, print_summary
from echoscope.report.export import write_json
from echoscope.report.html import write_html
from echoscope.storage import Store

app = typer.Typer(
    help="Detect coordinated influence campaigns across public channels.",
    no_args_is_help=True,
    add_completion=False,
)
collect_app = typer.Typer(help="Collect posts from a platform.", no_args_is_help=True)
app.add_typer(collect_app, name="collect")
console = Console()

DbOption = Annotated[Path, typer.Option("--db", help="SQLite database file.")]


def _parse_when(value: str | None) -> datetime | None:
    """Accept ISO dates or relative spans like ``24h`` / ``7d``."""
    if not value:
        return None
    units = {"h": "hours", "d": "days", "m": "minutes"}
    if value[-1] in units and value[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(**{units[value[-1]]: int(value[:-1])})
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _report(result: DetectionResult, details: int, html: Path | None,
            json_out: Path | None) -> None:
    print_summary(result, console)
    for campaign in result.campaigns[:details]:
        console.print()
        print_campaign(campaign, console)
    if html:
        write_html(result, html)
        console.print(f"\n[green]HTML report:[/green] {html}")
    if json_out:
        write_json(result, json_out)
        console.print(f"[green]JSON results:[/green] {json_out}")


@app.command()
def version() -> None:
    """Show the installed version."""
    console.print(f"echoscope {__version__}")


@app.command()
def demo(
    seed: Annotated[int, typer.Option(help="Random seed for the synthetic scenario.")] = 42,
    html: Annotated[Path | None, typer.Option(help="Write an HTML report.")] = Path(
        "echoscope-demo.html"
    ),
    json_out: Annotated[Path | None, typer.Option("--json", help="Write JSON results.")] = None,
    save: Annotated[Path | None, typer.Option(help="Also save the dataset as JSONL.")] = None,
    details: Annotated[int, typer.Option(help="Campaigns to show in detail.")] = 1,
) -> None:
    """Run the full pipeline on a synthetic week with planted campaigns, and score it."""
    from echoscope.demo import build_scenario
    from echoscope.evaluate import evaluate

    scenario = build_scenario(seed)
    console.print(f"[dim]Synthetic scenario: {len(scenario.posts):,} posts, "
                  f"{len(scenario.campaigns)} planted campaigns, "
                  f"{len(scenario.negatives)} organic look-alikes[/dim]\n")
    if save:
        write_jsonl(scenario.posts, save)
    result = detect(scenario.posts)
    _report(result, details, html, json_out)

    ev = evaluate(scenario, result)
    console.print(f"\n[bold]Benchmark[/bold] (threshold {ev.threshold}): "
                  f"precision {ev.precision:.0%}, recall {ev.recall:.0%}")
    for name, purity in ev.network_purity.items():
        console.print(f"  {name}: {purity:.0%} of its channels grouped into one network")
    lookalikes = [(i, label, s) for i, label, s in ev.matches if label in scenario.negatives]
    for i, label, s in lookalikes:
        console.print(f"  [dim]#{i} is the organic '{label}' case, scored {s:.2f}[/dim]")


@app.command("import")
def import_jsonl(
    path: Annotated[Path, typer.Argument(exists=True, help="JSONL file of posts.")],
    db: DbOption = Path("echoscope.db"),
) -> None:
    """Import posts from a JSONL file (any platform)."""
    with Store(db) as store:
        n = store.add(read_jsonl(path))
    console.print(f"Imported {n:,} posts into {db}")


@app.command("export")
def export_jsonl(
    path: Annotated[Path, typer.Argument(help="Output JSONL file.")],
    db: DbOption = Path("echoscope.db"),
) -> None:
    """Export all stored posts as JSONL."""
    with Store(db) as store:
        n = write_jsonl(store.iter_posts(), path)
    console.print(f"Exported {n:,} posts to {path}")


@app.command()
def stats(db: DbOption = Path("echoscope.db")) -> None:
    """Show what's in the database."""
    with Store(db) as store:
        s = store.stats()
    console.print(f"{s['posts']:,} posts from {s['channels']:,} channels in {db}")


@app.command("detect")
def detect_cmd(
    db: DbOption = Path("echoscope.db"),
    since: Annotated[str | None, typer.Option(help="ISO date or relative (24h, 7d).")] = None,
    until: Annotated[str | None, typer.Option(help="ISO date.")] = None,
    window: Annotated[int, typer.Option(help="Burst window in minutes.")] = 30,
    min_channels: Annotated[int, typer.Option(help="Channels needed for a campaign.")] = 5,
    text_threshold: Annotated[float, typer.Option(help="Text similarity, 0-1.")] = 0.6,
    min_score: Annotated[float, typer.Option(help="Hide campaigns below this score.")] = 0.0,
    details: Annotated[int, typer.Option(help="Campaigns to show in detail.")] = 3,
    html: Annotated[Path | None, typer.Option(help="Write an HTML report.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write JSON results.")] = None,
) -> None:
    """Find coordinated campaigns in stored posts."""
    cfg = DetectionConfig(
        text_threshold=text_threshold,
        min_channels=min_channels,
        burst_window=timedelta(minutes=window),
        min_score=min_score,
    )
    with Store(db) as store:
        posts = store.posts(_parse_when(since), _parse_when(until))
    if not posts:
        console.print("[yellow]No posts in range.[/yellow] Collect or import data first.")
        raise typer.Exit(1)
    with console.status(f"Analysing {len(posts):,} posts..."):
        result = detect(posts, cfg)
    _report(result, details, html, json_out)


@collect_app.command("telegram")
def collect_telegram(
    channels: Annotated[Path, typer.Argument(exists=True, help="Text file, one channel per line.")],
    db: DbOption = Path("echoscope.db"),
    since: Annotated[str | None, typer.Option(help="ISO date or relative (24h, 7d).")] = "7d",
    media: Annotated[bool, typer.Option(help="Download photo thumbnails to pHash them.")] = True,
    session: Annotated[str, typer.Option(help="Telethon session name.")] = "echoscope",
) -> None:
    """Collect public Telegram channels (needs TELEGRAM_API_ID / TELEGRAM_API_HASH)."""
    from echoscope.collectors import telegram

    handles = channels.read_text(encoding="utf-8").splitlines()
    with Store(db) as store:
        try:
            total = asyncio.run(telegram.collect(
                store, handles, since=_parse_when(since), hash_media=media, session=session,
                on_progress=lambda h, n: console.print(f"  @{h}: {n:,} posts total"),
            ))
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
    console.print(f"[green]Collected {total:,} posts into {db}[/green]")


if __name__ == "__main__":
    app()
