"""Vega-Lite static variant.

Python emits Vega-Lite JSON specs per atom. A tiny static HTML harness uses
vega-embed to render them. The specs ARE the deliverable — the harness is
incidental. This tests how clean the "atom = JSON spec, Python pipeline owns
the truth" composition feels in practice.

Compared with the hand-rolled SVG variant, this one trades visual-vocabulary
control for grammar-of-graphics ergonomics. We deliberately keep the styling
sparse and opinionated to avoid library-default vibes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Shared visual vocabulary — keep this aligned with hand-svg/build.py so the
# three stacks read as variants of the same project, not separate styles.
PALETTE = {
    "ink": "#1a1a1a",
    "ink_dim": "#666",
    "rule": "#d4d4d4",
    "paper": "#fafaf7",
    "accent": "#b35a1f",
    "accent_dim": "#dba37e",
    "lane": "#3a5e7c",
    "lossy": "#999",
}

ARC_COLORS = ["#7c4a3a", "#3a5e7c", "#3a7c4a", "#7c6a3a", "#5e3a7c", "#7c3a5e"]

VEGA_LITE_VERSION = "5"
VEGA_EMBED_VERSION = "6"


def spec_todo_strip(todos: list[dict]) -> dict:
    """TODO-age strip — horizontal bars sized by age, sorted by introduction date."""
    # Give each TODO a unique compound label so y-axis rows don't collapse when
    # multiple TODOs share an introducing commit (extremely common — a single
    # cleanup pass tends to land several at once).
    todos = [
        {**t, "_label": f"L{t['line_number']} {t['introduced_short']}"} for t in todos
    ]
    if not todos:
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "description": "Empty TODO strip — file carries no admissions.",
            "title": {
                "text": "TODO-age strip",
                "subtitle": "No TODO/FIXME admissions currently in the file. That itself is a signal.",
                "anchor": "start",
                "color": PALETTE["ink"],
                "subtitleColor": PALETTE["ink_dim"],
            },
            "width": 800,
            "height": 60,
            "data": {"values": []},
            "mark": "bar",
        }

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "TODO-age strip — bars sized by age, sorted by introduction date.",
        "title": {
            "text": "TODO-age strip",
            "subtitle": f"{len(todos)} admission(s), oldest first. Bar length = days survived.",
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
        },
        "width": 700,
        "height": max(60, len(todos) * 22 + 30),
        "background": PALETTE["paper"],
        "data": {"values": todos},
        "mark": {"type": "bar", "cornerRadius": 2, "tooltip": True},
        "encoding": {
            "y": {
                "field": "_label",
                "type": "nominal",
                "sort": {"field": "introduced_at"},
                "axis": {
                    "title": None,
                    "labelFontSize": 10,
                    "labelFontFamily": "ui-monospace, SF Mono, Monaco, monospace",
                    "tickColor": PALETTE["rule"],
                    "domainColor": PALETTE["rule"],
                },
            },
            "x": {
                "field": "age_days",
                "type": "quantitative",
                "axis": {"title": "Age (days)", "titleColor": PALETTE["ink_dim"]},
            },
            "color": {
                "field": "age_days",
                "type": "quantitative",
                "scale": {
                    "domain": [0, 365, 1000, 2000],
                    "range": [
                        PALETTE["accent_dim"],
                        "#c97a4a",
                        PALETTE["accent"],
                        "#7c2a0f",
                    ],
                },
                "legend": {"title": "Age", "orient": "right"},
            },
            "tooltip": [
                {"field": "kind", "title": "Kind"},
                {"field": "line_number", "title": "Line"},
                {"field": "text", "title": "Text"},
                {"field": "introduced_by", "title": "By"},
                {"field": "introduced_short", "title": "Commit"},
                {"field": "age_days", "title": "Age (days)"},
            ],
        },
        "config": {
            "view": {"stroke": None},
            "axis": {"grid": False},
        },
    }


def spec_swimlane(swimlane: dict) -> dict:
    """Author swimlane — one row per author, commits as dots on a time axis."""
    rows = []
    for lane in swimlane["lanes"]:
        for c in lane["commits"]:
            rows.append(
                {
                    "author": lane["author"],
                    "timestamp": c["timestamp"],
                    "diff": c["additions"] + c["deletions"],
                    "subject": c["subject"],
                    "short_sha": c["short_sha"],
                    "decisive": bool(c["arcs"]),
                    "arcs": ", ".join(c["arcs"]) or "—",
                }
            )

    if not rows:
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "title": "Author swimlane",
            "description": "No commits in cache.",
            "data": {"values": []},
            "mark": "point",
        }

    # Deterministic lane order — earliest contributor on top, matching the
    # other stacks.
    lane_order = [lane["author"] for lane in swimlane["lanes"]]

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Author swimlane — one row per author, commits as dots sized by diff, time on X.",
        "title": {
            "text": "Author swimlane",
            "subtitle": f"{len(swimlane['lanes'])} contributor(s), {sum(lane['commit_count'] for lane in swimlane['lanes'])} commits. Dot size scales with diff size; filled dots are decisive commits.",
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
        },
        "width": 760,
        "height": {"step": 50},
        "background": PALETTE["paper"],
        "data": {"values": rows},
        "mark": {"type": "circle", "tooltip": True, "opacity": 0.85},
        "encoding": {
            "y": {
                "field": "author",
                "type": "nominal",
                "sort": lane_order,
                "axis": {
                    "title": None,
                    "labelFontSize": 11,
                    "labelColor": PALETTE["ink"],
                    "tickColor": PALETTE["rule"],
                    "domainColor": PALETTE["rule"],
                },
            },
            "x": {
                "field": "timestamp",
                "type": "temporal",
                "axis": {
                    "title": None,
                    "format": "%b %Y",
                    "labelColor": PALETTE["ink_dim"],
                    "tickColor": PALETTE["rule"],
                },
            },
            "size": {
                "field": "diff",
                "type": "quantitative",
                "scale": {"range": [40, 600]},
                "legend": {"title": "Diff size", "orient": "right"},
            },
            "color": {
                "field": "decisive",
                "type": "nominal",
                "scale": {
                    "domain": [True, False],
                    "range": [PALETTE["accent"], PALETTE["lane"]],
                },
                "legend": {"title": "Decisive?", "orient": "right"},
            },
            "tooltip": [
                {"field": "author", "title": "Author"},
                {"field": "short_sha", "title": "SHA"},
                {
                    "field": "timestamp",
                    "title": "When",
                    "type": "temporal",
                    "format": "%Y-%m-%d %H:%M",
                },
                {"field": "subject", "title": "Subject"},
                {"field": "diff", "title": "Diff"},
                {"field": "arcs", "title": "Arcs"},
            ],
        },
        "config": {
            "view": {"stroke": None},
            "axis": {"grid": True, "gridColor": "#ececec"},
        },
    }


def spec_arc_band(arc_band: dict) -> dict:
    """Per-arc SC ranking band — bands per arc, decisive commits as ticks."""
    arcs = arc_band["arcs"]
    if not arcs:
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "title": "Per-arc SC ranking band",
            "description": "No arcs available.",
            "data": {"values": []},
            "mark": "bar",
        }

    # Build flat rows for both the underlying band rect and the tick marks.
    band_rows = []
    tick_rows = []
    lane_order = []
    # If arcs come from multiple files, disambiguate the labels by prepending
    # the file basename. Single-file projects keep clean "Arc N: name" labels.
    file_paths = {arc["file_path"] for arc in arcs}
    multi_file = len(file_paths) > 1
    for arc in arcs:
        basename = arc["file_path"].rsplit("/", 1)[-1]
        prefix = f"[{basename}] " if multi_file else ""
        label = f"{prefix}Arc {arc['arc_number']}: {arc['name']}"
        lane_order.append(label)
        datable = [c for c in arc["commits"] if c["timestamp"]]
        if datable:
            band_rows.append(
                {
                    "arc_label": label,
                    "arc_slug": arc["slug"],
                    "start": datable[0]["timestamp"],
                    "end": datable[-1]["timestamp"],
                    "commit_count": arc["commit_count"],
                    "date_range": arc["date_range"] or "",
                }
            )
        for c in arc["commits"]:
            if not c["timestamp"]:
                continue
            tick_rows.append(
                {
                    "arc_label": label,
                    "timestamp": c["timestamp"],
                    "short_sha": c["short_sha"],
                    "subject": c["subject"],
                }
            )

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Per-arc SC ranking band — band per arc, decisive commits as ticks.",
        "title": {
            "text": "Per-arc SC ranking band",
            "subtitle": f"{len(arcs)} arc(s). Each band shows the decisive commit sequence the historian named.",
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
        },
        "width": 760,
        "height": {"step": 56},
        "background": PALETTE["paper"],
        "layer": [
            {
                "data": {"values": band_rows},
                "mark": {
                    "type": "bar",
                    "cornerRadius": 3,
                    "opacity": 0.2,
                    "tooltip": True,
                },
                "encoding": {
                    "y": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                        "axis": {
                            "title": None,
                            "labelFontSize": 11,
                            "labelLimit": 220,
                            "labelColor": PALETTE["ink"],
                        },
                    },
                    "x": {
                        "field": "start",
                        "type": "temporal",
                        "axis": {
                            "title": None,
                            "format": "%b %Y",
                            "labelColor": PALETTE["ink_dim"],
                        },
                    },
                    "x2": {"field": "end"},
                    "color": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                        "scale": {"range": ARC_COLORS},
                        "legend": None,
                    },
                    "tooltip": [
                        {"field": "arc_label", "title": "Arc"},
                        {"field": "date_range", "title": "Range"},
                        {"field": "commit_count", "title": "Decisive commits"},
                    ],
                },
            },
            {
                "data": {"values": tick_rows},
                "mark": {"type": "tick", "thickness": 2.5, "size": 26, "tooltip": True},
                "encoding": {
                    "y": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                    },
                    "x": {
                        "field": "timestamp",
                        "type": "temporal",
                    },
                    "color": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                        "scale": {"range": ARC_COLORS},
                        "legend": None,
                    },
                    "tooltip": [
                        {"field": "short_sha", "title": "SHA"},
                        {"field": "subject", "title": "Subject"},
                        {
                            "field": "timestamp",
                            "title": "When",
                            "type": "temporal",
                            "format": "%Y-%m-%d",
                        },
                    ],
                },
            },
        ],
        "config": {
            "view": {"stroke": None},
            "axis": {"grid": False},
        },
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antiquarian — Vega-Lite static — {project}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@{vl}"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@{ve}"></script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      background: {paper};
      color: {ink};
      max-width: 1100px;
      margin: 2rem auto;
      padding: 0 1.5rem;
      line-height: 1.5;
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
    .subtle {{ color: {ink_dim}; font-size: 0.85rem; }}
    .atom {{
      margin: 2rem 0;
      border-top: 1px solid {rule};
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
      border: 1px solid {rule};
      border-radius: 4px;
    }}
    .meta ul {{ margin: 0.25rem 0 0; padding-left: 1.25rem; }}
    code {{ font-family: ui-monospace, "SF Mono", Monaco, monospace; font-size: 0.85em; }}
    .stack-badge {{
      display: inline-block;
      padding: 2px 8px;
      background: {accent};
      color: white;
      border-radius: 3px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .spec-link {{
      font-size: 0.75rem;
      color: {ink_dim};
    }}
  </style>
</head>
<body>
  <h1>{project} <span class="stack-badge">Vega-Lite static</span></h1>
  <div class="subtle">Generated {generated}</div>

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

  <div class="atom">
    <div id="todo-strip"></div>
    <div class="spec-link"><a href="specs/todo_strip.vl.json">spec → todo_strip.vl.json</a></div>
  </div>
  <div class="atom">
    <div id="swimlane"></div>
    <div class="spec-link"><a href="specs/swimlane.vl.json">spec → swimlane.vl.json</a></div>
  </div>
  <div class="atom">
    <div id="arc-band"></div>
    <div class="spec-link"><a href="specs/arc_band.vl.json">spec → arc_band.vl.json</a></div>
  </div>

  <footer class="subtle" style="margin-top: 3rem; border-top: 1px solid {rule}; padding-top: 1rem;">
    Vega-Lite static variant. Python pipeline emits the three JSON specs; this
    HTML harness is just <code>vega-embed</code> calls. The specs are the
    deliverable — open the links to inspect each one. Atom = value, not
    component. Derive-don't-duplicate.
  </footer>

  <script>
    const opts = {{actions: false, renderer: 'svg'}};
    vegaEmbed('#todo-strip', 'specs/todo_strip.vl.json', opts);
    vegaEmbed('#swimlane', 'specs/swimlane.vl.json', opts);
    vegaEmbed('#arc-band', 'specs/arc_band.vl.json', opts);
  </script>
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
    specs_dir = args.output_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    todos = json.loads((args.data_dir / "todos.json").read_text())
    swimlane = json.loads((args.data_dir / "swimlane.json").read_text())
    arc_band = json.loads((args.data_dir / "arc_band.json").read_text())

    specs = {
        "todo_strip.vl.json": spec_todo_strip(todos),
        "swimlane.vl.json": spec_swimlane(swimlane),
        "arc_band.vl.json": spec_arc_band(arc_band),
    }
    for name, spec in specs.items():
        (specs_dir / name).write_text(json.dumps(spec, indent=2), encoding="utf-8")

    files_list = "".join(
        f"<li><code>{f}</code></li>" for f in manifest.get("files", [])
    )
    stories_list = (
        "".join(f"<li><code>{s}</code></li>" for s in manifest.get("stories", []))
        or "<li><em>none</em></li>"
    )

    html = HTML_TEMPLATE.format(
        project=args.project,
        vl=VEGA_LITE_VERSION,
        ve=VEGA_EMBED_VERSION,
        generated=manifest.get("generated_at", ""),
        files_list=files_list,
        stories_list=stories_list,
        **PALETTE,
    )
    (args.output_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"[vega-lite] wrote {args.output_dir / 'index.html'} + {len(specs)} specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
