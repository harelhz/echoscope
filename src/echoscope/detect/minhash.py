"""MinHash signatures and LSH banding for near-duplicate text search.

Comparing every post with every other post is O(n^2). MinHash compresses each
post's set of character shingles into a short signature whose per-slot
agreement rate estimates Jaccard similarity; LSH banding then only compares
posts that collide in at least one band, which makes the search close to
linear in practice.

Character shingles (instead of words) keep this language-agnostic: they work
the same for Arabic, Hebrew and English, and tolerate small edits and typos.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence

import numpy as np

_PRIME = np.uint64((1 << 61) - 1)
_MAX32 = np.uint64(0xFFFFFFFF)


def shingles(text: str, k: int = 5) -> set[str]:
    if len(text) <= k:
        return {text} if text else set()
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def _hash32(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "little")


class MinHasher:
    """Produces fixed-length MinHash signatures with ``num_perm`` hash functions."""

    def __init__(self, num_perm: int = 128, seed: int = 1):
        rng = np.random.default_rng(seed)
        # a*x + b with a, b, x < 2**32 never overflows uint64.
        self.a = rng.integers(1, 1 << 32, size=num_perm, dtype=np.uint64)
        self.b = rng.integers(0, 1 << 32, size=num_perm, dtype=np.uint64)
        self.num_perm = num_perm

    def signature(self, tokens: Iterable[str]) -> np.ndarray:
        hashes = np.fromiter((_hash32(t) for t in tokens), dtype=np.uint64)
        if hashes.size == 0:
            return np.full(self.num_perm, _MAX32, dtype=np.uint64)
        permuted = (np.outer(hashes, self.a) + self.b) % _PRIME & _MAX32
        return permuted.min(axis=0)


def jaccard_estimate(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
    return float(np.mean(sig_a == sig_b))


class LSHIndex:
    """Banded LSH over MinHash signatures.

    With ``bands`` bands of ``rows`` rows, two items with Jaccard similarity s
    become candidates with probability 1 - (1 - s**rows)**bands. The defaults
    (32 x 4) make pairs above ~0.5 similarity very likely to collide.
    """

    def __init__(self, bands: int = 32, rows: int = 4):
        self.bands = bands
        self.rows = rows
        self._buckets: list[dict[bytes, list[int]]] = [defaultdict(list) for _ in range(bands)]

    def add(self, item_id: int, signature: np.ndarray) -> None:
        if signature.size < self.bands * self.rows:
            raise ValueError("signature shorter than bands * rows")
        for band in range(self.bands):
            chunk = signature[band * self.rows : (band + 1) * self.rows]
            self._buckets[band][chunk.tobytes()].append(item_id)

    def candidate_pairs(self) -> set[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for buckets in self._buckets:
            for ids in buckets.values():
                if len(ids) < 2:
                    continue
                for i, a in enumerate(ids):
                    for b in ids[i + 1 :]:
                        pairs.add((a, b) if a < b else (b, a))
        return pairs


def near_duplicate_pairs(
    signatures: Sequence[np.ndarray], threshold: float = 0.6, bands: int = 32, rows: int = 4
) -> list[tuple[int, int, float]]:
    """Return ``(i, j, similarity)`` for every pair estimated at or above ``threshold``."""
    index = LSHIndex(bands, rows)
    for i, sig in enumerate(signatures):
        index.add(i, sig)
    result = []
    for i, j in index.candidate_pairs():
        sim = jaccard_estimate(signatures[i], signatures[j])
        if sim >= threshold:
            result.append((i, j, sim))
    return result
