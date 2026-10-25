"""Synthetic benchmark: one simulated week of public channel activity.

All channels, domains and messages are fictional. The scenario mixes:

- **Background noise**: unrelated everyday posts from ~80 organic channels.
- **Organic news events**: many channels covering the same story in their own
  words over several hours (should NOT be flagged).
- **Viral forward**: one popular post natively forwarded by many channels over
  hours (should score LOW).
- **Copied official statement**: aggregators copy-pasting the same statement
  within half an hour. A deliberate hard case; it's fine to rank it MEDIUM,
  and it must rank below the real campaigns.
- **Network A**: 30 sockpuppet channels running 5 Arabic/English campaigns.
- **Network B**: 12 channels running 3 Hebrew campaigns.

Because the ground truth is known, the benchmark measures precision and
recall, not just "it found something".
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from echoscope.models import Post
from echoscope.normalize import extract_urls

START = datetime(2026, 3, 2, 6, 0, tzinfo=timezone.utc)
PLATFORM = "telegram"

_PREFIX = ["daily", "breaking", "voice", "street", "north", "south", "free", "real", "open",
           "city", "free_press", "people", "eye", "frontline", "radar", "pulse"]
_SUFFIX = ["news", "report", "updates", "wire", "now", "today", "watch", "media", "press",
           "post", "live", "desk", "brief", "insider", "times"]
_VOCAB = (
    "market prices weather traffic school football match council meeting road works "
    "hospital clinic festival concert power outage water supply bus line train strike "
    "election poll minister budget tax fuel bread vegetables harbour port airport flight "
    "delay police patrol fire brigade bridge tunnel park museum exhibition university "
    "students exam results heat wave rain storm wind coast beach fishing farmers harvest "
    "olive season wedding funeral mosque church synagogue holiday shops discount bank "
    "currency rate exchange internet mobile network phone repair cars accident injured "
    "court ruling judge lawyer protest march square crowd speech mayor village town"
).split()

# Campaign templates (fictional, generic narratives).
_NETWORK_A_CAMPAIGNS = [
    "عاجل: انسحاب الجنود من القاعدة قرب الحدود الشمالية والفيديو يظهر حالة الذعر بين القوات",
    "BREAKING: Leaked documents show the army is hiding heavy losses from the public, "
    "share before it gets deleted",
    "مصادر خاصة: القيادة فقدت السيطرة على الوضع في الجنوب والجنود يرفضون الأوامر",
    "Eyewitnesses report hospitals in the capital are overflowing and officials are "
    "silent about the real numbers",
    "عاجل وخطير: الحكومة تخطط لإغلاق الإنترنت بالكامل الليلة، انشروا قبل الحذف",
]
_NETWORK_B_CAMPAIGNS = [
    "דחוף: דיווחים על קריסת מערכת החשמל באזור המרכז, הממשלה מסתירה את האמת מהציבור",
    "מקור בכיר חושף: המערכת הצבאית לא מוכנה בכלל ומסתירים את זה מאיתנו, תפיצו לכולם",
    "בלעדי: אלפי משפחות עוזבות את הצפון והתקשורת מסרבת לדווח על כך, שתפו עכשיו",
]
_ORGANIC_STORIES = [
    ("storm", ["Heavy storm hits the coast", "Coastal storm causes flooding",
               "Storm damage reported along the shore", "Flooding after overnight storm"]),
    ("budget", ["Parliament passes new budget", "Budget vote approved late at night",
                "New state budget finally approved", "Lawmakers approve spending plan"]),
    ("match", ["Home team wins the cup final", "Dramatic cup final ends in victory",
               "Fans celebrate cup final win", "Cup final decided in extra time"]),
    ("fire", ["Large fire near the industrial zone", "Firefighters battle blaze in industrial area",
              "Smoke seen over industrial zone after fire", "Industrial zone fire under control"]),
]
_STATEMENT = ("Official statement: the ministry confirms that the main highway will be closed "
              "tonight from 22:00 until 05:00 for scheduled maintenance works.")


@dataclass
class Scenario:
    posts: list[Post]
    campaigns: dict[str, set[str]] = field(default_factory=dict)  # label -> post keys
    negatives: dict[str, set[str]] = field(default_factory=dict)
    networks: dict[str, set[str]] = field(default_factory=dict)  # label -> channel names


class _Builder:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.posts: list[Post] = []
        self._ids: dict[str, int] = {}
        self._names: set[str] = set()

    def channel(self) -> str:
        while True:
            name = (f"{self.rng.choice(_PREFIX)}_{self.rng.choice(_SUFFIX)}"
                    f"{self.rng.choice(['', '', str(self.rng.randint(1, 99))])}")
            if name not in self._names:
                self._names.add(name)
                return name

    def post(self, channel: str, ts: datetime, text: str, **kw) -> Post:
        self._ids[channel] = self._ids.get(channel, 1000) + self.rng.randint(1, 3)
        kw.setdefault("urls", extract_urls(text))
        p = Post(PLATFORM, channel, str(self._ids[channel]), ts, text, **kw)
        self.posts.append(p)
        return p

    def noise_text(self) -> str:
        return " ".join(self.rng.choices(_VOCAB, k=self.rng.randint(12, 30)))

    def phash(self) -> int:
        return self.rng.getrandbits(64)

    def variant_hash(self, h: int, max_bits: int = 4) -> str:
        for bit in self.rng.sample(range(64), self.rng.randint(0, max_bits)):
            h ^= 1 << bit
        return f"{h:016x}"

    def mutate(self, text: str, channel: str) -> str:
        """Small edits sockpuppets make so copies don't look identical."""
        r = self.rng
        words = text.split()
        if r.random() < 0.5 and len(words) > 6:
            i = r.randrange(len(words))
            words.insert(i, r.choice(["!!", "⚠️", "🔴", "🚨", "‼️"]))
        if r.random() < 0.4:
            words.pop(r.randrange(len(words)))
        out = " ".join(words)
        out = out.replace("ا", "أ", 1) if r.random() < 0.3 else out
        if r.random() < 0.5:
            emoji = r.choice(["🔴", "🚨", "⚡", ""])
            tag = r.choice(["#عاجل", "#breaking", "#דחוף", ""])
            out = f"{emoji} {out} {tag}"
        if r.random() < 0.6:
            out += f"\n\nSubscribe: https://t.me/{channel}"
        return out.strip()


def build_scenario(seed: int = 42) -> Scenario:
    b = _Builder(seed)
    rng = b.rng
    week = timedelta(days=7)
    organic = [b.channel() for _ in range(80)]
    network_a = [b.channel() for _ in range(30)]
    network_b = [b.channel() for _ in range(12)]
    scenario = Scenario(posts=b.posts)
    scenario.networks = {"network_a": set(network_a), "network_b": set(network_b)}

    def at(offset: timedelta) -> datetime:
        return START + offset

    # Background noise from everyone (sockpuppets post filler too, to look normal).
    for ch in organic + network_a + network_b:
        for _ in range(rng.randint(15, 40)):
            ts = at(timedelta(seconds=rng.uniform(0, week.total_seconds())))
            media = [f"{b.phash():016x}"] if rng.random() < 0.2 else []
            footer = f"\nhttps://t.me/{ch}" if rng.random() < 0.5 else ""
            b.post(ch, ts, b.noise_text() + footer, media_hashes=media)

    # Organic news: same story, different words, spread over hours.
    for n, (topic, headlines) in enumerate(_ORGANIC_STORIES):
        t0 = at(timedelta(days=1 + n * 1.4, hours=rng.uniform(0, 10)))
        keys = set()
        for ch in rng.sample(organic, rng.randint(20, 40)):
            ts = t0 + timedelta(minutes=rng.expovariate(1 / 90))
            text = f"{rng.choice(headlines)}. {b.noise_text()}"
            keys.add(b.post(ch, ts, text, media_hashes=[f"{b.phash():016x}"]).key)
        scenario.negatives[f"organic_{topic}"] = keys

    # Viral post natively forwarded over several hours.
    source = organic[0]
    t0 = at(timedelta(days=2, hours=14))
    viral = b.post(source, t0, "Incredible footage of the northern lights seen from the hills "
                   "last night, photo by our reader", media_hashes=[f"{b.phash():016x}"])
    keys = {viral.key}
    for ch in rng.sample(organic[1:], 25):
        ts = t0 + timedelta(minutes=rng.expovariate(1 / 120))
        keys.add(b.post(ch, ts, viral.text, media_hashes=viral.media_hashes,
                        forward_of=viral.key).key)
    scenario.negatives["viral_forward"] = keys

    # Aggregators copy-pasting an official statement (hard negative).
    t0 = at(timedelta(days=4, hours=9))
    keys = set()
    for ch in rng.sample(organic, 9):
        ts = t0 + timedelta(minutes=rng.uniform(0, 25))
        keys.add(b.post(ch, ts, _STATEMENT).key)
    scenario.negatives["official_statement"] = keys

    # Coordinated campaigns: seed, then a tight burst of mutated copies.
    def run_network(label: str, members: list[str], templates: list[str], spread_min: float,
                    domain: str) -> None:
        for n, template in enumerate(templates):
            t0 = at(timedelta(days=0.5 + n * (6 / len(templates)), hours=rng.uniform(0, 8)))
            image = b.phash()
            link = f"https://{domain}/article/{rng.randint(1000, 9999)}?utm_source=tg"
            seeder, *amplifiers = rng.sample(members, rng.randint(int(len(members) * 0.7),
                                                                  len(members)))
            keys = {b.post(seeder, t0, f"{template}\n{link}", urls=[link],
                           media_hashes=[b.variant_hash(image)]).key}
            for ch in amplifiers:
                ts = t0 + timedelta(minutes=rng.uniform(1, spread_min))
                text = b.mutate(template, ch)
                urls = [link] if rng.random() < 0.7 else []
                if urls:
                    text += f"\n{link}"
                keys.add(b.post(ch, ts, text, urls=urls,
                                media_hashes=[b.variant_hash(image)]).key)
            scenario.campaigns[f"{label}_{n + 1}"] = keys

    run_network("network_a", network_a, _NETWORK_A_CAMPAIGNS, 14, "truth-today-news.example")
    run_network("network_b", network_b, _NETWORK_B_CAMPAIGNS, 20, "hadashot-emet.example")

    b.posts.sort(key=lambda p: p.timestamp)
    return scenario
