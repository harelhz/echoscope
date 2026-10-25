"""Import and export posts as JSON Lines.

This is the adapter for any platform without a native collector: convert your
data to one JSON object per line and Echoscope can analyse it.

Required fields: ``channel``, ``message_id``, ``timestamp`` (ISO 8601).
Optional: ``platform`` (default ``"generic"``), ``text``, ``urls``,
``media_hashes`` (hex pHashes), ``forward_of`` (``platform:channel/message_id``),
``views``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from echoscope.models import Post
from echoscope.normalize import extract_urls


def read_jsonl(path: str | Path) -> Iterator[Post]:
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                text = obj.get("text") or ""
                yield Post(
                    platform=obj.get("platform", "generic"),
                    channel=str(obj["channel"]),
                    message_id=str(obj["message_id"]),
                    timestamp=datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00")),
                    text=text,
                    urls=obj.get("urls") or extract_urls(text),
                    media_hashes=obj.get("media_hashes") or [],
                    forward_of=obj.get("forward_of"),
                    views=obj.get("views"),
                )
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"{path}:{line_no}: invalid record ({exc})") from exc


def write_jsonl(posts: Iterable[Post], path: str | Path) -> int:
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for p in posts:
            record = {
                "platform": p.platform,
                "channel": p.channel,
                "message_id": p.message_id,
                "timestamp": p.timestamp.isoformat(),
                "text": p.text,
                "urls": p.urls,
                "media_hashes": p.media_hashes,
                "forward_of": p.forward_of,
                "views": p.views,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count
