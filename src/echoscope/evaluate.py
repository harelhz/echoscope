"""Score detection results against a scenario with known ground truth."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from echoscope.demo import Scenario
from echoscope.detect.pipeline import DetectionResult


@dataclass
class Evaluation:
    precision: float  # flagged campaigns that are real campaigns
    recall: float  # real campaigns that were flagged
    network_purity: dict[str, float]  # share of each planted network found in one community
    matches: list[tuple[int, str, float]]  # (campaign id, best label, score)
    threshold: float


def evaluate(scenario: Scenario, result: DetectionResult, threshold: float = 0.5) -> Evaluation:
    label_of: dict[str, str] = {}
    for label, keys in {**scenario.campaigns, **scenario.negatives}.items():
        for key in keys:
            label_of[key] = label

    matches = []
    found: set[str] = set()
    true_pos = flagged = 0
    for campaign in result.campaigns:
        label, _ = Counter(label_of.get(p.key, "noise") for p in campaign.posts).most_common(1)[0]
        matches.append((campaign.id, label, campaign.score))
        if campaign.score < threshold:
            continue
        flagged += 1
        if label in scenario.campaigns:
            true_pos += 1
            found.add(label)

    purity = {}
    for name, channels in scenario.networks.items():
        communities = Counter(result.communities.get(c) for c in channels)
        communities.pop(None, None)
        purity[name] = communities.most_common(1)[0][1] / len(channels) if communities else 0.0

    return Evaluation(
        precision=true_pos / flagged if flagged else 0.0,
        recall=len(found) / len(scenario.campaigns) if scenario.campaigns else 0.0,
        network_purity=purity,
        matches=matches,
        threshold=threshold,
    )
