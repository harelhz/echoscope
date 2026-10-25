"""Core data model shared by collectors, storage and detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Post:
    """A single public message, normalised across platforms.

    ``forward_of`` identifies the original message when the platform exposes an
    explicit forward/repost (e.g. ``"telegram:somechannel/1234"``). Explicit
    forwards are attributed amplification; copy-pasted text without attribution
    is a stronger coordination signal, so the distinction matters.
    """

    platform: str
    channel: str
    message_id: str
    timestamp: datetime
    text: str = ""
    urls: list[str] = field(default_factory=list)
    media_hashes: list[str] = field(default_factory=list)  # 64-bit perceptual hashes, hex
    forward_of: str | None = None
    views: int | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel}/{self.message_id}"

    @property
    def is_forward(self) -> bool:
        return self.forward_of is not None


@dataclass(slots=True)
class Signal:
    """One explainable component of a campaign score."""

    name: str
    value: float  # normalised to [0, 1]
    weight: float
    reason: str

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass(slots=True)
class Campaign:
    """A burst of near-identical content pushed by many channels."""

    id: int
    posts: list[Post]  # posts inside the burst, sorted by time
    origin_post: Post | None = None  # earliest post of the event; may precede the burst
    score: float = 0.0
    signals: list[Signal] = field(default_factory=list)
    community: int | None = None
    shared_media: list[str] = field(default_factory=list)
    shared_urls: list[str] = field(default_factory=list)

    @property
    def channels(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.posts:
            seen.setdefault(p.channel, None)
        return list(seen)

    @property
    def origin(self) -> Post:
        return self.origin_post or self.posts[0]

    @property
    def start(self) -> datetime:
        return self.posts[0].timestamp

    @property
    def end(self) -> datetime:
        return self.posts[-1].timestamp

    @property
    def span_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    @property
    def confidence(self) -> str:
        if self.score >= 0.75:
            return "HIGH"
        if self.score >= 0.5:
            return "MEDIUM"
        return "LOW"

    @property
    def headline(self) -> str:
        for p in self.posts:
            if p.text.strip():
                line = p.text.strip().splitlines()[0]
                return line if len(line) <= 120 else line[:117] + "..."
        return "(media only)"
