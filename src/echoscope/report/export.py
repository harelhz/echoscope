"""Machine-readable export of detection results."""

from __future__ import annotations

import json
from pathlib import Path

from echoscope import __version__
from echoscope.detect.pipeline import DetectionResult
from echoscope.models import Campaign


def campaign_to_dict(c: Campaign) -> dict:
    return {
        "id": c.id,
        "score": c.score,
        "confidence": c.confidence,
        "headline": c.headline,
        "origin": {"channel": c.origin.channel, "post": c.origin.key,
                   "timestamp": c.origin.timestamp.isoformat()},
        "start": c.start.isoformat(),
        "end": c.end.isoformat(),
        "span_minutes": round(c.span_minutes, 1),
        "channels": c.channels,
        "network": c.community,
        "shared_urls": c.shared_urls,
        "shared_media": c.shared_media,
        "signals": [
            {"name": s.name, "value": round(s.value, 3), "weight": s.weight, "reason": s.reason}
            for s in c.signals
        ],
        "posts": [
            {"key": p.key, "channel": p.channel, "timestamp": p.timestamp.isoformat(),
             "forward_of": p.forward_of, "text": p.text}
            for p in c.posts
        ],
    }


def to_dict(result: DetectionResult) -> dict:
    networks: dict[int, list[str]] = {}
    for channel, n in result.communities.items():
        networks.setdefault(n, []).append(channel)
    return {
        "tool": "echoscope",
        "version": __version__,
        "posts_analyzed": result.posts_analyzed,
        "campaigns": [campaign_to_dict(c) for c in result.campaigns],
        "networks": [{"id": n, "channels": sorted(chs)} for n, chs in sorted(networks.items())],
    }


def write_json(result: DetectionResult, path: str | Path) -> None:
    Path(path).write_text(json.dumps(to_dict(result), ensure_ascii=False, indent=2), "utf-8")
