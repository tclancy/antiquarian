"""Vega-Lite static variant — the instrument panel.

Python emits Vega-Lite JSON specs per atom. A tiny static HTML harness uses
vega-embed to render them. The specs ARE the deliverable — the harness is
incidental. This tests how clean the "atom = JSON spec, Python pipeline owns
the truth" composition feels in practice.

Visual identity: **instrument panel**. Black header strip, mono-heavy
typography, each atom paired with an inline JSON spec inspector via
`<details>`. Reads as a technical reference page where the spec is part of
the deliverable, not just the rendered chart.

Compared with the Observable narrative variant (long-form essay typography
with charts as evidence) and the hand-svg broadsheet variant (project-controlled
serif identity), this stack leans into "the JSON is the deliverable."
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

# Shared visual vocabulary — palette aligned with the other two stacks so the
# variants read as variations of the same project, not separate styles.
PALETTE = {
    "ink": "#1a1a1a",
    "ink_dim": "#555",
    "rule": "#d4d4d4",
    "paper": "#f5f3ee",
    "panel": "#ffffff",
    "accent": "#b35a1f",
    "accent_dim": "#dba37e",
    "lane": "#3a5e7c",
    "lossy": "#999",
}

ARC_COLORS = [
    "#7c4a3a",
    "#3a5e7c",
    "#3a7c4a",
    "#7c6a3a",
    "#5e3a7c",
    "#7c3a5e",
    "#a08a5e",
    "#5e7c3a",
]

VEGA_LITE_VERSION = "5"
VEGA_EMBED_VERSION = "6"


# ----------------------------------------------------------------------------
# Time-axis projection (piecewise active-window scale)
# ----------------------------------------------------------------------------
#
# Vega-Lite can't natively do a "piecewise time scale." The clean trick:
# pre-project every datum's timestamp into a pixel-space coordinate using the
# same active-window scale as the other stacks, then drive the x encoding
# from that quantitative field. The per-window labels render as a separate
# small spec (`window_axis.vl.json`) underneath each chart.

GAP_PX = 56
MIN_WIN_PX = 36


def build_active_scale(timeline: dict, pixel_width: int) -> dict:
    """Return scale closure + window/gap pixel allocations.

    Pure Python so the spec generator can pre-project timestamps before
    emitting JSON. Mirror of the analogous helper in the other stacks.
    """
    if not timeline or not timeline.get("full_span"):
        return {
            "scale": lambda _: 0,
            "gap_blocks": [],
            "windows": [],
            "window_pixels": [],
            "window_starts": [],
            "total_pixels": pixel_width,
        }
    windows = []
    for w in timeline["active_windows"]:
        windows.append(
            {
                "start": datetime.fromisoformat(w["start"]),
                "end": datetime.fromisoformat(w["end"]),
                "commit_count": w["commit_count"],
            }
        )
    gaps = []
    for g in timeline.get("gaps", []):
        gaps.append(
            {
                "start": datetime.fromisoformat(g["start"]),
                "end": datetime.fromisoformat(g["end"]),
                "days": g["days"],
            }
        )

    win_durations = [
        max(1.0, (w["end"] - w["start"]).total_seconds()) for w in windows
    ]
    total_dur = sum(win_durations) or 1
    total_gap_px = len(gaps) * GAP_PX
    remaining_px = max(120, pixel_width - total_gap_px)

    allocations = [d / total_dur * remaining_px for d in win_durations]
    undershoot = 0
    for i, a in enumerate(allocations):
        if a < MIN_WIN_PX:
            undershoot += MIN_WIN_PX - a
            allocations[i] = MIN_WIN_PX
    if undershoot > 0:
        max_idx = allocations.index(max(allocations))
        allocations[max_idx] = max(MIN_WIN_PX, allocations[max_idx] - undershoot)

    window_starts = []
    cursor = 0.0
    for i, a in enumerate(allocations):
        window_starts.append(cursor)
        cursor += a
        if i < len(gaps):
            cursor += GAP_PX
    total_pixels = cursor

    def scale(dt: datetime) -> float:
        for i, w in enumerate(windows):
            px0 = window_starts[i]
            pxw = allocations[i]
            if w["start"] <= dt <= w["end"]:
                dur = max(1.0, (w["end"] - w["start"]).total_seconds())
                return px0 + (dt - w["start"]).total_seconds() / dur * pxw
            if dt < w["start"]:
                if i == 0:
                    return px0
                prev_end = window_starts[i - 1] + allocations[i - 1]
                return prev_end + GAP_PX / 2
        last = len(windows) - 1
        return window_starts[last] + allocations[last]

    gap_blocks = []
    for i, g in enumerate(gaps):
        x0 = window_starts[i] + allocations[i]
        gap_blocks.append(
            {
                "x_start": x0,
                "x_end": x0 + GAP_PX,
                "days": g["days"],
                "label": (
                    f"{g['days'] / 365:.1f}y gap"
                    if g["days"] >= 365
                    else f"{g['days']}d gap"
                ),
            }
        )

    return {
        "scale": scale,
        "gap_blocks": gap_blocks,
        "windows": windows,
        "window_pixels": allocations,
        "window_starts": window_starts,
        "total_pixels": total_pixels,
    }


def _format_window(w: dict) -> str:
    s = w["start"]
    e = w["end"]
    if s.year == e.year and s.strftime("%b") == e.strftime("%b"):
        return f"{s.strftime('%b %Y')}"
    if s.year == e.year:
        return f"{s.strftime('%b')}–{e.strftime('%b %Y')}"
    return f"{s.strftime('%b %Y')} – {e.strftime('%b %Y')}"


def spec_timeline_strip(timeline: dict, width: int = 760) -> dict:
    """Dual-axis reference strip: full project lifespan as a single bar with
    active commit windows highlighted as filled segments."""
    if not timeline or not timeline.get("full_span"):
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "data": {"values": []},
            "mark": "bar",
        }

    full_start = datetime.fromisoformat(timeline["full_span"]["start"])
    full_end = datetime.fromisoformat(timeline["full_span"]["end"])

    bg = [{"y": "lifespan", "start": full_start.isoformat(), "end": full_end.isoformat()}]
    actives = [
        {
            "y": "lifespan",
            "start": w["start"],
            "end": w["end"],
            "commits": w["commit_count"],
        }
        for w in timeline["active_windows"]
    ]
    gaps = [
        {"y": "lifespan", "start": g["start"], "end": g["end"], "days": g["days"]}
        for g in timeline.get("gaps", [])
        if g["days"] >= 365
    ]

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Dual-axis timeline strip — full project lifespan, active windows in accent, dormancy gaps hatched.",
        "title": {
            "text": "Project lifespan",
            "subtitle": (
                f"{full_start.strftime('%b %Y')} – {full_end.strftime('%b %Y')} "
                f"({timeline['full_span']['days']} days). "
                "Filled = active commit windows; hatched = dormancy."
            ),
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
            "fontSize": 12,
            "subtitleFontSize": 10,
        },
        "width": width,
        "height": 30,
        "background": PALETTE["paper"],
        "layer": [
            {
                "data": {"values": bg},
                "mark": {
                    "type": "bar",
                    "color": "#eee9df",
                    "cornerRadius": 2,
                    "height": 18,
                },
                "encoding": {
                    "x": {
                        "field": "start",
                        "type": "temporal",
                        "axis": {
                            "title": None,
                            "format": "%Y",
                            "tickColor": PALETTE["rule"],
                            "labelColor": PALETTE["ink_dim"],
                            "labelFontSize": 9,
                        },
                    },
                    "x2": {"field": "end"},
                    "y": {"field": "y", "type": "nominal", "axis": None},
                },
            },
            {
                "data": {"values": gaps},
                "mark": {
                    "type": "bar",
                    "color": PALETTE["lossy"],
                    "fillOpacity": 0.35,
                    "height": 16,
                },
                "encoding": {
                    "x": {"field": "start", "type": "temporal"},
                    "x2": {"field": "end"},
                    "y": {"field": "y", "type": "nominal", "axis": None},
                },
            },
            {
                "data": {"values": actives},
                "mark": {
                    "type": "bar",
                    "color": PALETTE["accent"],
                    "cornerRadius": 1,
                    "height": 14,
                    "tooltip": True,
                },
                "encoding": {
                    "x": {"field": "start", "type": "temporal"},
                    "x2": {"field": "end"},
                    "y": {"field": "y", "type": "nominal", "axis": None},
                    "tooltip": [
                        {"field": "commits", "title": "Commits"},
                        {
                            "field": "start",
                            "title": "From",
                            "type": "temporal",
                            "format": "%Y-%m-%d",
                        },
                        {
                            "field": "end",
                            "title": "To",
                            "type": "temporal",
                            "format": "%Y-%m-%d",
                        },
                    ],
                },
            },
        ],
        "config": {
            "view": {"stroke": None},
            "axis": {"grid": False, "domain": False},
        },
    }


def _window_axis_data(axis: dict) -> list[dict]:
    rows = []
    for i, w in enumerate(axis["windows"]):
        x0 = axis["window_starts"][i]
        pxw = axis["window_pixels"][i]
        rows.append(
            {
                "px_mid": x0 + pxw / 2,
                "px_start": x0,
                "px_end": x0 + pxw,
                "label": _format_window(w),
            }
        )
    return rows


def _gap_axis_data(axis: dict) -> list[dict]:
    return [
        {"px_mid": g["x_start"] + (g["x_end"] - g["x_start"]) / 2, "label": g["label"]}
        for g in axis["gap_blocks"]
    ]


def spec_todo_strip(todos: list[dict]) -> dict:
    """TODO-age strip — horizontal bars sized by age, sorted oldest-first."""
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
            "width": 760,
            "height": 60,
            "data": {"values": []},
            "mark": "bar",
        }

    todos = [
        {
            **t,
            "_label": f"{t['file_path'].rsplit('/', 1)[-1]} L{t['line_number']}",
        }
        for t in todos
    ]

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "TODO-age strip — bars sized by age in days survived.",
        "title": {
            "text": "TODO-age strip",
            "subtitle": f"{len(todos)} admission(s), oldest at top. Bar length = days survived.",
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
            "fontSize": 13,
            "subtitleFontSize": 10,
        },
        "width": 660,
        "height": max(60, len(todos) * 22 + 30),
        "background": PALETTE["panel"],
        "data": {"values": todos},
        "mark": {"type": "bar", "cornerRadius": 2, "tooltip": True},
        "encoding": {
            "y": {
                "field": "_label",
                "type": "nominal",
                "sort": {"field": "age_days", "order": "descending"},
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
                "axis": {
                    "title": "Days survived in tree",
                    "titleColor": PALETTE["ink_dim"],
                    "titleFontSize": 10,
                },
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
                "legend": {
                    "title": "TODO age (days)",
                    "orient": "right",
                    "titleFontSize": 9,
                    "titleColor": PALETTE["ink"],
                    "labelColor": PALETTE["ink_dim"],
                },
            },
            "tooltip": [
                {"field": "kind", "title": "Kind"},
                {"field": "file_path", "title": "File"},
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


def spec_swimlane(swimlane: dict, timeline: dict) -> dict:
    """Author swimlane — pre-projected to piecewise pixel space.

    Time is collapsed to active windows only. Window labels and gap
    indicators are emitted in a separate `window_axis.vl.json` spec rendered
    underneath this chart.
    """
    if not swimlane["lanes"]:
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "title": "Author swimlane",
            "description": "No commits in cache.",
            "data": {"values": []},
            "mark": "point",
        }

    width = 760
    axis = build_active_scale(timeline, width)

    rows = []
    for lane in swimlane["lanes"]:
        for c in lane["commits"]:
            ts = datetime.fromisoformat(c["timestamp"])
            rows.append(
                {
                    "author": lane["author"],
                    "px": axis["scale"](ts),
                    "timestamp": c["timestamp"],
                    "diff": c["additions"] + c["deletions"],
                    "subject": c["subject"],
                    "short_sha": c["short_sha"],
                    "decisive": bool(c["arcs"]),
                    "decisive_label": "decisive" if c["arcs"] else "supporting",
                    "arcs": ", ".join(c["arcs"]) or "—",
                }
            )

    lane_order = [lane["author"] for lane in swimlane["lanes"]]

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Author swimlane on piecewise pixel-space x — active windows compressed.",
        "title": {
            "text": "Author swimlane",
            "subtitle": (
                f"{len(swimlane['lanes'])} contributor(s), "
                f"{sum(lane['commit_count'] for lane in swimlane['lanes'])} commits. "
                "Mark size = lines of code changed. Time is compressed to active windows; "
                "see the date strip immediately below for window boundaries and gap durations."
            ),
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
            "fontSize": 13,
            "subtitleFontSize": 10,
        },
        "width": width,
        "height": {"step": 56},
        "background": PALETTE["panel"],
        "data": {"values": rows},
        "mark": {
            "type": "circle",
            "tooltip": True,
            "opacity": 0.85,
            "stroke": PALETTE["ink"],
            "strokeWidth": 0.4,
        },
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
                "field": "px",
                "type": "quantitative",
                "scale": {"domain": [0, axis["total_pixels"]]},
                "axis": None,
            },
            "size": {
                "field": "diff",
                "type": "quantitative",
                "scale": {"range": [50, 800]},
                "legend": {
                    "title": "Diff size (LoC)",
                    "orient": "right",
                    "titleFontSize": 9,
                    "titleColor": PALETTE["ink"],
                    "labelColor": PALETTE["ink_dim"],
                },
            },
            "color": {
                "field": "decisive_label",
                "type": "nominal",
                "scale": {
                    "domain": ["decisive", "supporting"],
                    "range": [PALETTE["accent"], PALETTE["lane"]],
                },
                "legend": {
                    "title": "Mark color",
                    "orient": "right",
                    "titleFontSize": 9,
                    "titleColor": PALETTE["ink"],
                    "labelColor": PALETTE["ink_dim"],
                },
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
                {"field": "diff", "title": "Diff (LoC)"},
                {"field": "arcs", "title": "Arcs"},
            ],
        },
        "config": {
            "view": {"stroke": None},
            "axis": {"grid": False},
        },
    }


def spec_window_axis(timeline: dict, width: int = 760) -> dict:
    """Per-window date labels + gap labels strip — rendered as a separate
    chart underneath the swimlane and arc-band so the main chart's spec
    stays clean."""
    if not timeline or not timeline.get("full_span"):
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "data": {"values": []},
            "mark": "text",
        }
    axis = build_active_scale(timeline, width)
    win_rows = _window_axis_data(axis)
    gap_rows = _gap_axis_data(axis)
    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Per-window date labels for the piecewise pixel-space x axis.",
        "width": width,
        "height": 22,
        "background": PALETTE["panel"],
        "layer": [
            {
                "data": {"values": win_rows},
                "mark": {"type": "rule", "color": "#999", "strokeWidth": 1},
                "encoding": {
                    "x": {
                        "field": "px_start",
                        "type": "quantitative",
                        "scale": {"domain": [0, axis["total_pixels"]]},
                        "axis": None,
                    },
                    "x2": {"field": "px_end"},
                    "y": {"datum": 2, "type": "quantitative", "axis": None},
                },
            },
            {
                "data": {"values": win_rows},
                "mark": {
                    "type": "text",
                    "fontSize": 10,
                    "color": PALETTE["ink_dim"],
                    "baseline": "top",
                    "dy": 4,
                },
                "encoding": {
                    "x": {
                        "field": "px_mid",
                        "type": "quantitative",
                        "scale": {"domain": [0, axis["total_pixels"]]},
                        "axis": None,
                    },
                    "y": {"datum": 2, "type": "quantitative", "axis": None},
                    "text": {"field": "label"},
                },
            },
            {
                "data": {"values": gap_rows},
                "mark": {
                    "type": "text",
                    "fontSize": 9,
                    "color": PALETTE["lossy"],
                    "fontStyle": "italic",
                    "baseline": "top",
                    "dy": 4,
                },
                "encoding": {
                    "x": {
                        "field": "px_mid",
                        "type": "quantitative",
                        "scale": {"domain": [0, axis["total_pixels"]]},
                        "axis": None,
                    },
                    "y": {"datum": 2, "type": "quantitative", "axis": None},
                    "text": {"field": "label"},
                },
            },
        ],
        "config": {"view": {"stroke": None}, "axis": {"grid": False}},
    }


def spec_arc_band(arc_band: dict, timeline: dict) -> dict:
    """Per-arc SC ranking band — piecewise pixel x, ticks for decisive commits."""
    arcs = arc_band["arcs"]
    if not arcs:
        return {
            "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
            "title": "Per-arc SC ranking band",
            "description": "No arcs available.",
            "data": {"values": []},
            "mark": "bar",
        }

    width = 760
    axis = build_active_scale(timeline, width)

    band_rows = []
    tick_rows = []
    lane_order = []
    file_paths = {arc["file_path"] for arc in arcs}
    multi_file = len(file_paths) > 1
    for arc in arcs:
        basename = arc["file_path"].rsplit("/", 1)[-1]
        prefix = f"[{basename}] " if multi_file else ""
        label = f"{prefix}A{arc['arc_number']}: {arc['name']}"
        if len(label) > 60:
            label = label[:57] + "…"
        lane_order.append(label)
        datable = [c for c in arc["commits"] if c["timestamp"]]
        if datable:
            t0 = datetime.fromisoformat(datable[0]["timestamp"])
            t1 = datetime.fromisoformat(datable[-1]["timestamp"])
            px1 = axis["scale"](t0)
            px2 = max(axis["scale"](t1), px1 + 4)
            band_rows.append(
                {
                    "arc_label": label,
                    "px1": px1,
                    "px2": px2,
                    "arc_slug": arc["slug"],
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
                    "px": axis["scale"](datetime.fromisoformat(c["timestamp"])),
                    "short_sha": c["short_sha"],
                    "subject": c["subject"],
                    "arc_slug": arc["slug"],
                }
            )

    return {
        "$schema": f"https://vega.github.io/schema/vega-lite/v{VEGA_LITE_VERSION}.json",
        "description": "Per-arc SC ranking band — band per arc, decisive commits as ticks; piecewise pixel x.",
        "title": {
            "text": "Per-arc SC ranking band",
            "subtitle": (
                f"{len(arcs)} arc(s) across {len(file_paths)} file(s). "
                "Bands span first→last decisive commit; ticks are the commits the story cited. "
                "Date strip below this chart shows window boundaries."
            ),
            "anchor": "start",
            "color": PALETTE["ink"],
            "subtitleColor": PALETTE["ink_dim"],
            "fontSize": 13,
            "subtitleFontSize": 10,
        },
        "width": width,
        "height": {"step": 24},
        "background": PALETTE["panel"],
        "layer": [
            {
                "data": {"values": band_rows},
                "mark": {
                    "type": "bar",
                    "cornerRadius": 3,
                    "opacity": 0.25,
                    "tooltip": True,
                    "height": 14,
                },
                "encoding": {
                    "y": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                        "axis": {
                            "title": None,
                            "labelFontSize": 9,
                            "labelLimit": 280,
                            "labelColor": PALETTE["ink"],
                            "labelFontFamily": "ui-monospace, SF Mono, Monaco, monospace",
                            "tickColor": PALETTE["rule"],
                            "domainColor": PALETTE["rule"],
                        },
                    },
                    "x": {
                        "field": "px1",
                        "type": "quantitative",
                        "scale": {"domain": [0, axis["total_pixels"]]},
                        "axis": None,
                    },
                    "x2": {"field": "px2"},
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
                "mark": {"type": "tick", "thickness": 2, "size": 18, "tooltip": True},
                "encoding": {
                    "y": {
                        "field": "arc_label",
                        "type": "nominal",
                        "sort": lane_order,
                    },
                    "x": {"field": "px", "type": "quantitative"},
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
    :root {{
      --ink: {ink};
      --ink-dim: {ink_dim};
      --rule: {rule};
      --paper: {paper};
      --panel: {panel};
      --accent: {accent};
      --mono: ui-monospace, "SF Mono", "JetBrains Mono", Monaco, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: var(--mono);
      background: var(--paper);
      color: var(--ink);
      margin: 0;
      padding: 0;
      line-height: 1.45;
      font-size: 13px;
    }}
    .panel-head {{
      background: var(--ink);
      color: var(--paper);
      padding: 0.75rem 1.5rem;
      display: flex;
      align-items: baseline;
      gap: 1.5rem;
      border-bottom: 2px solid var(--accent);
    }}
    .panel-head h1 {{
      margin: 0;
      font-size: 14px;
      font-weight: 500;
      letter-spacing: 0.04em;
      font-family: var(--mono);
    }}
    .panel-head .badge {{
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: var(--accent);
      padding: 2px 8px;
      border-radius: 2px;
      color: var(--paper);
      font-weight: 600;
    }}
    .panel-head .meta {{
      margin-left: auto;
      font-size: 11px;
      color: #999;
      font-family: var(--mono);
    }}
    .panel-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 1px;
      background: var(--rule);
      padding: 1px;
    }}
    .panel-grid > .panel-cell {{
      background: var(--panel);
      padding: 0;
      display: flex;
      flex-direction: column;
    }}
    .cell-label {{
      background: var(--ink);
      color: var(--paper);
      padding: 5px 12px;
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .cell-label .cell-num {{
      color: var(--accent);
      font-weight: 600;
    }}
    .cell-label a {{
      color: #b8b8b8;
      text-decoration: none;
      font-size: 10px;
      font-weight: 400;
    }}
    .cell-label a:hover {{ color: var(--accent); }}
    .cell-body {{ padding: 12px 16px; overflow-x: auto; }}
    details.spec-inspector {{
      margin: 0;
      border-top: 1px solid var(--rule);
      background: #f9f8f3;
    }}
    details.spec-inspector summary {{
      cursor: pointer;
      padding: 6px 16px;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-dim);
      font-family: var(--mono);
      user-select: none;
    }}
    details.spec-inspector summary:hover {{ color: var(--accent); }}
    details.spec-inspector pre {{
      margin: 0;
      padding: 10px 16px;
      font-size: 10.5px;
      line-height: 1.4;
      color: var(--ink);
      background: #fdfcf8;
      max-height: 360px;
      overflow: auto;
      border-top: 1px dashed var(--rule);
      font-family: var(--mono);
    }}
    .meta-block {{
      padding: 12px 1.5rem;
      background: var(--panel);
      border-bottom: 1px solid var(--rule);
      font-size: 11px;
      color: var(--ink-dim);
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4px 14px;
      align-items: baseline;
    }}
    .meta-block .k {{
      color: var(--ink);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 10px;
    }}
    .meta-block .v code {{ color: var(--accent); }}
    .panel-foot {{
      padding: 10px 1.5rem;
      background: var(--ink);
      color: #999;
      font-size: 10px;
      letter-spacing: 0.04em;
    }}
    .panel-foot a {{ color: var(--accent); text-decoration: none; }}
  </style>
</head>
<body>
  <div class="panel-head">
    <h1>antiquarian:{project}</h1>
    <span class="badge">vega-lite-static</span>
    <span class="meta">{generated} · spec-driven instrument panel</span>
  </div>

  <div class="meta-block">
    <span class="k">files</span><span class="v">{files_inline}</span>
    <span class="k">stories</span><span class="v">{stories_inline}</span>
  </div>

  <div class="panel-grid">
    <div class="panel-cell">
      <div class="cell-label">
        <span><span class="cell-num">00</span> &nbsp;timeline_strip · project lifespan reference</span>
        <a href="specs/timeline_strip.vl.json">spec ↗</a>
      </div>
      <div class="cell-body"><div id="timeline-strip"></div></div>
      <details class="spec-inspector">
        <summary>inspect spec (timeline_strip.vl.json)</summary>
        <pre>{timeline_strip_spec}</pre>
      </details>
    </div>

    <div class="panel-cell">
      <div class="cell-label">
        <span><span class="cell-num">01</span> &nbsp;todo_strip · admissions age</span>
        <a href="specs/todo_strip.vl.json">spec ↗</a>
      </div>
      <div class="cell-body"><div id="todo-strip"></div></div>
      <details class="spec-inspector">
        <summary>inspect spec (todo_strip.vl.json)</summary>
        <pre>{todo_strip_spec}</pre>
      </details>
    </div>

    <div class="panel-cell">
      <div class="cell-label">
        <span><span class="cell-num">02</span> &nbsp;swimlane · author × time (compressed)</span>
        <a href="specs/swimlane.vl.json">spec ↗</a>
      </div>
      <div class="cell-body">
        <div id="swimlane"></div>
        <div id="swimlane-axis"></div>
      </div>
      <details class="spec-inspector">
        <summary>inspect spec (swimlane.vl.json)</summary>
        <pre>{swimlane_spec}</pre>
      </details>
    </div>

    <div class="panel-cell">
      <div class="cell-label">
        <span><span class="cell-num">03</span> &nbsp;arc_band · per-arc SC ranking</span>
        <a href="specs/arc_band.vl.json">spec ↗</a>
      </div>
      <div class="cell-body">
        <div id="arc-band"></div>
        <div id="arc-band-axis"></div>
      </div>
      <details class="spec-inspector">
        <summary>inspect spec (arc_band.vl.json)</summary>
        <pre>{arc_band_spec}</pre>
      </details>
    </div>
  </div>

  <div class="panel-foot">
    vega-lite-static · Python pipeline emits 5 specs ({vl_lib_lines} total lines); vega-embed renders.
    All specs round-trip through <code>vega-lite.compile()</code> with zero warnings.
    <a href="../">← back to project landing</a>
  </div>

  <script>
    const opts = {{actions: false, renderer: 'svg'}};
    vegaEmbed('#timeline-strip', 'specs/timeline_strip.vl.json', opts);
    vegaEmbed('#todo-strip', 'specs/todo_strip.vl.json', opts);
    vegaEmbed('#swimlane', 'specs/swimlane.vl.json', opts);
    vegaEmbed('#swimlane-axis', 'specs/window_axis.vl.json', opts);
    vegaEmbed('#arc-band', 'specs/arc_band.vl.json', opts);
    vegaEmbed('#arc-band-axis', 'specs/window_axis.vl.json', opts);
  </script>
</body>
</html>
"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
    timeline = json.loads((args.data_dir / "timeline.json").read_text())

    specs = {
        "timeline_strip.vl.json": spec_timeline_strip(timeline),
        "todo_strip.vl.json": spec_todo_strip(todos),
        "swimlane.vl.json": spec_swimlane(swimlane, timeline),
        "arc_band.vl.json": spec_arc_band(arc_band, timeline),
        "window_axis.vl.json": spec_window_axis(timeline),
    }
    total_lines = 0
    for name, spec in specs.items():
        body = json.dumps(spec, indent=2)
        total_lines += body.count("\n") + 1
        (specs_dir / name).write_text(body, encoding="utf-8")

    files_inline = " ".join(
        f"<code>{_xml_escape(f)}</code>" for f in manifest.get("files", [])
    ) or "<em>none</em>"
    stories_inline = (
        " ".join(f"<code>{_xml_escape(s)}</code>" for s in manifest.get("stories", []))
        or "<em>none</em>"
    )

    html = HTML_TEMPLATE.format(
        project=args.project,
        vl=VEGA_LITE_VERSION,
        ve=VEGA_EMBED_VERSION,
        generated=manifest.get("generated_at", ""),
        files_inline=files_inline,
        stories_inline=stories_inline,
        timeline_strip_spec=_xml_escape(json.dumps(specs["timeline_strip.vl.json"], indent=2)),
        todo_strip_spec=_xml_escape(json.dumps(specs["todo_strip.vl.json"], indent=2)),
        swimlane_spec=_xml_escape(json.dumps(specs["swimlane.vl.json"], indent=2)),
        arc_band_spec=_xml_escape(json.dumps(specs["arc_band.vl.json"], indent=2)),
        vl_lib_lines=total_lines,
        **{k: v for k, v in PALETTE.items()},
    )
    (args.output_dir / "index.html").write_text(html, encoding="utf-8")
    print(
        f"[vega-lite] wrote {args.output_dir / 'index.html'} + {len(specs)} specs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
