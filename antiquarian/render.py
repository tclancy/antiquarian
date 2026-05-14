"""Antiquarian broadsheet — hand-rolled SVG renderer (the canonical visual output).

Promoted from ``viz-playground/hand-svg/build.py`` per issue #40 after the
playground feel-test settled the visual-stack question. This is what
``antiquarian render`` produces.

Visual identity: **antiquarian broadsheet** — large serif masthead,
small-caps dateline, drop caps, double-rule borders, woodblock-style
hatched textures for lossy regions, italic side-note glyphs in the margins.
EB Garamond is the preferred face; the page degrades gracefully through
Iowan Old Style → Palatino → Georgia when it can't load.

The full design commitments (Tufte's data-ink discipline, Dürer's
mark-making language for the hatch, 19th-century broadsheet page idiom)
live in ``docs/visual-vocabulary.md``; this file is the implementation.

The committed visual atoms (see ``docs/visual-vocabulary.md``):
  * The lossy region is first-class — gaps are filled with the diagonal
    hatched pattern and labeled with their duration ("Xy gap").
  * Diff size (LoC) is in the swimlane legend.
  * Dual-axis timeline strip (full project lifespan + active windows only)
    sits in the masthead AND atop each atom.
  * Multi-file label prefix and rename-truncated indicator on swimlane bars.

Library entry point: ``render_broadsheet(data: dict) -> str`` returns a
complete self-contained HTML string. ``data`` is whatever
``antiquarian.render_data.extract_render_data`` produced.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from string import Template

# ----------------------------------------------------------------------------
# Visual vocabulary — antiquarian broadsheet.
# Earthy, restrained, serif-friendly. Type sizes are larger than the other
# stacks because this one is the "masthead" page.
# ----------------------------------------------------------------------------
PALETTE = {
    "ink": "#1f1a14",  # print-press dark; warmer than pure black
    "ink_dim": "#5a4e3a",
    "rule": "#a89b80",
    "rule_dim": "#d4c8b0",
    "paper": "#f4ead4",  # parchment yellow
    "paper_alt": "#ede1c4",
    "accent": "#8a3a1f",  # oxide red, like a printer's stamp
    "accent_dim": "#c97a4a",
    "lane": "#3a4e6a",  # deep ink blue
    "lossy": "#7a6f5e",
}

# Eight-arc palette — color-as-pigment, like a 19th-century chromolithograph.
# Pigments from a printer's chase rather than RGB primaries.
ARC_COLORS = [
    "#8a3a1f",  # oxide red
    "#3a4e6a",  # ink blue
    "#3a5e3a",  # forest
    "#7a5c2a",  # ochre
    "#5a3a6a",  # mauve
    "#7a3a4a",  # claret
    "#a0875a",  # bistre
    "#5e6a3a",  # olive
]

GAP_PX = 80
MIN_WIN_PX = 50


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def build_active_scale(timeline: dict, pixel_width: int):
    """Piecewise pixel scale for the dual-axis active-windows timeline.

    Maps a datetime onto the rendered x-coordinate. Each active window
    gets a pixel allocation proportional to its duration (with a
    minimum floor so brief windows stay visible), and gap segments
    between windows get a fixed pixel width regardless of how many
    years the gap actually spanned. The returned ``scale`` callable
    is what the atom renderers use to position commit marks.
    """
    if not timeline or not timeline.get("full_span"):

        def empty_scale(_):
            return 0

        return {
            "scale": empty_scale,
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
                "start": _iso_to_dt(w["start"]),
                "end": _iso_to_dt(w["end"]),
                "commit_count": w["commit_count"],
            }
        )
    gaps = []
    for g in timeline.get("gaps", []):
        gaps.append(
            {
                "start": _iso_to_dt(g["start"]),
                "end": _iso_to_dt(g["end"]),
                "days": g["days"],
            }
        )
    win_dur = [max(1.0, (w["end"] - w["start"]).total_seconds()) for w in windows]
    total_dur = sum(win_dur) or 1
    total_gap_px = len(gaps) * GAP_PX
    remaining_px = max(120, pixel_width - total_gap_px)
    allocations = [d / total_dur * remaining_px for d in win_dur]
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
                    f"{g['days'] / 365:.1f}y" if g["days"] >= 365 else f"{g['days']}d"
                ),
                "long_label": (
                    f"the silence — {g['days']} days"
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


def _defs() -> str:
    """SVG <defs> — the project-controlled patterns. Diagonal hatch for
    lossy regions; cross-hatch as a denser option for deeply lossy stretches."""
    return f"""
<defs>
  <pattern id="lossy-hatch" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="8" stroke="{PALETTE["lossy"]}" stroke-width="1.2" opacity="0.45"/>
  </pattern>
  <pattern id="lossy-hatch-dense" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="5" stroke="{PALETTE["lossy"]}" stroke-width="1" opacity="0.7"/>
  </pattern>
  <pattern id="lossy-crosshatch" patternUnits="userSpaceOnUse" width="9" height="9">
    <line x1="0" y1="0" x2="9" y2="9" stroke="{PALETTE["lossy"]}" stroke-width="0.9" opacity="0.5"/>
    <line x1="9" y1="0" x2="0" y2="9" stroke="{PALETTE["lossy"]}" stroke-width="0.9" opacity="0.5"/>
  </pattern>
</defs>
"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ----------------------------------------------------------------------------
# Atoms
# ----------------------------------------------------------------------------


def render_timeline_masthead(timeline: dict) -> str:
    """The masthead-strip dual-axis ribbon. Wide, sits above the H1 dateline.

    Full project lifespan on a single rule; active windows are filled with
    accent; dormancy regions get the diagonal hatch. Year labels every
    couple of years.
    """
    if not timeline or not timeline.get("full_span"):
        return ""

    width = 900
    height = 90
    full_start = _iso_to_dt(timeline["full_span"]["start"])
    full_end = _iso_to_dt(timeline["full_span"]["end"])
    full_span = (full_end - full_start).total_seconds()
    margin_left = 30
    margin_right = 30
    chart_w = width - margin_left - margin_right

    def sx(dt: datetime) -> float:
        return margin_left + (dt - full_start).total_seconds() / full_span * chart_w

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block; max-width: 100%;">',
        _defs(),
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{PALETTE["paper"]}"/>',
        f'<line x1="{margin_left}" y1="20" x2="{width - margin_right}" y2="20" stroke="{PALETTE["ink"]}" stroke-width="0.8"/>',
        f'<line x1="{margin_left}" y1="23" x2="{width - margin_right}" y2="23" stroke="{PALETTE["ink"]}" stroke-width="0.4"/>',
        f'<text x="{margin_left}" y="14" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" font-size="11" font-style="italic" fill="{PALETTE["ink_dim"]}">'
        f"A reconstructed lifespan, from {full_start.strftime('%B %Y')} to {full_end.strftime('%B %Y')}"
        f" — {timeline['full_span']['days']} days of surviving record.</text>",
    ]

    bar_y = 40
    bar_h = 22
    parts.append(
        f'<rect x="{margin_left}" y="{bar_y}" width="{chart_w}" height="{bar_h}" '
        f'fill="{PALETTE["paper_alt"]}" stroke="{PALETTE["rule"]}" stroke-width="0.8"/>'
    )
    for g in timeline.get("gaps", []):
        if g["days"] < 365:
            continue
        x1 = sx(_iso_to_dt(g["start"]))
        x2 = sx(_iso_to_dt(g["end"]))
        parts.append(
            f'<rect x="{x1}" y="{bar_y}" width="{x2 - x1}" height="{bar_h}" '
            f'fill="url(#lossy-hatch)"/>'
        )
    for w in timeline["active_windows"]:
        x1 = sx(_iso_to_dt(w["start"]))
        x2 = sx(_iso_to_dt(w["end"]))
        width_px = max(2, x2 - x1)
        parts.append(
            f'<rect x="{x1}" y="{bar_y + 2}" width="{width_px}" height="{bar_h - 4}" '
            f'fill="{PALETTE["accent"]}" opacity="0.92">'
            f"<title>{w['commit_count']} commits, {_iso_to_dt(w['start']).date()} – {_iso_to_dt(w['end']).date()}</title>"
            f"</rect>"
        )

    start_year = full_start.year
    end_year = full_end.year
    span_yrs = end_year - start_year + 1
    step = 2 if span_yrs > 8 else 1
    for y in range(start_year, end_year + 1, step):
        d = datetime(y, 1, 1, tzinfo=full_start.tzinfo)
        if d < full_start or d > full_end:
            continue
        x = sx(d)
        parts.append(
            f'<line x1="{x}" y1="{bar_y + bar_h}" x2="{x}" y2="{bar_y + bar_h + 4}" stroke="{PALETTE["rule"]}"/>'
        )
        parts.append(
            f'<text x="{x}" y="{bar_y + bar_h + 16}" text-anchor="middle" font-size="10" '
            f'font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" fill="{PALETTE["ink_dim"]}">{y}</text>'
        )

    parts.append(
        f'<g transform="translate({margin_left}, {bar_y + bar_h + 28})">'
        f'<rect x="0" y="0" width="14" height="10" fill="{PALETTE["accent"]}" opacity="0.92"/>'
        f'<text x="20" y="9" font-size="10" font-family="EB Garamond, serif" fill="{PALETTE["ink_dim"]}">active commit windows</text>'
        f'<rect x="190" y="0" width="14" height="10" fill="url(#lossy-hatch)" stroke="{PALETTE["rule"]}" stroke-width="0.5"/>'
        f'<text x="210" y="9" font-size="10" font-family="EB Garamond, serif" fill="{PALETTE["ink_dim"]}">dormancy (≥1y)</text>'
        f"</g>"
    )

    parts.append("</svg>")
    return "".join(parts)


def _atom_timeline_strip(
    timeline: dict, width: int, margin_left: int, chart_w: int
) -> str:
    """Per-atom narrow reference strip — sits above each chart."""
    if not timeline or not timeline.get("full_span"):
        return ""
    h = 26
    full_start = _iso_to_dt(timeline["full_span"]["start"])
    full_end = _iso_to_dt(timeline["full_span"]["end"])
    full_span = (full_end - full_start).total_seconds()

    def sx(dt: datetime) -> float:
        return margin_left + (dt - full_start).total_seconds() / full_span * chart_w

    parts = [
        f'<rect x="{margin_left}" y="6" width="{chart_w}" height="{h - 12}" '
        f'fill="{PALETTE["paper_alt"]}" stroke="{PALETTE["rule"]}" stroke-width="0.5"/>',
    ]
    for g in timeline.get("gaps", []):
        if g["days"] < 365:
            continue
        x1 = sx(_iso_to_dt(g["start"]))
        x2 = sx(_iso_to_dt(g["end"]))
        parts.append(
            f'<rect x="{x1}" y="6" width="{x2 - x1}" height="{h - 12}" fill="url(#lossy-hatch)"/>'
        )
    for w in timeline["active_windows"]:
        x1 = sx(_iso_to_dt(w["start"]))
        x2 = sx(_iso_to_dt(w["end"]))
        wpx = max(2, x2 - x1)
        parts.append(
            f'<rect x="{x1}" y="8" width="{wpx}" height="{h - 16}" fill="{PALETTE["accent"]}" opacity="0.9"/>'
        )
    return "\n".join(parts)


def _window_axis_labels(axis: dict, margin_left: int, axis_y: float) -> str:
    """Piecewise-pixel-space axis labels — per-window date label + italic gap labels."""
    parts = []
    for i, w in enumerate(axis["windows"]):
        x0 = margin_left + axis["window_starts"][i]
        wpx = axis["window_pixels"][i]
        parts.append(
            f'<line x1="{x0}" y1="{axis_y}" x2="{x0 + wpx}" y2="{axis_y}" '
            f'stroke="{PALETTE["ink"]}" stroke-width="0.8"/>'
        )
        parts.append(
            f'<text x="{x0 + wpx / 2}" y="{axis_y + 14}" text-anchor="middle" '
            f'font-size="11" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" '
            f'fill="{PALETTE["ink"]}">{_format_window(w)}</text>'
        )
    for g in axis["gap_blocks"]:
        cx = margin_left + g["x_start"] + (g["x_end"] - g["x_start"]) / 2
        parts.append(
            f'<text x="{cx}" y="{axis_y + 14}" text-anchor="middle" '
            f'font-size="10" font-family="EB Garamond, serif" font-style="italic" '
            f'fill="{PALETTE["lossy"]}">{g["label"]} gap</text>'
        )
    return "\n".join(parts)


def render_todo_strip(todos: list[dict], timeline: dict) -> str:
    """TODO-age strip — bars sized by age, sorted oldest at top.

    Returns an empty string when the codebase has zero TODOs; the broadsheet
    layout then skips the chapter mark + atom block entirely rather than
    surfacing an empty placeholder. Absence of TODOs is information, but the
    page doesn't need a whole atom to say so — the existence of the file map
    and swimlane already implies "here is what we have."
    """
    if not todos:
        return ""

    max_age = max(t["age_days"] for t in todos)
    bar_max = 720
    row_h = 28
    label_w = 320
    margin_top = 86
    margin_left = label_w + 30
    height = margin_top + row_h * len(todos) + 60
    width = margin_left + bar_max + 100

    todos = sorted(todos, key=lambda t: t["age_days"], reverse=True)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block; max-width: 100%; background: {PALETTE["paper"]};">',
        _defs(),
        _atom_timeline_strip(timeline, width, 20, width - 40),
        f'<text x="20" y="56" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" font-size="22" font-weight="600" fill="{PALETTE["ink"]}">'
        "On the matter of admissions"
        "</text>",
        f'<text x="20" y="76" font-family="EB Garamond, Iowan Old Style, serif" font-size="12" font-style="italic" fill="{PALETTE["ink_dim"]}">'
        f"{len(todos)} TODO and FIXME annotations currently survive in the surveyed files; the bar measures days each has lived in the tree."
        "</text>",
        f'<line x1="20" y1="80" x2="{width - 20}" y2="80" stroke="{PALETTE["ink"]}" stroke-width="0.6"/>',
        f'<text x="{margin_left + bar_max / 2}" y="{margin_top - 10}" text-anchor="middle" font-size="10" '
        f'font-family="EB Garamond, serif" font-style="italic" fill="{PALETTE["ink_dim"]}">days survived</text>',
    ]

    for i, t in enumerate(todos):
        y = margin_top + i * row_h
        bar_len = (t["age_days"] / max_age) * bar_max if max_age else 0
        if t["age_days"] >= 1000:
            color = PALETTE["accent"]
        elif t["age_days"] >= 365:
            color = PALETTE["accent_dim"]
        else:
            color = "#c9a87a"
        basename = t["file_path"].rsplit("/", 1)[-1]
        text_preview = (t["text"][:38] + "…") if len(t["text"]) > 38 else t["text"]
        label = f"{basename} · L{t['line_number']}: {text_preview}"
        if i % 2 == 0:
            parts.append(
                f'<rect x="20" y="{y + 2}" width="{width - 40}" height="{row_h - 4}" '
                f'fill="{PALETTE["paper_alt"]}" opacity="0.55"/>'
            )
        parts.append(
            f'<text x="{label_w + 14}" y="{y + row_h / 2 + 4}" text-anchor="end" '
            f'font-size="11" font-family="EB Garamond, Iowan Old Style, Palatino, serif" fill="{PALETTE["ink"]}">{_xml_escape(label)}</text>'
        )
        parts.append(
            f'<rect x="{margin_left}" y="{y + 6}" width="{bar_len}" height="{row_h - 12}" '
            f'fill="{color}" stroke="{PALETTE["ink"]}" stroke-width="0.4" opacity="0.9">'
            f"<title>{_xml_escape(t['text'])} (introduced {_xml_escape(t['introduced_at'][:10])} by {_xml_escape(t['introduced_by'])})</title>"
            f"</rect>"
        )
        parts.append(
            f'<text x="{margin_left + bar_len + 8}" y="{y + row_h / 2 + 4}" '
            f'font-family="EB Garamond, serif" font-style="italic" font-size="11" fill="{PALETTE["ink_dim"]}">'
            f"{t['age_days']}d &mdash; {_xml_escape(t['introduced_by'])}"
            "</text>"
        )

    legend_y = margin_top + row_h * len(todos) + 24
    parts.append(
        f'<g transform="translate(20, {legend_y})">'
        f'<text x="0" y="0" font-family="EB Garamond, serif" font-style="italic" '
        f'font-size="10" fill="{PALETTE["ink_dim"]}">Age cohorts:</text>'
        f'<rect x="80" y="-9" width="14" height="11" fill="#c9a87a"/><text x="98" y="0" font-size="10" font-family="EB Garamond, serif" fill="{PALETTE["ink_dim"]}">&lt; 1 year</text>'
        f'<rect x="180" y="-9" width="14" height="11" fill="{PALETTE["accent_dim"]}"/><text x="198" y="0" font-size="10" font-family="EB Garamond, serif" fill="{PALETTE["ink_dim"]}">1–3 years</text>'
        f'<rect x="290" y="-9" width="14" height="11" fill="{PALETTE["accent"]}"/><text x="308" y="0" font-size="10" font-family="EB Garamond, serif" fill="{PALETTE["ink_dim"]}">&gt; 3 years (archaeological)</text>'
        f"</g>"
    )

    parts.append("</svg>")
    return "\n".join(parts)


def render_swimlane(swimlane: dict, timeline: dict, file_lifespans: list[dict]) -> str:
    """Author swimlane — dual-axis x, lossy hatching across gaps, Diff size (LoC) legend."""
    lanes = swimlane["lanes"]
    if not lanes:
        return _empty_atom("Author swimlane", "No commits in cache.")

    row_h = 60
    margin_top = 130
    margin_left = 220
    chart_w = 760
    margin_right = 60
    width = margin_left + chart_w + margin_right
    bottom_pad = 80
    height = margin_top + row_h * len(lanes) + bottom_pad

    axis = build_active_scale(timeline, chart_w)
    max_diff = (
        max(
            (c["additions"] + c["deletions"]) for lane in lanes for c in lane["commits"]
        )
        or 1
    )

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block; max-width: 100%; background: {PALETTE["paper"]};">',
        _defs(),
        _atom_timeline_strip(timeline, width, 30, width - 60),
        f'<text x="30" y="64" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" '
        f'font-size="22" font-weight="600" fill="{PALETTE["ink"]}">Hands that touched the work</text>',
        f'<text x="30" y="86" font-family="EB Garamond, Iowan Old Style, serif" font-style="italic" '
        f'font-size="12" fill="{PALETTE["ink_dim"]}">'
        f"{len(lanes)} contributor(s), {sum(lane['commit_count'] for lane in lanes)} commits "
        "in the surviving record. Mark size scales with lines of code (LoC) changed; "
        "filled marks are commits the historian named as decisive."
        "</text>",
        f'<line x1="30" y1="90" x2="{width - 30}" y2="90" stroke="{PALETTE["ink"]}" stroke-width="0.6"/>',
        f'<line x1="30" y1="93" x2="{width - 30}" y2="93" stroke="{PALETTE["ink"]}" stroke-width="0.3"/>',
    ]

    chart_top = margin_top
    chart_bottom = margin_top + row_h * len(lanes)
    for g in axis["gap_blocks"]:
        x0 = margin_left + g["x_start"]
        parts.append(
            f'<rect x="{x0}" y="{chart_top}" width="{g["x_end"] - g["x_start"]}" '
            f'height="{chart_bottom - chart_top}" fill="url(#lossy-hatch)" />'
        )
        cy = (chart_top + chart_bottom) / 2
        parts.append(
            f'<text x="{x0 + (g["x_end"] - g["x_start"]) / 2}" y="{cy}" '
            f'text-anchor="middle" font-family="EB Garamond, serif" font-style="italic" '
            f'font-size="13" fill="{PALETTE["lossy"]}">{_xml_escape(g["long_label"])}</text>'
        )

    for i, w in enumerate(axis["windows"]):
        x0 = margin_left + axis["window_starts"][i]
        wpx = axis["window_pixels"][i]
        parts.append(
            f'<rect x="{x0}" y="{chart_top - 4}" width="{wpx}" height="{chart_bottom - chart_top + 8}" '
            f'fill="none" stroke="{PALETTE["rule"]}" stroke-width="0.6"/>'
        )

    truncated = [f for f in file_lifespans if f["likely_rename_truncated"]]
    if truncated:
        notes_x = margin_left + chart_w + 10
        parts.append(
            f'<text x="{notes_x}" y="{margin_top - 4}" font-family="EB Garamond, serif" '
            f'font-style="italic" font-size="10" fill="{PALETTE["accent"]}">'
            f"{len(truncated)} file(s):</text>"
        )
        parts.append(
            f'<text x="{notes_x}" y="{margin_top + 9}" font-family="EB Garamond, serif" '
            f'font-style="italic" font-size="9" fill="{PALETTE["ink_dim"]}">"--follow"</text>'
        )
        parts.append(
            f'<text x="{notes_x}" y="{margin_top + 20}" font-family="EB Garamond, serif" '
            f'font-style="italic" font-size="9" fill="{PALETTE["ink_dim"]}">lost the chain.</text>'
        )

    for i, lane in enumerate(lanes):
        y = margin_top + i * row_h + row_h / 2
        parts.append(
            f'<text x="{margin_left - 16}" y="{y - 2}" text-anchor="end" '
            f'font-family="EB Garamond, Iowan Old Style, Palatino, serif" font-size="14" font-weight="600" '
            f'fill="{PALETTE["ink"]}">{_xml_escape(lane["author"])}</text>'
        )
        parts.append(
            f'<text x="{margin_left - 16}" y="{y + 14}" text-anchor="end" '
            f'font-family="EB Garamond, serif" font-size="10" font-style="italic" '
            f'fill="{PALETTE["ink_dim"]}">{lane["commit_count"]} commits</text>'
        )
        parts.append(
            f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + chart_w}" y2="{y}" '
            f'stroke="{PALETTE["rule_dim"]}" stroke-width="0.6"/>'
        )
        for c in lane["commits"]:
            cx = margin_left + axis["scale"](_iso_to_dt(c["timestamp"]))
            diff = c["additions"] + c["deletions"]
            r = 4 + math.sqrt(diff / max_diff) * 14
            decisive = bool(c["arcs"])
            fill = PALETTE["accent"] if decisive else PALETTE["lane"]
            stroke = PALETTE["ink"] if decisive else PALETTE["rule"]
            parts.append(
                f'<circle cx="{cx}" cy="{y}" r="{r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="0.8" opacity="0.88">'
                f"<title>{_xml_escape(c['short_sha'] + ' — ' + c['subject'] + ' (' + str(diff) + ' LoC)')}</title>"
                "</circle>"
            )

    axis_y = chart_bottom + 10
    parts.append(_window_axis_labels(axis, margin_left, axis_y))

    leg_y = height - 32
    parts.append(
        f'<g transform="translate(30, {leg_y})">'
        f'<text x="0" y="0" font-family="EB Garamond, serif" font-size="11" '
        f'font-style="italic" font-weight="600" fill="{PALETTE["ink"]}">Diff size (LoC):</text>'
        f'<circle cx="120" cy="-3" r="4" fill="{PALETTE["lane"]}" opacity="0.6"/>'
        f'<text x="130" y="1" font-family="EB Garamond, serif" font-size="10" '
        f'fill="{PALETTE["ink_dim"]}">{int(max_diff * 0.05)}</text>'
        f'<circle cx="190" cy="-3" r="9" fill="{PALETTE["lane"]}" opacity="0.6"/>'
        f'<text x="206" y="1" font-family="EB Garamond, serif" font-size="10" '
        f'fill="{PALETTE["ink_dim"]}">{int(max_diff * 0.25)}</text>'
        f'<circle cx="270" cy="-3" r="17" fill="{PALETTE["lane"]}" opacity="0.6"/>'
        f'<text x="294" y="1" font-family="EB Garamond, serif" font-size="10" '
        f'fill="{PALETTE["ink_dim"]}">{max_diff}</text>'
        f'<circle cx="430" cy="-3" r="6" fill="{PALETTE["accent"]}" stroke="{PALETTE["ink"]}" stroke-width="0.8"/>'
        f'<text x="442" y="1" font-family="EB Garamond, serif" font-style="italic" font-size="11" '
        f'fill="{PALETTE["ink_dim"]}">decisive commit (named in story)</text>'
        f'<circle cx="640" cy="-3" r="6" fill="{PALETTE["lane"]}"/>'
        f'<text x="652" y="1" font-family="EB Garamond, serif" font-style="italic" font-size="11" '
        f'fill="{PALETTE["ink_dim"]}">supporting commit</text>'
        f"</g>"
    )

    parts.append("</svg>")
    return "\n".join(parts)


def render_arc_band(arc_band: dict, timeline: dict) -> str:
    """Per-arc SC ranking band — broadsheet style."""
    arcs = arc_band["arcs"]
    if not arcs:
        return _empty_atom("Per-arc SC ranking band", "No arcs found.")

    row_h = 38
    margin_top = 130
    margin_left = 320
    chart_w = 720
    margin_right = 60
    width = margin_left + chart_w + margin_right
    bottom_pad = 60
    height = margin_top + row_h * len(arcs) + bottom_pad

    axis = build_active_scale(timeline, chart_w)
    file_paths = {arc["file_path"] for arc in arcs}
    multi_file = len(file_paths) > 1

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block; max-width: 100%; background: {PALETTE["paper"]};">',
        _defs(),
        _atom_timeline_strip(timeline, width, 30, width - 60),
        f'<text x="30" y="64" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" '
        f'font-size="22" font-weight="600" fill="{PALETTE["ink"]}">The named arcs of the work</text>',
        f'<text x="30" y="86" font-family="EB Garamond, Iowan Old Style, serif" font-style="italic" '
        f'font-size="12" fill="{PALETTE["ink_dim"]}">'
        f"{len(arcs)} arc(s) across {len(file_paths)} file(s), as the historian recorded them. "
        "Bands span first to last decisive commit; the inset ticks are the commits the story explicitly named."
        "</text>",
        f'<line x1="30" y1="90" x2="{width - 30}" y2="90" stroke="{PALETTE["ink"]}" stroke-width="0.6"/>',
        f'<line x1="30" y1="93" x2="{width - 30}" y2="93" stroke="{PALETTE["ink"]}" stroke-width="0.3"/>',
    ]

    chart_top = margin_top - 6
    chart_bottom = margin_top + row_h * len(arcs)
    for g in axis["gap_blocks"]:
        x0 = margin_left + g["x_start"]
        parts.append(
            f'<rect x="{x0}" y="{chart_top}" width="{g["x_end"] - g["x_start"]}" '
            f'height="{chart_bottom - chart_top}" fill="url(#lossy-hatch)"/>'
        )
    for i, w in enumerate(axis["windows"]):
        x0 = margin_left + axis["window_starts"][i]
        wpx = axis["window_pixels"][i]
        parts.append(
            f'<rect x="{x0}" y="{chart_top}" width="{wpx}" height="{chart_bottom - chart_top}" '
            f'fill="none" stroke="{PALETTE["rule"]}" stroke-width="0.4"/>'
        )

    for i, arc in enumerate(arcs):
        color = ARC_COLORS[i % len(ARC_COLORS)]
        y = margin_top + i * row_h
        basename = arc["file_path"].rsplit("/", 1)[-1]
        if multi_file:
            parts.append(
                f'<text x="{margin_left - 14}" y="{y + 12}" text-anchor="end" '
                f'font-family="ui-monospace, SF Mono, Monaco, monospace" font-size="9" '
                f'fill="{PALETTE["accent"]}">{_xml_escape(basename)}</text>'
            )
        name = arc["name"]
        if len(name) > 38:
            name = name[:36] + "…"
        parts.append(
            f'<text x="{margin_left - 14}" y="{y + 26}" text-anchor="end" '
            f'font-family="EB Garamond, Iowan Old Style, Palatino, serif" font-size="11.5" font-weight="600" '
            f'fill="{PALETTE["ink"]}">Arc {arc["arc_number"]}: {_xml_escape(name)}</text>'
        )

        datable = [c for c in arc["commits"] if c["timestamp"]]
        if datable:
            t0 = _iso_to_dt(datable[0]["timestamp"])
            t1 = _iso_to_dt(datable[-1]["timestamp"])
            band_x1 = margin_left + axis["scale"](t0)
            band_x2 = margin_left + axis["scale"](t1)
            band_y = y + 14
            band_h = 12
            parts.append(
                f'<rect x="{band_x1}" y="{band_y}" width="{max(band_x2 - band_x1, 3)}" '
                f'height="{band_h}" fill="{color}" opacity="0.28" '
                f'stroke="{color}" stroke-width="0.6"/>'
            )
            for c in arc["commits"]:
                if not c["timestamp"]:
                    continue
                cx = margin_left + axis["scale"](_iso_to_dt(c["timestamp"]))
                parts.append(
                    f'<line x1="{cx}" y1="{band_y - 2}" x2="{cx}" y2="{band_y + band_h + 2}" '
                    f'stroke="{color}" stroke-width="2.5">'
                    f"<title>{_xml_escape(c['short_sha'] + ' — ' + c['subject'])}</title>"
                    "</line>"
                )

    axis_y = chart_bottom + 8
    parts.append(_window_axis_labels(axis, margin_left, axis_y))

    parts.append("</svg>")
    return "\n".join(parts)


def _empty_atom(title: str, message: str) -> str:
    return f"""<svg viewBox="0 0 900 160" xmlns="http://www.w3.org/2000/svg" width="100%" style="display:block; max-width:100%; background: {PALETTE["paper"]};">
{_defs()}
<rect x="0" y="0" width="900" height="160" fill="url(#lossy-hatch)" opacity="0.4"/>
<rect x="0" y="0" width="900" height="160" fill="{PALETTE["paper"]}" opacity="0.5"/>
<text x="40" y="46" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" font-size="22" font-weight="600" fill="{PALETTE["ink"]}">{_xml_escape(title)}</text>
<text x="40" y="78" font-family="EB Garamond, serif" font-size="13" fill="{PALETTE["ink_dim"]}" font-style="italic">{_xml_escape(message)}</text>
</svg>"""


def story_filename_for_file(file_path: str) -> str:
    """Mirror of pipeline.py's safe_name convention, with .html extension.

    Stories on disk live at ``.antiquarian/stories/<file_path with / → __>.md``;
    the rendered HTML pages alongside them use the same stem with .html.
    Exposed so the CLI and tests can share the mapping.
    """
    return file_path.replace("/", "__") + ".html"


def _story_md_to_html_name(story_md_filename: str) -> str:
    """Map a stories/*.md filename to its rendered HTML sibling."""
    if story_md_filename.endswith(".md"):
        return story_md_filename[:-3] + ".html"
    return story_md_filename + ".html"


_ROMAN_NUMERALS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
# The order matters — atoms appear top-to-bottom in this sequence on the
# page. Empty atoms (e.g. todo_strip when the codebase has zero TODOs) are
# dropped from the layout and the chapter-mark numbering shifts down so
# there are no "i" / [missing] / "iii" gaps.
_ATOM_ORDER = ("todo_strip", "swimlane", "arc_band")


def _render_atom_sequence(atoms: dict[str, str]) -> str:
    """Render the atoms list in order, skipping any that are empty.

    Chapter marks (i, ii, iii…) are assigned to surviving atoms only.
    """
    parts: list[str] = []
    n = 0
    for key in _ATOM_ORDER:
        body = atoms.get(key, "")
        if not body:
            continue
        numeral = _ROMAN_NUMERALS[n] if n < len(_ROMAN_NUMERALS) else str(n + 1)
        parts.append(f'<div class="chapter-mark">{numeral}</div>')
        parts.append(f'<div class="atom">{body}</div>')
        n += 1
    return "\n    ".join(parts)


def render_page(
    project: str,
    manifest: dict,
    atoms: dict[str, str],
    timeline: dict,
    masthead: str,
    survey_excerpt: str | None,
    stories_with_pages: set[str] | None = None,
    has_survey: bool = False,
    story_descriptions: dict[str, str] | None = None,
) -> str:
    """Render the main broadsheet HTML.

    ``stories_with_pages`` is the set of story markdown filenames (e.g.
    ``src__a.py.md``) that have rendered HTML pages alongside them. Filenames
    in this set get a clickable link in the meta-table; the rest stay as plain
    ``<code>``. None = treat as empty (no links).

    ``story_descriptions`` maps file paths to one-sentence Origin excerpts,
    shown alongside each file in the meta-table.
    """
    generated = manifest.get("generated_at", "")
    files = manifest.get("files", [])
    linked = stories_with_pages or set()
    descs = story_descriptions or {}

    def _file_li(f: str) -> str:
        """A file_path that has a story gets linked to its HTML page."""
        safe = _story_md_to_html_name(f.replace("/", "__") + ".md")
        desc = descs.get(f, "")
        desc_span = (
            f' <span class="file-desc">— {_xml_escape(desc)}</span>' if desc else ""
        )
        if (f.replace("/", "__") + ".md") in linked:
            return f'<li><a href="stories/{safe}"><code>{_xml_escape(f)}</code></a>{desc_span}</li>'
        return f"<li><code>{_xml_escape(f)}</code>{desc_span}</li>"

    file_lines = "".join(_file_li(f) for f in files)

    full_start = full_end = ""
    if timeline.get("full_span"):
        full_start = _iso_to_dt(timeline["full_span"]["start"]).strftime("%B %Y")
        full_end = _iso_to_dt(timeline["full_span"]["end"]).strftime("%B %Y")

    survey_html = ""
    if survey_excerpt:
        survey_link = (
            '\n    <div class="aside-link"><a href="survey.html">read the full survey &rarr;</a></div>'
            if has_survey
            else ""
        )
        survey_html = f"""
  <aside class="survey-excerpt">
    <div class="aside-label">from the surveyor's field notes</div>
    <div class="aside-body">{survey_excerpt}</div>{survey_link}
  </aside>"""
    elif has_survey:
        survey_html = """
  <aside class="survey-excerpt">
    <div class="aside-label">codebase survey</div>
    <div class="aside-link"><a href="survey.html">read the full codebase survey &rarr;</a></div>
  </aside>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antiquarian — {_xml_escape(project)} broadsheet</title>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --ink: {PALETTE["ink"]};
      --ink-dim: {PALETTE["ink_dim"]};
      --rule: {PALETTE["rule"]};
      --paper: {PALETTE["paper"]};
      --paper-alt: {PALETTE["paper_alt"]};
      --accent: {PALETTE["accent"]};
      --serif: "EB Garamond", "Iowan Old Style", Palatino, Georgia, serif;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      background: var(--paper);
      color: var(--ink);
      margin: 0;
      padding: 0;
      font-family: var(--serif);
      line-height: 1.55;
    }}
    .broadsheet {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 2rem 2.5rem 4rem;
      background: var(--paper);
      position: relative;
    }}
    .dateline {{
      font-family: var(--serif);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.4em;
      font-weight: 500;
      color: var(--ink-dim);
      border-bottom: 1px solid var(--ink);
      padding-bottom: 0.5rem;
      margin-bottom: 0.5rem;
    }}
    .masthead-title {{
      font-family: var(--serif);
      font-size: 3rem;
      font-weight: 700;
      letter-spacing: -0.005em;
      line-height: 1.05;
      margin: 0.25rem 0 0.5rem;
      color: var(--ink);
    }}
    .masthead-sub {{
      font-family: var(--serif);
      font-style: italic;
      font-size: 1rem;
      color: var(--ink-dim);
      max-width: 64ch;
      margin: 0 0 1.5rem;
    }}
    .double-rule {{
      border-top: 2px solid var(--ink);
      border-bottom: 0.5px solid var(--ink);
      margin: 1rem 0 1.5rem;
      padding-bottom: 2px;
    }}
    p.lede {{
      font-family: var(--serif);
      font-size: 1.05rem;
      line-height: 1.6;
      max-width: 60ch;
      margin: 0 0 1.5rem;
    }}
    p.lede::first-letter {{
      font-family: var(--serif);
      font-size: 4.5rem;
      font-weight: 700;
      float: left;
      line-height: 0.85;
      padding: 0.4rem 0.5rem 0 0;
      color: var(--accent);
    }}
    aside.survey-excerpt {{
      background: var(--paper-alt);
      border-left: 4px solid var(--accent);
      padding: 1rem 1.25rem;
      margin: 1.5rem 0;
      max-width: 56ch;
    }}
    aside.survey-excerpt .aside-label {{
      font-family: var(--serif);
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 0.65rem;
      color: var(--accent);
      font-weight: 600;
      margin-bottom: 0.4rem;
    }}
    aside.survey-excerpt .aside-body {{
      font-family: var(--serif);
      font-style: italic;
      font-size: 0.95rem;
      line-height: 1.55;
      color: var(--ink);
    }}
    aside.survey-excerpt .aside-link {{
      margin-top: 0.6rem;
      font-size: 0.85rem;
    }}
    aside.survey-excerpt .aside-link a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px dotted var(--accent);
    }}
    aside.survey-excerpt .aside-link a:hover {{
      border-bottom-style: solid;
    }}
    .chapter-mark {{
      font-family: var(--serif);
      font-size: 0.95rem;
      font-variant: small-caps;
      letter-spacing: 0.2em;
      color: var(--ink-dim);
      text-align: center;
      margin: 2.5rem 0 1rem;
    }}
    .chapter-mark::before, .chapter-mark::after {{
      content: " · "; color: var(--accent);
    }}
    .meta-table {{
      font-family: var(--serif);
      font-size: 0.85rem;
      color: var(--ink-dim);
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 4px 1.5rem;
      margin: 1rem 0 2rem;
      padding: 0.75rem 1rem;
      background: var(--paper-alt);
      border-top: 1px solid var(--ink);
      border-bottom: 1px solid var(--ink);
    }}
    .meta-table .k {{
      font-variant: small-caps;
      letter-spacing: 0.1em;
      font-weight: 600;
      color: var(--ink);
    }}
    .meta-table ul {{ margin: 0; padding-left: 1rem; }}
    .meta-table .file-desc {{
      font-style: italic;
      font-size: 0.78rem;
      color: var(--ink-dim);
    }}
    .meta-table code {{
      font-family: ui-monospace, "SF Mono", Monaco, monospace;
      font-size: 0.8rem;
      color: var(--accent);
    }}
    .atom {{
      margin: 0.5rem -1rem 2rem;
      padding: 0.5rem 1rem;
      background: var(--paper);
    }}
    .colophon {{
      margin-top: 3rem;
      padding-top: 1rem;
      border-top: 1px solid var(--ink);
      font-family: var(--serif);
      font-style: italic;
      font-size: 0.85rem;
      color: var(--ink-dim);
      max-width: 56ch;
    }}
  </style>
</head>
<body>
  <div class="broadsheet">
    <div class="dateline">Antiquarian · field notes · vol. i</div>
    <h1 class="masthead-title">{_xml_escape(project)}</h1>
    <p class="masthead-sub">A reconstruction of the project's surviving record, from {full_start} to {full_end}. Three atoms, hand-set in pure SVG, with the historian's lossy regions and named arcs preserved as marginalia.</p>
    <div class="double-rule"></div>

    <div class="atom">{masthead}</div>

    <div class="meta-table">
      <span class="k">files surveyed</span><div><ul>{file_lines}</ul></div>
      <span class="k">stories on file</span><div><ul>{stories_lines}</ul></div>
      <span class="k">codebase survey</span><div>{'<a href="survey.html">full narrative synthesis</a>' if has_survey else "<em>none — run <code>antiquarian survey</code> then <code>render</code></em>"}</div>
      <span class="k">generated</span><code>{_xml_escape(generated)}</code>
    </div>

    <p class="lede">
      The following pages are a hand-set printing of what survived. Dormancies
      in the record appear as hatched intervals; commits the historian named
      appear larger and outlined; arcs are bracketed bands, each set in its
      own pigment from the printer's chase. Where the channel went dark, the
      page says so in marks rather than blank space — the absence is set as
      carefully as the presence.
    </p>{survey_html}

    {_render_atom_sequence(atoms)}

    <div class="colophon">
      Set in the antiquarian broadsheet idiom — data-ink discipline laid out
      in 19th-century print furniture, with woodblock-style hatching for the
      moments when the record went dark. The bracketed window frames, the
      arc bands in their own pigments, the small-caps chapter marks, the
      diagonal hatch of an absent year — every mark accounts for either
      what survived or what didn't.
    </div>
  </div>
</body>
</html>
"""


def render_broadsheet(
    data: dict, *, stories_with_pages: set[str] | None = None, has_survey: bool = False
) -> str:
    """Render the broadsheet HTML page from extracted render data.

    ``data`` is the dict returned by
    ``antiquarian.render_data.extract_render_data`` — a JSON-shaped bundle
    of commits, todos, arcs, swimlane lanes, arc-band rankings, timeline
    metadata, file lifespans, and an optional survey excerpt.

    ``stories_with_pages`` is the set of ``.md`` story filenames that have
    rendered HTML siblings; filenames in this set become clickable links in
    the meta-table (#46). The CLI populates this after writing the per-story
    pages; callers that only want the index can omit it.

    Returns a self-contained HTML string with inline SVG. The page degrades
    gracefully when EB Garamond fails to load (the only external resource).
    """
    timeline = data["timeline"]
    masthead_svg = render_timeline_masthead(timeline)
    atoms = {
        "todo_strip": render_todo_strip(data["todos"], timeline),
        "swimlane": render_swimlane(data["swimlane"], timeline, data["file_lifespans"]),
        "arc_band": render_arc_band(data["arc_band"], timeline),
    }
    raw_excerpt = data.get("survey_excerpt")
    survey_excerpt = _xml_escape(raw_excerpt) if raw_excerpt else None

    manifest = {
        "files": data.get("files", []),
        "generated_at": data.get("generated_at", ""),
    }
    return render_page(
        data["project"],
        manifest,
        atoms,
        timeline,
        masthead_svg,
        survey_excerpt,
        stories_with_pages=stories_with_pages,
        has_survey=has_survey,
        story_descriptions=data.get("story_descriptions"),
    )


# Story-page templates — kept as real .css/.html files under templates/ so
# IDEs give them syntax highlighting and diffs are scoped to the template
# rather than buried inside a Python string literal. Substitution uses
# string.Template ($name) rather than .format() so CSS and HTML braces stay
# literal.
#
# Both are read and prepared **once at module import time** rather than per
# render call: _STORY_PAGE_CSS is the fully-palette-substituted string, and
# _STORY_PAGE_HTML is a compiled Template object. Rendering 100 story pages
# in a single survey reads the disk twice total, not 200 times.
_TEMPLATES_DIR = Path(__file__).parent / "templates"

_STORY_PAGE_CSS = Template(
    (_TEMPLATES_DIR / "story_page.css").read_text(encoding="utf-8")
).substitute(
    ink=PALETTE["ink"],
    ink_dim=PALETTE["ink_dim"],
    rule=PALETTE["rule"],
    paper=PALETTE["paper"],
    paper_alt=PALETTE["paper_alt"],
    accent=PALETTE["accent"],
)

_STORY_PAGE_HTML = Template(
    (_TEMPLATES_DIR / "story_page.html").read_text(encoding="utf-8")
)

_SURVEY_PAGE_HTML = Template(
    (_TEMPLATES_DIR / "survey_page.html").read_text(encoding="utf-8")
)


# Pattern: a `## TODO/FIXME aging` section whose body matches the old
# "no TODO/FIXME admissions" placeholder. Used to strip the section from
# stories cached before the system-prompt change that stopped emitting it.
# Conservative match — only strips if the placeholder phrase is present, so
# real TODO/FIXME content survives and the skip-and-stub `Unrecoverable in
# this session.` text (which is also a valid no-data state) survives too.
_EMPTY_TODO_SECTION_RE = re.compile(
    r"^##\s+TODO/FIXME aging\s*\n+[^\n]*"
    r"currently carries no TODO/FIXME admissions[^\n]*\n*",
    flags=re.MULTILINE,
)


def _strip_empty_todo_section(story_md: str) -> str:
    """Drop the canonical 'no admissions' TODO section from a cached story.

    The current system prompt omits the section when no annotations exist,
    but stories synthesized before that change still carry the placeholder.
    Strip it at render time so existing renders look right without a
    re-run of ``claude -p`` against every file.
    """
    return _EMPTY_TODO_SECTION_RE.sub("", story_md)


def render_story_page(
    file_path: str,
    story_md: str,
    project: str,
) -> str:
    """Render a single per-file story.md as a styled HTML page (#46).

    The page shares palette and typography with the broadsheet but uses a
    narrower text column and no atoms — this is the long-form prose surface,
    the broadsheet is the figure-led front page. A "← back to broadsheet"
    link in the dateline navigates back to ``index.html``.

    Markdown conversion uses Python-Markdown's safe defaults; the story
    content comes from our own synthesizer so no untrusted HTML to worry
    about, but the conversion still escapes special characters in plain
    text. Removes the antiquarian cache-digest comment that ``pipeline.py``
    prepends to persisted stories before rendering.

    The CSS and HTML scaffolding live as separate files under
    ``antiquarian/templates/`` so editing them gets IDE syntax highlighting
    and produces clean diffs.
    """
    # Strip the digest marker line if present — it's an HTML comment used
    # internally by the cache, not narrative content.
    if story_md.startswith("<!-- antiquarian-cache-digest:"):
        _, _, story_md = story_md.partition("\n")

    # Strip the canonical "no TODO/FIXME admissions" placeholder section
    # from stories cached before the system-prompt change that stopped
    # emitting it.
    story_md = _strip_empty_todo_section(story_md)

    import markdown as _markdown

    body_html = _markdown.markdown(
        story_md.strip(),
        extensions=["fenced_code", "tables"],
        output_format="html",
    )
    project_escaped = _xml_escape(project)
    file_path_escaped = _xml_escape(file_path)
    return _STORY_PAGE_HTML.substitute(
        title=f"{project_escaped} — {file_path_escaped}",
        css=_STORY_PAGE_CSS,
        project=project_escaped,
        file_path=file_path_escaped,
        body_html=body_html,
    )


def render_survey_page(
    survey_md: str,
    project: str,
    file_count: int,
) -> str:
    """Render the codebase survey as a styled HTML page (#81).

    Uses the same palette and typography as story pages so the broadsheet,
    stories, and survey feel like one publication.
    """
    import markdown as _markdown

    body_html = _markdown.markdown(
        survey_md.strip(),
        extensions=["fenced_code", "tables"],
        output_format="html",
    )
    project_escaped = _xml_escape(project)
    return _SURVEY_PAGE_HTML.substitute(
        title=f"{project_escaped} — Codebase Survey",
        css=_STORY_PAGE_CSS,
        project=project_escaped,
        file_count=str(file_count),
        body_html=body_html,
    )
