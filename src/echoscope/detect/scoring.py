"""Explainable coordination scoring.

Every campaign score is a weighted sum of named signals, each with a
human-readable reason. Analysts need to know *why* something was flagged so
they can check it, and a black-box number is useless as evidence.

The signals reflect how organic and coordinated spread differ:

- **Synchronicity**: organic news spreads over hours; coordinated pushes hit
  many channels within minutes.
- **Unattributed copying**: organic sharing tends to use native forwards (which
  credit the source); networks copy-paste so each channel looks independent.
- **Recurrence**: big news makes unrelated channels overlap once. The same
  channels overlapping again and again suggests one operator.
- **Shared assets**: the same image or link pushed across the burst.
- **Scale**: more channels means more evidence.
"""

from __future__ import annotations

import math
from datetime import timedelta
from itertools import combinations

import networkx as nx

from echoscope.models import Campaign, Signal
from echoscope.normalize import normalize_url

WEIGHTS = {
    "synchronicity": 0.30,
    "unattributed_copying": 0.25,
    "recurrence": 0.30,
    "shared_assets": 0.05,
    "scale": 0.10,
}


def score_campaign(campaign: Campaign, graph: nx.Graph, window: timedelta) -> list[Signal]:
    posts = campaign.posts
    channels = campaign.channels
    n_channels = len(channels)
    span = max(campaign.span_minutes, 1.0)

    velocity = n_channels / span  # distinct channels per minute
    sync = Signal(
        "synchronicity",
        1 - math.exp(-velocity),
        WEIGHTS["synchronicity"],
        f"{n_channels} channels posted within {campaign.span_minutes:.0f} min "
        f"({velocity:.2f} channels/min)",
    )

    copied = sum(1 for p in posts if not p.is_forward)
    copy_ratio = copied / len(posts)
    copying = Signal(
        "unattributed_copying",
        copy_ratio,
        WEIGHTS["unattributed_copying"],
        f"{copied}/{len(posts)} posts copy the content without a native forward",
    )

    pairs = list(combinations(sorted(channels), 2))
    others = [graph[a][b]["weight"] - 1 for a, b in pairs if graph.has_edge(a, b)]
    mean_other = sum(others) / len(pairs) if pairs else 0.0
    recurrence = Signal(
        "recurrence",
        1 - math.exp(-mean_other),
        WEIGHTS["recurrence"],
        f"channel pairs co-appeared in {mean_other:.1f} other bursts on average",
    )

    media_share = _top_share([p.media_hashes for p in posts], campaign.shared_media)
    url_share = _top_share([p.urls for p in posts], campaign.shared_urls, normalise=True)
    share = max(media_share, url_share)
    parts = []
    if campaign.shared_media:
        parts.append(f"same image in {media_share:.0%} of posts")
    if campaign.shared_urls:
        parts.append(f"same link in {url_share:.0%} of posts")
    assets = Signal(
        "shared_assets",
        share,
        WEIGHTS["shared_assets"],
        "; ".join(parts) or "no common image or link",
    )

    scale = Signal(
        "scale",
        min(1.0, max(0, n_channels - 4) / 16),
        WEIGHTS["scale"],
        f"{n_channels} distinct channels in a {window.total_seconds() / 60:.0f}-min window",
    )
    return [sync, copying, recurrence, assets, scale]


def _top_share(values: list[list[str]], shared: list[str], normalise: bool = False) -> float:
    """Fraction of posts that contain the most common shared asset."""
    if not shared or not values:
        return 0.0
    top = shared[0]
    hits = 0
    for vals in values:
        canon = {normalize_url(v) for v in vals} if normalise else set(vals)
        hits += top in canon
    return hits / len(values)
