"""Language-aware text and URL normalisation.

Influence operators make small edits so copies don't look identical: swapping
Arabic letter variants, adding diacritics, emojis, hashtags or tracking
parameters. Normalising these away before comparison makes the copies collapse
back together. Arabic and Hebrew get explicit handling because generic
lowercasing does nothing for them.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"[@#][\w֐-׿؀-ۿ]+")
# Arabic tashkeel + tatweel, and Hebrew niqqud / cantillation marks.
_ARABIC_MARKS_RE = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_HEBREW_MARKS_RE = re.compile(r"[֑-ׇ]")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

_ARABIC_LETTER_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        # Eastern Arabic and Persian digits -> ASCII
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)

_TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "si", "ref", "ref_src", "feature", "s", "t"}


def normalize_text(text: str) -> str:
    """Reduce text to a canonical form for near-duplicate comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _ARABIC_MARKS_RE.sub("", text)
    text = _HEBREW_MARKS_RE.sub("", text)
    text = text.translate(_ARABIC_LETTER_MAP)
    text = text.casefold()
    text = _NON_WORD_RE.sub(" ", text)  # also drops emoji and punctuation
    return _SPACE_RE.sub(" ", text).strip()


def extract_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(").,;!?\"'") for m in _URL_RE.finditer(text)]


def normalize_url(url: str) -> str | None:
    """Canonicalise a URL so trivially different links compare equal.

    Lowercases the host, drops ``www.``, fragments and tracking parameters, and
    trailing slashes. Returns ``None`` for unparsable input.
    """
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    host = host.removeprefix("www.").removeprefix("m.")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/")
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def url_domain(url: str) -> str:
    return urlsplit(url).hostname or ""
