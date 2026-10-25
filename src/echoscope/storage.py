"""SQLite storage for collected posts.

A single local file keeps the tool easy to run offline and to hand over as
part of an investigation. Writes are idempotent: re-collecting a channel never
duplicates posts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from echoscope.models import Post

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    platform     TEXT NOT NULL,
    channel      TEXT NOT NULL,
    message_id   TEXT NOT NULL,
    ts           REAL NOT NULL,
    text         TEXT NOT NULL DEFAULT '',
    urls         TEXT NOT NULL DEFAULT '[]',
    media_hashes TEXT NOT NULL DEFAULT '[]',
    forward_of   TEXT,
    views        INTEGER,
    PRIMARY KEY (platform, channel, message_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_ts ON posts (ts);
"""


class Store:
    def __init__(self, path: str | Path = "echoscope.db"):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(_SCHEMA)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def add(self, posts: Iterable[Post]) -> int:
        """Insert or update posts; returns how many rows were written."""
        rows = [
            (
                p.platform,
                p.channel,
                p.message_id,
                p.timestamp.timestamp(),
                p.text,
                json.dumps(p.urls),
                json.dumps(p.media_hashes),
                p.forward_of,
                p.views,
            )
            for p in posts
        ]
        with self.conn:
            self.conn.executemany(
                """INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (platform, channel, message_id) DO UPDATE SET
                     text=excluded.text, urls=excluded.urls,
                     media_hashes=excluded.media_hashes, views=excluded.views""",
                rows,
            )
        return len(rows)

    def posts(self, since: datetime | None = None, until: datetime | None = None) -> list[Post]:
        return list(self.iter_posts(since, until))

    def iter_posts(
        self, since: datetime | None = None, until: datetime | None = None
    ) -> Iterator[Post]:
        lo = since.timestamp() if since else float("-inf")
        hi = until.timestamp() if until else float("inf")
        cur = self.conn.execute(
            "SELECT * FROM posts WHERE ts BETWEEN ? AND ? ORDER BY ts", (lo, hi)
        )
        for platform, channel, mid, ts, text, urls, media, fwd, views in cur:
            yield Post(
                platform=platform,
                channel=channel,
                message_id=mid,
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                text=text,
                urls=json.loads(urls),
                media_hashes=json.loads(media),
                forward_of=fwd,
                views=views,
            )

    def last_message_id(self, platform: str, channel: str) -> int:
        """Highest numeric message id stored for a channel (0 if none)."""
        row = self.conn.execute(
            "SELECT MAX(CAST(message_id AS INTEGER)) FROM posts WHERE platform=? AND channel=?",
            (platform, channel),
        ).fetchone()
        return int(row[0] or 0)

    def stats(self) -> dict[str, int]:
        posts, channels = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT platform || ':' || channel) FROM posts"
        ).fetchone()
        return {"posts": posts, "channels": channels}
