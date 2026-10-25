"""Collect posts from public Telegram channels via the official MTProto API.

Requires the ``telegram`` extra and an API id/hash from https://my.telegram.org.
Only public channels are supported; this collector never joins private groups
or reads private chats.

Collection is incremental: each run continues from the newest message already
stored for a channel, so it can run on a schedule.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone

from echoscope.detect.media import image_phash
from echoscope.models import Post
from echoscope.storage import Store

PLATFORM = "telegram"


def _require_telethon():
    try:
        import telethon
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "Telegram collection needs the optional extra: pip install 'echoscope[telegram]'"
        ) from exc
    return telethon


def client_from_env(session: str = "echoscope"):
    """Build a TelegramClient from ``TELEGRAM_API_ID`` / ``TELEGRAM_API_HASH``."""
    telethon = _require_telethon()
    try:
        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH (get them at https://my.telegram.org)"
        ) from exc
    return telethon.TelegramClient(session, api_id, api_hash)


def _urls(message) -> list[str]:
    from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

    urls = []
    for entity, text in message.get_entities_text() or []:
        if isinstance(entity, MessageEntityTextUrl):
            urls.append(entity.url)
        elif isinstance(entity, MessageEntityUrl):
            urls.append(text)
    return urls


def channel_name(entity) -> str:
    """Stable channel name: the public username, or the numeric id if there is none."""
    return (entity.username or f"id{entity.id}").lower()


def _forward_of(message) -> str | None:
    fwd = message.fwd_from
    if fwd is None:
        return None
    channel_id = getattr(fwd.from_id, "channel_id", None)
    if channel_id and fwd.channel_post:
        # Telegram usually ships the source channel's entity with the message.
        source = getattr(message.forward, "chat", None)
        name = channel_name(source) if source is not None else f"id{channel_id}"
        return f"{PLATFORM}:{name}/{fwd.channel_post}"
    # Forward from a user or a hidden source: still a forward, origin unknown.
    return f"{PLATFORM}:unknown/{fwd.from_name or 'hidden'}-{int(fwd.date.timestamp())}"


async def iter_channel(
    client, entity, min_id: int = 0, since: datetime | None = None, hash_media: bool = True
) -> AsyncIterator[Post]:
    name = channel_name(entity)
    # reverse=True walks oldest -> newest, starting after min_id / since.
    async for msg in client.iter_messages(entity, min_id=min_id, offset_date=since, reverse=True):
        media_hashes = []
        if hash_media and msg.photo:
            data = await client.download_media(msg, bytes, thumb=-1)
            if data and (h := image_phash(data)):
                media_hashes.append(h)
        yield Post(
            platform=PLATFORM,
            channel=name,
            message_id=str(msg.id),
            timestamp=msg.date.astimezone(timezone.utc),
            text=msg.message or "",
            urls=_urls(msg),
            media_hashes=media_hashes,
            forward_of=_forward_of(msg),
            views=msg.views,
        )


async def collect(
    store: Store,
    handles: Iterable[str],
    since: datetime | None = None,
    hash_media: bool = True,
    session: str = "echoscope",
    on_progress=None,
) -> int:
    """Collect new posts from each channel into ``store``; returns posts written."""
    client = client_from_env(session)
    total = 0
    async with client:  # prompts for phone login on first run, then reuses the session file
        for handle in handles:
            handle = handle.strip().removeprefix("https://t.me/").removeprefix("@")
            if not handle or handle.startswith("#"):
                continue
            entity = await client.get_entity(handle)
            min_id = store.last_message_id(PLATFORM, channel_name(entity))
            batch: list[Post] = []
            async for post in iter_channel(client, entity, min_id, since, hash_media):
                batch.append(post)
                if len(batch) >= 500:
                    total += store.add(batch)
                    batch.clear()
            total += store.add(batch)
            if on_progress:
                on_progress(handle, total)
    return total
