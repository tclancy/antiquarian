"""Hand-rolled SVG variant.

Tests the floor for craft: if hand-rolled atoms feel more intentional than
library output, that tells us the library is overhead. Pure-Python SVG strings,
zero JS, project-controlled visual vocabulary throughout.

This is also where the uncertainty / lossy-region atom lives — per Tom's note in
issue #4, "the channel is too lossy here" needs its own visual language we own
end-to-end. Implemented as a diagonal-hatch fill on the swimlane gap region.

Output: a single static index.html with inline SVG. No JS, no CSS framework, no
build step beyond Python. Open it in a browser and look at it.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

# Project-controlled vocabulary lives here — colors, type sizes, paddings.
# Deliberately constrained palette to keep the output feeling intentional rather
# than chart-library-default.
PALETTE = {
    "ink": "#1a1a1a",  # primary text
    "ink_dim": "#666",  # secondary text
    "rule": "#d4d4d4",  # axis/grid lines
    "rule_dim": "#ececec",  # softer grid
    "paper": "#fafaf7",  # background
    "accent": "#b35a1f",  # decisive marks, TODO bars
    "accent_dim": "#dba37e",  # lighter accent for younger TODOs
    "lane": "#3a5e7c",  # swimlane stroke
    "lossy": "#999",  # uncertainty hatching
}

# Five-arc palette — colors picked to be distinguishable but earthy, not "tag soup".
ARC_COLORS = ["#7c4a3a", "#3a5e7c", "#3a7c4a", "#7c6a3a", "#5e3a7c", "#7c3a5e"]


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _time_axis(times: list[datetime], width: int, x0: int) -> tuple:
    """Return (scale, ticks) where scale(t) -> px, ticks is a list of (x, label)."""
    t_min = min(times)
    t_max = max(times)
    if t_min == t_max:
        t_max = t_min.replace(year=t_min.year + 1)
    span = (t_max - t_min).total_seconds()

    def scale(t: datetime) -> float:
        return x0 + (t - t_min).total_seconds() / span * width

    # Tick every month or two depending on span.
    months_span = max(1, int(span / (60 * 60 * 24 * 30)))
    step = max(1, months_span // 8)
    ticks = []
    # Walk from t_min forward in step-month increments.
    yr, mo = t_min.year, t_min.month
    while True:
        try:
            tick_dt = t_min.replace(
                year=yr, month=mo, day=1, hour=0, minute=0, second=0, microsecond=0
            )
        except ValueError:
            break
        if tick_dt > t_max:
            break
        if tick_dt >= t_min:
            ticks.append((scale(tick_dt), tick_dt.strftime("%b %Y")))
        mo += step
        while mo > 12:
            mo -= 12
            yr += 1
    return scale, ticks


def _hatch_def() -> str:
    """SVG <defs> pattern for the lossy-region hatching atom.

    The lossy-region / uncertainty pattern — diagonal lines on a neutral
    background. Used wherever a span of time has no recoverable commit data.
    Project-defined visual vocabulary, NOT a library default.
    """
    return f"""
<defs>
  <pattern id="lossy-hatch" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="6" stroke="{PALETTE["lossy"]}" stroke-width="1" opacity="0.5"/>
  </pattern>
  <pattern id="lossy-hatch-dense" patternUnits="userSpaceOnUse" width="4" height="4" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="4" stroke="{PALETTE["lossy"]}" stroke-width="0.8" opacity="0.7"/>
  </pattern>
</defs>
"""


def render_todo_strip(todos: list[dict]) -> str:
    """TODO-age strip — bars sized by age, sorted by introduction date.

    The whole atom is one chart, one question: "what admissions has this codebase
    been carrying, and for how long?" No drill-down required to read the answer.
    """
    if not todos:
        return _empty_atom(
            "TODO-age strip",
            "This file currently carries no TODO/FIXME admissions. That itself is a signal of the maintainers' standards.",
        )

    # Layout: oldest on top, newest at bottom. Bar length = age in days.
    max_age = max(t["age_days"] for t in todos)
    bar_max = 800  # px
    row_h = 28
    label_w = 280
    margin_top = 60
    margin_left = label_w + 20
    height = margin_top + row_h * len(todos) + 40
    width = margin_left + bar_max + 80

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="background:{PALETTE["paper"]}; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">',
        _hatch_def(),
        f'<text x="20" y="30" font-size="18" font-weight="600" fill="{PALETTE["ink"]}">TODO-age strip</text>',
        f'<text x="20" y="48" font-size="12" fill="{PALETTE["ink_dim"]}">{len(todos)} admission(s), oldest first. Bar length = days survived.</text>',
    ]

    for i, t in enumerate(todos):
        y = margin_top + i * row_h
        bar_len = (t["age_days"] / max_age) * bar_max if max_age else 0
        # Color by age bucket — older admissions get the saturated accent.
        if t["age_days"] >= 1000:
            color = PALETTE["accent"]
        elif t["age_days"] >= 365:
            color = "#c97a4a"
        else:
            color = PALETTE["accent_dim"]
        label = f"{t['kind']} L{t['line_number']}: {t['text'][:40]}"
        if len(t["text"]) > 40:
            label += "…"
        parts.append(
            f'<text x="{label_w + 10}" y="{y + row_h / 2 + 4}" text-anchor="end" '
            f'font-size="11" font-family="ui-monospace, SF Mono, Monaco, monospace" fill="{PALETTE["ink"]}">{_xml_escape(label)}</text>'
        )
        parts.append(
            f'<rect x="{margin_left}" y="{y + 6}" width="{bar_len}" height="{row_h - 12}" '
            f'fill="{color}" rx="2"/>'
        )
        # Age label at end of bar.
        parts.append(
            f'<text x="{margin_left + bar_len + 6}" y="{y + row_h / 2 + 4}" '
            f'font-size="11" fill="{PALETTE["ink_dim"]}">{t["age_days"]}d · {t["introduced_by"]}</text>'
        )

    return "\n".join(parts) + "\n</svg>"


def render_swimlane(data: dict) -> str:
    """Author swimlane — one row per author, commits as dots on a time axis."""
    lanes = data["lanes"]
    if not lanes:
        return _empty_atom("Author swimlane", "No commits in cache.")

    # Collect all commit timestamps for the X axis scale.
    all_ts = []
    for lane in lanes:
        for c in lane["commits"]:
            all_ts.append(_iso_to_dt(c["timestamp"]))
    if not all_ts:
        return _empty_atom("Author swimlane", "No commit timestamps available.")

    row_h = 56
    margin_top = 80
    margin_left = 200
    chart_w = 800
    margin_right = 40
    width = margin_left + chart_w + margin_right
    height = margin_top + row_h * len(lanes) + 60

    scale, ticks = _time_axis(all_ts, chart_w, margin_left)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="background:{PALETTE["paper"]}; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">',
        _hatch_def(),
        f'<text x="20" y="30" font-size="18" font-weight="600" fill="{PALETTE["ink"]}">Author swimlane</text>',
        f'<text x="20" y="48" font-size="12" fill="{PALETTE["ink_dim"]}">{len(lanes)} contributor(s), {sum(lane["commit_count"] for lane in lanes)} commits. Dot size scales with diff size.</text>',
    ]

    # Identify the largest gap across all timestamps for a lossy-region overlay.
    # The hatching shows where the channel went dark — visual vocabulary owned by
    # the project, not the library.
    sorted_ts = sorted(set(all_ts))
    if len(sorted_ts) > 1:
        gaps = [
            (sorted_ts[i + 1] - sorted_ts[i], sorted_ts[i], sorted_ts[i + 1])
            for i in range(len(sorted_ts) - 1)
        ]
        gap_total = (max(all_ts) - min(all_ts)).total_seconds()
        biggest = max(gaps, key=lambda g: g[0].total_seconds())
        if gap_total > 0 and biggest[0].total_seconds() / gap_total > 0.25:
            gx1 = scale(biggest[1])
            gx2 = scale(biggest[2])
            parts.append(
                f'<rect x="{gx1}" y="{margin_top - 10}" width="{gx2 - gx1}" '
                f'height="{row_h * len(lanes) + 20}" fill="url(#lossy-hatch)" />'
            )
            gap_days = biggest[0].days
            parts.append(
                f'<text x="{(gx1 + gx2) / 2}" y="{margin_top - 16}" text-anchor="middle" '
                f'font-size="10" font-style="italic" fill="{PALETTE["lossy"]}">'
                f"lossy region — {gap_days}d gap</text>"
            )

    # X-axis ticks.
    axis_y = margin_top + row_h * len(lanes) + 20
    parts.append(
        f'<line x1="{margin_left}" y1="{axis_y}" x2="{margin_left + chart_w}" y2="{axis_y}" '
        f'stroke="{PALETTE["rule"]}" stroke-width="1"/>'
    )
    for tx, label in ticks:
        parts.append(
            f'<line x1="{tx}" y1="{axis_y}" x2="{tx}" y2="{axis_y + 5}" stroke="{PALETTE["rule"]}"/>'
        )
        parts.append(
            f'<text x="{tx}" y="{axis_y + 18}" text-anchor="middle" font-size="10" '
            f'fill="{PALETTE["ink_dim"]}">{label}</text>'
        )

    # Lanes.
    max_diff = (
        max(
            (c["additions"] + c["deletions"]) for lane in lanes for c in lane["commits"]
        )
        or 1
    )

    for i, lane in enumerate(lanes):
        y = margin_top + i * row_h + row_h / 2
        # Lane label.
        parts.append(
            f'<text x="{margin_left - 12}" y="{y + 4}" text-anchor="end" font-size="12" '
            f'fill="{PALETTE["ink"]}">{_xml_escape(lane["author"])}</text>'
        )
        parts.append(
            f'<text x="{margin_left - 12}" y="{y + 18}" text-anchor="end" font-size="10" '
            f'fill="{PALETTE["ink_dim"]}">{lane["commit_count"]} commits</text>'
        )
        # Lane stroke — solid from first to last commit.
        first = _iso_to_dt(lane["first_commit"])
        last = _iso_to_dt(lane["last_commit"])
        parts.append(
            f'<line x1="{scale(first)}" y1="{y}" x2="{scale(last)}" y2="{y}" '
            f'stroke="{PALETTE["lane"]}" stroke-width="1" opacity="0.5"/>'
        )
        # Commits as dots, sized by diff.
        for c in lane["commits"]:
            cx = scale(_iso_to_dt(c["timestamp"]))
            diff = c["additions"] + c["deletions"]
            r = 3 + math.sqrt(diff / max_diff) * 8
            color = PALETTE["accent"] if c["arcs"] else PALETTE["lane"]
            stroke = PALETTE["ink"] if c["arcs"] else "none"
            parts.append(
                f'<circle cx="{cx}" cy="{y}" r="{r}" fill="{color}" '
                f'stroke="{stroke}" stroke-width="1" opacity="0.85">'
                f"<title>{_xml_escape(c['short_sha'] + ' — ' + c['subject'])}</title></circle>"
            )

    return "\n".join(parts) + "\n</svg>"


def render_arc_band(data: dict) -> str:
    """Per-arc SC ranking band — one row per arc, decisive commits as highlighted marks."""
    arcs = data["arcs"]
    if not arcs:
        return _empty_atom(
            "Per-arc SC ranking band",
            "No story / arcs available for this project.",
        )

    all_ts = []
    for arc in arcs:
        for c in arc["commits"]:
            if c["timestamp"]:
                all_ts.append(_iso_to_dt(c["timestamp"]))
    if not all_ts:
        return _empty_atom(
            "Per-arc SC ranking band", "Arcs found but none have datable commits."
        )

    row_h = 76
    margin_top = 80
    margin_left = 260
    chart_w = 760
    margin_right = 40
    width = margin_left + chart_w + margin_right
    height = margin_top + row_h * len(arcs) + 50

    scale, ticks = _time_axis(all_ts, chart_w, margin_left)
    axis_y = margin_top + row_h * len(arcs) + 10

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="background:{PALETTE["paper"]}; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">',
        _hatch_def(),
        f'<text x="20" y="30" font-size="18" font-weight="600" fill="{PALETTE["ink"]}">Per-arc SC ranking band</text>',
        f'<text x="20" y="48" font-size="12" fill="{PALETTE["ink_dim"]}">{len(arcs)} arc(s). Each band: a decisive commit sequence the historian named.</text>',
    ]

    # X-axis.
    parts.append(
        f'<line x1="{margin_left}" y1="{axis_y}" x2="{margin_left + chart_w}" y2="{axis_y}" '
        f'stroke="{PALETTE["rule"]}" stroke-width="1"/>'
    )
    for tx, label in ticks:
        parts.append(
            f'<line x1="{tx}" y1="{axis_y}" x2="{tx}" y2="{axis_y + 5}" stroke="{PALETTE["rule"]}"/>'
        )
        parts.append(
            f'<text x="{tx}" y="{axis_y + 18}" text-anchor="middle" font-size="10" '
            f'fill="{PALETTE["ink_dim"]}">{label}</text>'
        )

    file_paths = {arc["file_path"] for arc in arcs}
    multi_file = len(file_paths) > 1
    for i, arc in enumerate(arcs):
        color = ARC_COLORS[i % len(ARC_COLORS)]
        y = margin_top + i * row_h
        basename = arc["file_path"].rsplit("/", 1)[-1]
        # Arc label box.
        if multi_file:
            parts.append(
                f'<text x="{margin_left - 12}" y="{y + 8}" text-anchor="end" font-size="9" '
                f'font-family="ui-monospace, SF Mono, Monaco, monospace" fill="{PALETTE["ink_dim"]}">{_xml_escape(basename)}</text>'
            )
        parts.append(
            f'<text x="{margin_left - 12}" y="{y + 22}" text-anchor="end" font-size="13" '
            f'font-weight="600" fill="{PALETTE["ink"]}">Arc {arc["arc_number"]}: {_xml_escape(arc["name"])}</text>'
        )
        if arc["date_range"]:
            parts.append(
                f'<text x="{margin_left - 12}" y="{y + 34}" text-anchor="end" font-size="10" '
                f'font-style="italic" fill="{PALETTE["ink_dim"]}">{_xml_escape(arc["date_range"])}</text>'
            )
        parts.append(
            f'<text x="{margin_left - 12}" y="{y + 50}" text-anchor="end" font-size="10" '
            f'fill="{PALETTE["ink_dim"]}">{arc["commit_count"]} decisive commits</text>'
        )

        # Compute the arc's time span and draw a band underlay.
        datable = [c for c in arc["commits"] if c["timestamp"]]
        if datable:
            band_x1 = scale(_iso_to_dt(datable[0]["timestamp"]))
            band_x2 = scale(_iso_to_dt(datable[-1]["timestamp"]))
            band_y = y + 22
            band_h = 26
            parts.append(
                f'<rect x="{band_x1}" y="{band_y}" width="{max(band_x2 - band_x1, 2)}" '
                f'height="{band_h}" fill="{color}" opacity="0.18" rx="2"/>'
            )
            # Decisive commit marks as thick vertical ticks on the band.
            for c in arc["commits"]:
                if not c["timestamp"]:
                    continue
                cx = scale(_iso_to_dt(c["timestamp"]))
                parts.append(
                    f'<line x1="{cx}" y1="{band_y}" x2="{cx}" y2="{band_y + band_h}" '
                    f'stroke="{color}" stroke-width="2.5">'
                    f"<title>{_xml_escape(c['short_sha'] + ' — ' + c['subject'])}</title></line>"
                )

        # Missing/uncached commits get the lossy hatching on the band edge.
        missing = [c for c in arc["commits"] if c["missing"]]
        if missing:
            parts.append(
                f'<text x="{margin_left + chart_w + 8}" y="{y + 38}" font-size="10" '
                f'fill="{PALETTE["lossy"]}" font-style="italic">{len(missing)} commit(s) not in cache</text>'
            )

    return "\n".join(parts) + "\n</svg>"


def _empty_atom(title: str, message: str) -> str:
    return f"""<svg viewBox="0 0 900 120" xmlns="http://www.w3.org/2000/svg" style="background:{PALETTE["paper"]}; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
{_hatch_def()}
<rect x="0" y="0" width="900" height="120" fill="url(#lossy-hatch)" opacity="0.4"/>
<text x="20" y="30" font-size="18" font-weight="600" fill="{PALETTE["ink"]}">{title}</text>
<text x="20" y="60" font-size="13" fill="{PALETTE["ink_dim"]}" font-style="italic">{_xml_escape(message)}</text>
</svg>"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_page(project: str, manifest: dict, atoms: dict[str, str]) -> str:
    generated = manifest.get("generated_at", "")
    files = manifest.get("files", [])
    stories = manifest.get("stories", [])

    files_list = "".join(f"<li><code>{_xml_escape(f)}</code></li>" for f in files)
    stories_list = (
        "".join(f"<li><code>{_xml_escape(s)}</code></li>" for s in stories)
        or "<li><em>none</em></li>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antiquarian — hand-rolled SVG — {_xml_escape(project)}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: {PALETTE["paper"]};
      color: {PALETTE["ink"]};
      max-width: 1100px;
      margin: 2rem auto;
      padding: 0 1.5rem;
      line-height: 1.5;
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
    .subtle {{ color: {PALETTE["ink_dim"]}; font-size: 0.85rem; }}
    .atom {{
      margin: 2rem 0;
      border-top: 1px solid {PALETTE["rule"]};
      padding-top: 1.5rem;
    }}
    .meta {{
      display: flex;
      gap: 2rem;
      flex-wrap: wrap;
      font-size: 0.85rem;
      margin: 1rem 0;
      padding: 0.75rem 1rem;
      background: #fff;
      border: 1px solid {PALETTE["rule"]};
      border-radius: 4px;
    }}
    .meta ul {{ margin: 0.25rem 0 0; padding-left: 1.25rem; }}
    code {{ font-family: ui-monospace, "SF Mono", Monaco, monospace; font-size: 0.85em; }}
    .stack-badge {{
      display: inline-block;
      padding: 2px 8px;
      background: {PALETTE["accent"]};
      color: white;
      border-radius: 3px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
  </style>
</head>
<body>
  <h1>{_xml_escape(project)} <span class="stack-badge">hand-rolled SVG</span></h1>
  <div class="subtle">Generated {_xml_escape(generated)}</div>

  <div class="meta">
    <div>
      <strong>Files in cache:</strong>
      <ul>{files_list}</ul>
    </div>
    <div>
      <strong>Stories:</strong>
      <ul>{stories_list}</ul>
    </div>
  </div>

  <div class="atom">{atoms.get("todo_strip", "")}</div>
  <div class="atom">{atoms.get("swimlane", "")}</div>
  <div class="atom">{atoms.get("arc_band", "")}</div>

  <footer class="subtle" style="margin-top: 3rem; border-top: 1px solid {PALETTE["rule"]}; padding-top: 1rem;">
    Hand-rolled SVG variant. Zero JS, zero chart library. Visual vocabulary
    (color, hatching, type sizes) is project-controlled, not library default.
    The diagonal-hatch pattern marks lossy regions — gaps where the channel
    went dark.
  </footer>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    todos = json.loads((args.data_dir / "todos.json").read_text())
    swimlane = json.loads((args.data_dir / "swimlane.json").read_text())
    arc_band = json.loads((args.data_dir / "arc_band.json").read_text())

    atoms = {
        "todo_strip": render_todo_strip(todos),
        "swimlane": render_swimlane(swimlane),
        "arc_band": render_arc_band(arc_band),
    }
    page = render_page(args.project, manifest, atoms)
    (args.output_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"[hand-svg] wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
