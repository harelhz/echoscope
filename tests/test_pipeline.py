from datetime import datetime, timedelta, timezone

import pytest

from echoscope.demo import build_scenario
from echoscope.detect.pipeline import DetectionConfig, densest_burst, detect
from echoscope.evaluate import evaluate
from echoscope.models import Post

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
TEXT = "Leaked documents show officials are hiding the real numbers, share before deletion"


def _post(channel, minutes, text=TEXT, **kw):
    ts = T0 + timedelta(minutes=minutes)
    return Post("test", channel, str(int(minutes * 60)), ts, text, **kw)


def test_tight_copy_paste_burst_is_flagged():
    posts = [_post(f"ch{i}", i * 0.5) for i in range(10)]
    result = detect(posts)
    assert len(result.campaigns) == 1
    campaign = result.campaigns[0]
    assert campaign.origin.channel == "ch0"
    assert len(campaign.channels) == 10


def test_few_channels_is_not_a_campaign():
    posts = [_post(f"ch{i}", i) for i in range(3)]
    assert detect(posts).campaigns == []


def test_slow_spread_is_split_into_events():
    # Same text, but one channel every 8 hours: never a burst of 5.
    posts = [_post(f"ch{i}", i * 480) for i in range(10)]
    assert detect(posts).campaigns == []


def test_forwards_score_lower_than_copies():
    copies = [_post(f"c{i}", i * 0.5) for i in range(10)]
    origin = _post("source", 0, text="Viral text about the northern lights over the hills tonight")
    forwards = [
        _post(f"f{i}", i * 0.5 + 1, text=origin.text, forward_of=origin.key) for i in range(10)
    ]
    scores = {c.origin.channel: c.score for c in detect(copies + [origin] + forwards).campaigns}
    assert scores["c0"] > scores["source"]


def test_channel_footer_links_do_not_merge_unrelated_posts():
    # Every post of each channel carries its own footer link; content is unrelated.
    posts = []
    for c in range(6):
        for m in range(6):
            posts.append(_post(f"ch{c}", c * 60 + m, text=f"unrelated post {c}-{m} " * 5,
                               urls=[f"https://t.me/ch{c}"]))
    assert detect(posts, DetectionConfig(min_channels=2)).campaigns == []


def test_densest_burst_picks_busiest_window():
    early = [_post(f"a{i}", i * 20) for i in range(3)]
    burst = [_post(f"b{i}", 200 + i) for i in range(6)]
    window = densest_burst(early + burst, timedelta(minutes=30))
    assert {p.channel for p in window} == {f"b{i}" for i in range(6)}


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_benchmark_scenario(seed):
    scenario = build_scenario(seed)
    result = detect(scenario.posts)
    ev = evaluate(scenario, result)
    assert ev.recall == 1.0
    assert ev.precision == 1.0
    assert min(ev.network_purity.values()) >= 0.9
    # Organic look-alikes must rank below every planted campaign.
    planted = [s for _, label, s in ev.matches if label in scenario.campaigns]
    organic = [s for _, label, s in ev.matches if label in scenario.negatives]
    assert not organic or max(organic) < min(planted)
