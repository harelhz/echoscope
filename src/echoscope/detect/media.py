"""Near-duplicate image matching over 64-bit perceptual hashes.

Re-posted propaganda images are usually cropped, resized, re-compressed or
watermarked, which changes the file hash but only flips a few bits of a
perceptual hash. Matching on Hamming distance catches these copies.

To avoid comparing every pair we use the pigeonhole principle: if two hashes
differ in at most ``d`` bits, then after splitting them into ``d + 1`` chunks at
least one chunk must be identical. Only hashes sharing a chunk are compared.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _chunk_masks(num_chunks: int, bits: int = 64) -> list[tuple[int, int]]:
    """Split ``bits`` into ``num_chunks`` contiguous (shift, mask) ranges."""
    base, extra = divmod(bits, num_chunks)
    masks, shift = [], 0
    for i in range(num_chunks):
        width = base + (1 if i < extra else 0)
        masks.append((shift, (1 << width) - 1))
        shift += width
    return masks


def similar_hash_pairs(hashes: Sequence[int], max_distance: int = 8) -> list[tuple[int, int, int]]:
    """Return ``(i, j, distance)`` for all hash pairs within ``max_distance`` bits."""
    masks = _chunk_masks(max_distance + 1)
    buckets: list[dict[int, list[int]]] = [defaultdict(list) for _ in masks]
    for idx, h in enumerate(hashes):
        for band, (shift, mask) in enumerate(masks):
            buckets[band][(h >> shift) & mask].append(idx)

    seen: set[tuple[int, int]] = set()
    result = []
    for band_buckets in buckets:
        for ids in band_buckets.values():
            for n, i in enumerate(ids):
                for j in ids[n + 1 :]:
                    pair = (i, j) if i < j else (j, i)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    dist = hamming(hashes[i], hashes[j])
                    if dist <= max_distance:
                        result.append((*pair, dist))
    return result


def image_phash(data: bytes) -> str | None:
    """Compute a 64-bit pHash for raw image bytes (needs the ``media`` extra)."""
    try:
        import io

        import imagehash
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            return str(imagehash.phash(img))
    except Exception:  # corrupt or unsupported image: skip, never crash a collection run
        return None
