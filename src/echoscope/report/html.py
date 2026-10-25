"""Self-contained HTML report.

The report is a single file with inline SVG and CSS and no external scripts,
so it opens offline and can be attached to an investigation as-is.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import networkx as nx

from echoscope import __version__
from echoscope.detect.pipeline import DetectionResult
from echoscope.models import Campaign

_PALETTE_SIZE = 8

_CSS = """
:root {
  --bg: #f7f7f5; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6b66; --line: #e3e2dd;
  --high: #c2362b; --medium: #b7791f; --low: #8a8a84; --accent: #2a5bd7;
  --c1: #2a5bd7; --c2: #c2362b; --c3: #1f8a5b; --c4: #8e44ad; --c5: #b7791f;
  --c6: #0e7c86; --c7: #c0458a; --c8: #5d6d7e; --c0: #b9b8b2;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #161615; --panel: #1f1f1d; --ink: #ecebe6; --muted: #9b9a94; --line: #34332f;
    --high: #ef6b5f; --medium: #e0a84a; --low: #8f8e88; --accent: #7aa2ff;
    --c1: #7aa2ff; --c2: #ef6b5f; --c3: #4fc18d; --c4: #b88ae0; --c5: #e0a84a;
    --c6: #45b8c2; --c7: #e57bb5; --c8: #9aa8b5; --c0: #55544f;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", "Noto Sans", "Noto Sans Arabic",
  "Noto Sans Hebrew", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 19px; margin: 36px 0 12px; }
.muted { color: var(--muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin: 20px 0; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; }
.stat b { display: block; font-size: 24px; }
details { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  margin: 10px 0; overflow: hidden; }
summary { cursor: pointer; padding: 12px 14px; display: flex; gap: 12px; align-items: baseline;
  flex-wrap: wrap; list-style: none; }
summary::-webkit-details-marker { display: none; }
.badge { font-weight: 700; font-size: 12px; padding: 2px 8px; border-radius: 99px;
  color: #fff; white-space: nowrap; }
.HIGH { background: var(--high); } .MEDIUM { background: var(--medium); }
.LOW { background: var(--low); }
.headline { flex: 1 1 320px; min-width: 0; overflow-wrap: anywhere; }
.body { padding: 0 14px 16px; border-top: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
td, th { text-align: start; padding: 5px 8px 5px 0; border-bottom: 1px solid var(--line);
  vertical-align: top; }
.bar { height: 8px; background: var(--line); border-radius: 4px; min-width: 80px; }
.bar i { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
.scroll { overflow-x: auto; }
svg { display: block; max-width: 100%; height: auto; }
.scroll table { min-width: 620px; }
.scroll svg.timeline { min-width: 680px; }
.scroll svg.network { min-width: 600px; }
svg text { fill: var(--muted); font-size: 11px; }
.axis { stroke: var(--line); }
.copy { fill: var(--accent); } .fwd { fill: none; stroke: var(--accent); stroke-width: 1.5; }
.origin { fill: var(--high); }
.edge { stroke: var(--muted); stroke-opacity: .35; }
blockquote { margin: 0 0 12px; padding: 8px 12px; border-inline-start: 3px solid var(--line);
  overflow-wrap: anywhere; white-space: pre-wrap; }
code { font-size: 13px; overflow-wrap: anywhere; }
footer { margin-top: 40px; font-size: 13px; }
"""


def _timeline_svg(c: Campaign, width: int = 900) -> str:
    posts = [c.origin] + [p for p in c.posts if p is not c.origin]
    channels = list(dict.fromkeys(p.channel for p in posts))[:40]
    row_h, left, top = 16, 150, 10
    height = top + row_h * len(channels) + 30
    t0 = c.origin.timestamp
    total = max(1.0, *((p.timestamp - t0).total_seconds() / 60 for p in posts))
    plot_w = width - left - 20

    def x(p) -> float:
        return left + plot_w * ((p.timestamp - t0).total_seconds() / 60) / total

    parts = [f'<svg class="timeline" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Posting timeline for campaign {c.id}">']
    row = {ch: i for i, ch in enumerate(channels)}
    for ch, i in row.items():
        y = top + i * row_h + row_h / 2
        parts.append(f'<text x="{left - 8}" y="{y + 4}" text-anchor="end">@{escape(ch)}</text>')
        parts.append(f'<line class="axis" x1="{left}" x2="{width - 20}" y1="{y}" y2="{y}"/>')
    step = next(s for s in (1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 1440, 1e9) if total / s <= 8)
    tick, axis_y = 0.0, height - 12
    while tick <= total:
        tx = left + plot_w * tick / total
        parts.append(f'<text x="{tx}" y="{axis_y}" text-anchor="middle">+{tick:.0f}m</text>')
        tick += step
    for p in posts:
        if p.channel not in row:
            continue
        y = top + row[p.channel] * row_h + row_h / 2
        cls = "origin" if p is c.origin else ("fwd" if p.is_forward else "copy")
        r = 6 if p is c.origin else 4
        mins = (p.timestamp - t0).total_seconds() / 60
        parts.append(f'<circle class="{cls}" cx="{x(p):.1f}" cy="{y}" r="{r}">'
                     f'<title>@{escape(p.channel)} +{mins:.1f} min</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def _network_svg(result: DetectionResult, width: int = 900) -> str:
    """Draw each connected group of repeatedly co-posting channels in its own cell.

    Laying out disconnected networks together pushes them to the edges and
    collapses each one into a blob, so every component is laid out separately.
    """
    graph = nx.Graph()
    graph.add_edges_from(
        (a, b, d) for a, b, d in result.graph.edges(data=True) if d["weight"] > 1
    )
    if graph.number_of_nodes() == 0:
        return '<p class="muted">No channels co-appeared in more than one burst.</p>'
    components = sorted(nx.connected_components(graph), key=len, reverse=True)[:12]
    per_row, cell_h, pad = 3, 300, 28
    cell_w = width / min(per_row, len(components))
    rows = -(-len(components) // per_row)
    height = int(rows * cell_h)

    parts = [f'<svg class="network" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Channel coordination network">']
    for idx, nodes in enumerate(components):
        sub = graph.subgraph(nodes)
        ox, oy = (idx % per_row) * cell_w, (idx // per_row) * cell_h
        if len(nodes) > 2:
            pos = nx.spring_layout(sub, seed=7, k=1.8 / len(nodes) ** 0.5, iterations=200)
        else:
            pos = {n: (i * 2 - 1.0, 0.0) for i, n in enumerate(sorted(nodes))}
        xs = [x for x, _ in pos.values()]
        ys = [y for _, y in pos.values()]
        spanx, spany = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
        box = min(cell_w, cell_h - 24) - 2 * pad

        def xy(node, pos=pos, xs=xs, ys=ys, spanx=spanx, spany=spany, ox=ox, oy=oy, box=box):
            x, y = pos[node]
            return (ox + cell_w / 2 + ((x - min(xs)) / spanx - 0.5) * box,
                    oy + pad + box / 2 + ((y - min(ys)) / spany - 0.5) * box)

        for a, b, d in sub.edges(data=True):
            (x1, y1), (x2, y2) = xy(a), xy(b)
            parts.append(f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                         f'y2="{y2:.1f}" stroke-width="{min(d["weight"], 6) * 0.4:.1f}"/>')
        communities = Counter(result.communities.get(n) for n in nodes)
        for node in nodes:
            x, y = xy(node)
            community = result.communities.get(node)
            color = f"var(--c{(community - 1) % _PALETTE_SIZE + 1})" if community else "var(--c0)"
            bursts = result.graph.nodes[node].get("bursts", 1)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3 + min(bursts, 8)}" '
                         f'fill="{color}" stroke="var(--panel)" stroke-width="1">'
                         f'<title>@{escape(node)}: network #{community or "-"}, '
                         f'{bursts} bursts</title></circle>')
        main = communities.most_common(1)[0][0]
        label = f"Network #{main}" if main else "Unassigned"
        parts.append(f'<text x="{ox + cell_w / 2:.1f}" y="{oy + cell_h - 10}" '
                     f'text-anchor="middle">{label} · {len(nodes)} channels</text>')
    parts.append("</svg>")
    return "".join(parts)


def _campaign_html(c: Campaign) -> str:
    rows = "".join(
        f'<tr><td>{escape(s.name)}</td><td><div class="bar"><i style="width:{s.value * 100:.0f}%">'
        f'</i></div></td><td>{s.value:.2f} &times; {s.weight:.2f}</td>'
        f"<td>{escape(s.reason)}</td></tr>"
        for s in c.signals
    )
    facts = [
        f"<b>Origin:</b> @{escape(c.origin.channel)} at {c.origin.timestamp:%Y-%m-%d %H:%M} UTC",
        f"<b>Spread:</b> {len(c.channels)} channels in {c.span_minutes:.0f} minutes",
    ]
    if c.community:
        facts.append(f"<b>Network:</b> #{c.community}")
    if c.shared_urls:
        facts.append(f"<b>Shared link:</b> <code>{escape(c.shared_urls[0])}</code>")
    if c.shared_media:
        facts.append(f"<b>Shared image pHash:</b> <code>{escape(c.shared_media[0])}</code>")
    sample = escape(c.origin.text[:600])
    return f"""
<details{' open' if c.id == 1 else ''}>
  <summary><span class="badge {c.confidence}">{c.confidence} {c.score:.2f}</span>
    <span class="headline" dir="auto">#{c.id} {escape(c.headline)}</span>
    <span class="muted">{len(c.channels)} channels · {c.span_minutes:.0f} min</span></summary>
  <div class="body">
    <p>{" · ".join(facts)}</p>
    <p class="muted">Origin post:</p><blockquote dir="auto">{sample}</blockquote>
    <h3>Why it was flagged</h3>
    <div class="scroll"><table><tr><th>Signal</th><th></th><th>Value</th><th>Reason</th></tr>
    {rows}</table></div>
    <h3>Timeline</h3>
    <p class="muted">Red = origin, filled = copy-paste, hollow = native forward.</p>
    <div class="scroll">{_timeline_svg(c)}</div>
  </div>
</details>"""


def render(result: DetectionResult, title: str = "Echoscope report") -> str:
    flagged = [c for c in result.campaigns if c.score >= 0.5]
    networks = len(set(result.communities.values()))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    campaigns = "".join(_campaign_html(c) for c in result.campaigns[:50])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{escape(title)}</h1>
<p class="muted">Generated {generated} by Echoscope {__version__}. Scores are leads for
an analyst to verify, not verdicts.</p>
<div class="stats">
  <div class="stat"><b>{result.posts_analyzed:,}</b>posts analysed</div>
  <div class="stat"><b>{len(result.campaigns)}</b>candidate bursts</div>
  <div class="stat"><b>{len(flagged)}</b>scored ≥ 0.5</div>
  <div class="stat"><b>{networks}</b>coordinated networks</div>
</div>
<h2>Campaigns</h2>
{campaigns or '<p class="muted">No campaigns detected.</p>'}
<h2>Coordination network</h2>
<p class="muted">Channels that appeared together in more than one burst. Colour = detected
network; size = number of bursts.</p>
<div class="scroll">{_network_svg(result)}</div>
<footer class="muted">Echoscope analyses public content only. See ETHICS.md.</footer>
</main></body></html>"""


def write_html(result: DetectionResult, path: str | Path, title: str = "Echoscope report") -> None:
    Path(path).write_text(render(result, title), "utf-8")
