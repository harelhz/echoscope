"""End-to-end detection: posts in, scored campaigns out.

Stages
------
1. **Link** posts that carry the same content: near-duplicate text (MinHash),
   near-duplicate images (pHash), the same canonical URL, or explicit forwards
   of the same original message.
2. **Group** linked posts into echo clusters (connected components).
3. **Split** each cluster into events wherever there is a long quiet gap, then
   find the densest burst of distinct channels inside each event.
4. **Graph**: channels that keep appearing in the same bursts get connected;
   community detection reveals likely networks run by one operator.
5. **Score** each burst with explainable signals.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations

import networkx as nx

from echoscope.detect.media import similar_hash_pairs
from echoscope.detect.minhash import MinHasher, near_duplicate_pairs, shingles
from echoscope.detect.scoring import score_campaign
from echoscope.models import Campaign, Post
from echoscope.normalize import normalize_text, normalize_url


@dataclass
class DetectionConfig:
    text_threshold: float = 0.6  # estimated Jaccard over character shingles
    min_text_chars: int = 40  # shorter texts ("BREAKING", "🔥") are too generic to link on
    shingle_size: int = 5
    image_max_distance: int = 8  # pHash Hamming distance
    max_url_reuse: int = 3  # a channel reusing a URL more often than this = footer, ignored
    min_channels: int = 5  # distinct channels needed to call something a campaign
    burst_window: timedelta = timedelta(minutes=30)
    event_gap: timedelta = timedelta(hours=6)
    min_score: float = 0.0  # campaigns below this are dropped from the results
    seed: int = 7


@dataclass
class DetectionResult:
    campaigns: list[Campaign]
    graph: nx.Graph  # channel coordination graph
    communities: dict[str, int]  # channel -> community id
    posts_analyzed: int


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def link_posts(posts: list[Post], cfg: DetectionConfig) -> list[list[int]]:
    """Group post indices into clusters of shared content."""
    uf = _UnionFind(len(posts))

    # Near-duplicate text.
    hasher = MinHasher(seed=cfg.seed)
    text_ids, signatures = [], []
    for i, post in enumerate(posts):
        norm = normalize_text(post.text)
        if len(norm) >= cfg.min_text_chars:
            text_ids.append(i)
            signatures.append(hasher.signature(shingles(norm, cfg.shingle_size)))
    for a, b, _ in near_duplicate_pairs(signatures, cfg.text_threshold):
        uf.union(text_ids[a], text_ids[b])

    # Near-duplicate images.
    img_owner, img_hashes = [], []
    for i, post in enumerate(posts):
        for h in post.media_hashes:
            try:
                img_hashes.append(int(h, 16))
            except ValueError:
                continue
            img_owner.append(i)
    for a, b, _ in similar_hash_pairs(img_hashes, cfg.image_max_distance):
        uf.union(img_owner[a], img_owner[b])

    # Same canonical URL, or explicit forwards of the same original message.
    boilerplate = _boilerplate_urls(posts, cfg.max_url_reuse)
    msg_index = {post.key: i for i, post in enumerate(posts)}
    first_with: dict[str, int] = {}
    for i, post in enumerate(posts):
        keys = [f"url:{u}" for u in _canonical_urls(post) if u not in boilerplate]
        if post.forward_of:
            keys.append(f"fwd:{post.forward_of}")
            if post.forward_of in msg_index:
                uf.union(msg_index[post.forward_of], i)
        for key in keys:
            uf.union(first_with.setdefault(key, i), i)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(posts)):
        groups[uf.find(i)].append(i)
    return [g for g in groups.values() if len(g) > 1]


def _canonical_urls(post: Post) -> list[str]:
    return [u for u in map(normalize_url, post.urls) if u]


def _boilerplate_urls(posts: list[Post], max_reuse: int) -> set[str]:
    """URLs a single channel attaches to many of its posts (footers, "join us" links).

    Linking on these would merge everything a channel ever posted into one cluster.
    """
    per_channel: Counter[tuple[str, str]] = Counter()
    for post in posts:
        for url in set(_canonical_urls(post)):
            per_channel[(post.channel, url)] += 1
    return {url for (_, url), n in per_channel.items() if n > max_reuse}


def _split_events(posts: list[Post], gap: timedelta) -> list[list[Post]]:
    events, current = [], [posts[0]]
    for prev, post in zip(posts, posts[1:], strict=False):
        if post.timestamp - prev.timestamp > gap:
            events.append(current)
            current = []
        current.append(post)
    events.append(current)
    return events


def densest_burst(posts: list[Post], window: timedelta) -> list[Post]:
    """Return the time window (of length ``window``) touching the most distinct channels."""
    best: tuple[int, int, int] = (0, 0, 0)  # (distinct channels, start, end)
    counts: Counter[str] = Counter()
    left = 0
    for right, post in enumerate(posts):
        counts[post.channel] += 1
        while post.timestamp - posts[left].timestamp > window:
            counts[posts[left].channel] -= 1
            if counts[posts[left].channel] == 0:
                del counts[posts[left].channel]
            left += 1
        if len(counts) > best[0]:
            best = (len(counts), left, right)
    _, start, end = best
    return posts[start : end + 1]


def _shared_values(values_per_post: list[list[str]], min_share: float = 0.5) -> list[str]:
    counts = Counter(v for values in values_per_post for v in set(values))
    need = max(2, int(len(values_per_post) * min_share))
    return [v for v, c in counts.most_common() if c >= need]


def detect(posts: list[Post], cfg: DetectionConfig | None = None) -> DetectionResult:
    cfg = cfg or DetectionConfig()
    posts = sorted(posts, key=lambda p: p.timestamp)

    candidates: list[Campaign] = []
    for cluster in link_posts(posts, cfg):
        cluster_posts = [posts[i] for i in sorted(cluster)]
        for event in _split_events(cluster_posts, cfg.event_gap):
            burst = densest_burst(event, cfg.burst_window)
            if len({p.channel for p in burst}) < cfg.min_channels:
                continue
            campaign = Campaign(id=0, posts=burst)
            # The first post of the whole event can precede the burst (seeding).
            campaign.origin_post = event[0]
            campaign.shared_urls = _shared_values([_canonical_urls(p) for p in burst])
            campaign.shared_media = _shared_values([p.media_hashes for p in burst])
            candidates.append(campaign)

    graph = coordination_graph(candidates)
    communities = detect_communities(graph, cfg.seed)

    for campaign in candidates:
        campaign.signals = score_campaign(campaign, graph, cfg.burst_window)
        campaign.score = round(sum(s.contribution for s in campaign.signals), 3)
        members = Counter(communities.get(c) for c in campaign.channels)
        campaign.community = members.most_common(1)[0][0] if members else None

    campaigns = sorted(
        (c for c in candidates if c.score >= cfg.min_score), key=lambda c: -c.score
    )
    for n, campaign in enumerate(campaigns, start=1):
        campaign.id = n
    return DetectionResult(campaigns, graph, communities, len(posts))


def coordination_graph(campaigns: list[Campaign]) -> nx.Graph:
    """Channels are nodes; edge weight = number of bursts two channels shared."""
    graph = nx.Graph()
    for campaign in campaigns:
        channels = campaign.channels
        for channel in channels:
            if graph.has_node(channel):
                graph.nodes[channel]["bursts"] += 1
            else:
                graph.add_node(channel, bursts=1)
        for a, b in combinations(sorted(channels), 2):
            if graph.has_edge(a, b):
                graph[a][b]["weight"] += 1
            else:
                graph.add_edge(a, b, weight=1)
    return graph


def detect_communities(graph: nx.Graph, seed: int = 7) -> dict[str, int]:
    """Louvain communities over edges seen in more than one burst.

    One-off co-occurrences happen naturally (everyone covers big news), so only
    repeated co-participation is treated as evidence of a shared operator.
    """
    repeated = nx.Graph()
    repeated.add_edges_from(
        (a, b, d) for a, b, d in graph.edges(data=True) if d["weight"] > 1
    )
    if repeated.number_of_edges() == 0:
        return {}
    groups = nx.community.louvain_communities(repeated, weight="weight", seed=seed)
    ranked = sorted((g for g in groups if len(g) > 1), key=len, reverse=True)
    return {channel: n for n, group in enumerate(ranked, start=1) for channel in group}
