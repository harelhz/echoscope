# Echoscope design

## Goal

Given a stream of public posts from many channels, surface the bursts of content that were
most likely pushed by a coordinated network, explain why each one was flagged, and group the
channels that keep acting together.

Non-goals: identifying the people behind channels, judging whether a narrative is true, or
monitoring private conversations.

## Architecture

```
src/echoscope/
├── models.py            Post, Campaign, Signal
├── normalize.py         text and URL canonicalisation (Arabic, Hebrew, tracking params)
├── storage.py           SQLite store, idempotent upserts
├── collectors/
│   ├── telegram.py      Telethon, public channels, incremental
│   └── jsonl.py         universal import/export format
├── detect/
│   ├── minhash.py       MinHash signatures + LSH banding
│   ├── media.py         pHash near-duplicate index (pigeonhole banding)
│   ├── pipeline.py      linking → clusters → events → bursts → graph
│   └── scoring.py       explainable signals
├── report/              terminal, JSON, self-contained HTML
├── demo.py              synthetic benchmark with ground truth
├── evaluate.py          precision / recall / network purity
└── cli.py               Typer CLI
```

Collectors only produce `Post` objects, and detectors only consume them. Adding a platform
means writing one collector; the detection logic never changes.

## Pipeline

### 1. Normalisation

Operators make cosmetic edits so that copies don't look identical. Normalisation removes:

- URLs, @mentions and #hashtags (often rotated per channel)
- Arabic tashkeel, tatweel and letter variants (أ إ آ → ا, ى → ي, ة → ه)
- Hebrew niqqud and cantillation marks
- Emoji, punctuation, case, and Eastern Arabic or Persian digits

URLs are canonicalised separately: lowercased host, no `www.`/`m.`, no fragment, no
`utm_*`/`fbclid`/etc., sorted query string.

### 2. Content linking

Posts are nodes in a union-find structure, and four kinds of evidence link them.

**Near-duplicate text: MinHash + LSH.** Each post becomes a set of character 5-grams.
128 hash functions produce a MinHash signature, where the fraction of matching slots
estimates Jaccard similarity. LSH with 32 bands of 4 rows makes pairs above about 0.5
similarity collide with high probability, so only colliding pairs are verified (default
threshold 0.6). Character shingles were chosen over words because they work for any script
and tolerate typos and inserted words. Cost is roughly O(n) for signatures, plus the
candidate pairs.

**Near-duplicate images: pHash + pigeonhole index.** Two 64-bit hashes within *d* bits of
each other must share at least one of *d + 1* chunks exactly, so hashes are bucketed by chunk
and only bucket-mates are compared. The result is exact (no false negatives) and avoids the
O(n²) scan. Correctness is tested against brute force.

Calibration of the default threshold (8 bits) on a synthetic 640×480 photo-like image:

| Edit | Hamming distance |
|---|---|
| Resize to 50% | 0 |
| Watermark text or logo box | 0 |
| JPEG quality 30 | 2 |
| Brightness +15% | 2 |
| Crop 5% per side | 8 |
| Crop 10% per side | 12 (missed) |
| Unrelated images | 22 minimum, 31 mean |

Raising the threshold to 10 or 12 would catch heavier crops while staying clear of unrelated
images, at the cost of more candidate pairs to verify.

**Same canonical URL.** URLs that one channel attaches to more than three of its own posts
are treated as footers ("subscribe to t.me/…") and ignored. Otherwise they would merge
everything a channel has ever posted into one cluster.

**Explicit forwards.** Forwards of the same original, and the original itself, are linked.

### 3. Events and bursts

Each connected component is an *echo cluster*. It's split into events wherever there is a
quiet gap of more than 6 hours, and a two-pointer sliding window finds the 30-minute span with
the most distinct channels. A burst needs at least 5 distinct channels to become a candidate
campaign. The first post of the event is kept as the **origin**, even when it falls before
the burst, which is what seeding usually looks like.

### 4. Coordination graph

Channels are nodes, and the edge weight is the number of bursts two channels shared. One
shared burst means little, since big news makes everyone overlap once. Community detection
(Louvain) therefore runs only on edges with weight above 1, that is, repeated
co-participation.

### 5. Scoring

| Signal | Value | Weight | Rationale |
|---|---|---|---|
| synchronicity | `1 − e^(−channels/minute)` | 0.30 | Organic spread takes hours; pushes take minutes |
| unattributed_copying | share of non-forward posts | 0.25 | Networks copy-paste so channels look independent; organic sharing forwards |
| recurrence | `1 − e^(−mean other shared bursts per pair)` | 0.30 | The same channels co-posting again and again suggests one operator |
| shared_assets | share of posts with the top image or link | 0.05 | Same media pushed everywhere |
| scale | `(channels − 4) / 16`, capped at 1 | 0.10 | More channels, more evidence |

Confidence levels: HIGH ≥ 0.75, MEDIUM ≥ 0.5, LOW below that. The weights were set by
reasoning about the signals and then checked against the synthetic benchmark. They are not
fitted, because fitting to synthetic data would just memorise the simulator.

## Evaluation

`demo.py` simulates a week across 122 channels, including two sockpuppet networks (30 and 12
channels) running 8 campaigns, and adversarial organic cases: a story covered by 20 to 40
channels in their own words, a viral post forwarded by 25 channels, and an official statement
copy-pasted by 9 aggregators within 25 minutes. `evaluate.py` reports precision and recall
over campaigns, plus network purity (the share of each planted network recovered in a single
community). The tests assert perfect recall and precision across several seeds, and that
every organic look-alike ranks below every planted campaign.

## Known limitations and next steps

- **Paraphrase and cross-language campaigns** evade shingle matching. Plan: add
  multilingual sentence embeddings (for example LaBSE or multilingual-e5) as an optional
  link type, with approximate nearest-neighbour search.
- **Single linkage** can chain loosely related content. Plan: verify cluster cohesion, or
  switch to a density-based method.
- **Weights are hand-set.** With labelled real-world data, they could be learned with a
  simple, interpretable model (logistic regression) that keeps the per-signal breakdown.
- **Telegram rate limits.** Telethon handles flood waits, but collecting hundreds of
  channels takes time. Plan: scheduled incremental collection.
