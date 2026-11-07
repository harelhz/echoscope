from datetime import datetime, timedelta, timezone

from rich.console import Console

from echoscope.detect.pipeline import detect
from echoscope.models import Post
from echoscope.report.console import print_campaign, print_summary

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
# Monitored posts are attacker-controlled: Rich must show this text, not parse it.
TEXT = "Hid the [/b] numbers, read [link=x]this[/link] [red]now"
URL = "https://example.com/[/b]"


def _render(print_fn, arg) -> str:
    console = Console(width=400, record=True, color_system=None)
    print_fn(arg, console)
    return console.export_text()


def test_markup_in_post_text_is_printed_literally():
    posts = [
        Post("test", f"ch{i}[b]", str(i), T0 + timedelta(minutes=i), TEXT, urls=[URL])
        for i in range(6)
    ]
    result = detect(posts)
    assert len(result.campaigns) == 1

    summary = _render(print_summary, result)
    assert TEXT in summary
    assert "@ch0[b]" in summary

    details = _render(print_campaign, result.campaigns[0])
    assert f"Narrative: {TEXT}" in details
    assert f"Shared link: {URL}" in details
    assert "@ch0[b]" in details
