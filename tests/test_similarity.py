import random

from echoscope.detect.media import hamming, similar_hash_pairs
from echoscope.detect.minhash import MinHasher, jaccard_estimate, near_duplicate_pairs, shingles


def test_minhash_estimates_jaccard():
    a = shingles("the quick brown fox jumps over the lazy dog near the river bank")
    b = shingles("the quick brown fox jumps over the lazy cat near the river bank")
    true = len(a & b) / len(a | b)
    hasher = MinHasher(num_perm=256)
    est = jaccard_estimate(hasher.signature(a), hasher.signature(b))
    assert abs(est - true) < 0.1


def test_near_duplicates_found_and_unrelated_ignored():
    hasher = MinHasher()
    texts = [
        "leaked documents show the army is hiding heavy losses from the public",
        "leaked documents show that the army is hiding heavy losses from the public!!",
        "football match tonight at the city stadium tickets still available",
    ]
    sigs = [hasher.signature(shingles(t)) for t in texts]
    pairs = {(i, j) for i, j, _ in near_duplicate_pairs(sigs, threshold=0.6)}
    assert pairs == {(0, 1)}


def test_phash_pairs_match_brute_force():
    rng = random.Random(3)
    base = [rng.getrandbits(64) for _ in range(40)]
    hashes = base + [h ^ (1 << rng.randrange(64)) ^ (1 << rng.randrange(64)) for h in base]
    expected = {
        (i, j)
        for i in range(len(hashes))
        for j in range(i + 1, len(hashes))
        if hamming(hashes[i], hashes[j]) <= 8
    }
    found = {(i, j) for i, j, _ in similar_hash_pairs(hashes, max_distance=8)}
    assert found == expected
    assert len(found) >= 40
