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
  * One absolute time spine: chart marks register to their true position
    across the full lifespan (``build_absolute_scale``); dormancy keeps its
    true width as a lossy region. The dual-axis reference strip (full span +
    active-window markers) stays in the masthead AND atop each atom as the
    orientation map.
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

from antiquarian.file_tree import (
    FileNode,
    FolderNode,
    build_file_tree,
    choose_open_depth,
)
from antiquarian.arc_roster import datable_count, group_arcs_by_file

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

# Above this many contributor lanes, the swimlane folds the ranked tail into a
# searchable HTML list instead of an ever-taller SVG (#118; the "information
# budget" of visualizing-at-scale.md).
SWIMLANE_LANE_BUDGET = 30

# Below this many TODO/FIXME notes, the marginalia atom degrades to a single
# sentence rather than a bar chart — the frame shouldn't dwarf the data (#122).
TODO_DENSITY_FLOOR = 3


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def build_absolute_scale(timeline: dict, pixel_width: int):
    """Linear pixel scale across the full project lifespan — the shared spine (#117).

    Maps a datetime onto an x-coordinate by its true position between
    ``full_span.start`` and ``full_span.end``, so the same date lands at the
    same x in every atom that registers to it. Dormant stretches are *not*
    collapsed — they occupy their true width, drawn as lossy regions. Dates
    outside the span clamp to the bounds.
    """
    span = timeline.get("full_span") if timeline else None
    if not span:

        def empty_scale(_):
            return 0

        return {"scale": empty_scale, "total_pixels": pixel_width}

    start = _iso_to_dt(span["start"])
    end = _iso_to_dt(span["end"])
    total = max(1.0, (end - start).total_seconds())

    def scale(dt: datetime) -> float:
        frac = (dt - start).total_seconds() / total
        frac = max(0.0, min(1.0, frac))
        return frac * pixel_width

    return {"scale": scale, "total_pixels": pixel_width}


def _axis_ticks(full_start: datetime, full_end: datetime) -> list[tuple[datetime, str]]:
    """``(datetime, label)`` ticks for the absolute axis, granularity by span (#117).

    A project spanning ≥ ~2 years gets **year** ticks (Jan 1 of each in-range
    year, thinned to every other year past eight so labels don't crowd). A
    younger project gets **month** ticks — year boundaries are too coarse for
    it, and a sub-year repo would get none — stepped to keep the count readable
    and suffixed with the year only when the span crosses a year boundary.
    """
    if (full_end - full_start).days >= 730:
        span_yrs = full_end.year - full_start.year + 1
        step = 2 if span_yrs > 8 else 1
        ticks: list[tuple[datetime, str]] = []
        for y in range(full_start.year, full_end.year + 1, step):
            d = datetime(y, 1, 1, tzinfo=full_start.tzinfo)
            if full_start <= d <= full_end:
                ticks.append((d, str(y)))
        return ticks

    months = max(1, (full_end - full_start).days) / 30.4
    step = 1 if months <= 12 else 2
    fmt = "%b" if full_start.year == full_end.year else "%b '%y"
    ticks = []
    cur = full_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= full_end:
        if cur >= full_start:
            ticks.append((cur, cur.strftime(fmt)))
        m = cur.month - 1 + step
        cur = cur.replace(year=cur.year + m // 12, month=m % 12 + 1)
    return ticks


def _render_dormancy_hatch(
    timeline: dict,
    scale,
    margin_left: float,
    chart_top: float,
    chart_bottom: float,
    *,
    labels: bool = False,
) -> list[str]:
    """Lossy-hatch the dormant stretches at their *true* width on the absolute spine.

    Each timeline gap (≥1y by construction) is drawn from its real start to its
    real end under the absolute scale, honouring the lossy-region commitment —
    absence occupies the space it actually spanned, rather than collapsing to a
    fixed-width block.
    """
    parts: list[str] = []
    for g in timeline.get("gaps", []):
        x0 = margin_left + scale(_iso_to_dt(g["start"]))
        x1 = margin_left + scale(_iso_to_dt(g["end"]))
        parts.append(
            f'<rect x="{x0}" y="{chart_top}" width="{max(x1 - x0, 0)}" '
            f'height="{chart_bottom - chart_top}" fill="url(#lossy-hatch)"/>'
        )
        if labels:
            cy = (chart_top + chart_bottom) / 2
            parts.append(
                f'<text x="{(x0 + x1) / 2}" y="{cy}" text-anchor="middle" '
                f'font-family="EB Garamond, serif" font-style="italic" font-size="13" '
                f'fill="{PALETTE["lossy"]}">the silence — {g["days"]} days</text>'
            )
    return parts


def _render_absolute_axis(
    timeline: dict, margin_left: float, chart_w: float, axis_y: float
) -> str:
    """Year-tick axis on the shared absolute spine (#117)."""
    if not timeline or not timeline.get("full_span"):
        return ""
    scale = build_absolute_scale(timeline, chart_w)["scale"]
    full_start = _iso_to_dt(timeline["full_span"]["start"])
    full_end = _iso_to_dt(timeline["full_span"]["end"])
    label_font = "EB Garamond, Iowan Old Style, Palatino, Georgia, serif"
    parts = [
        f'<line x1="{margin_left}" y1="{axis_y}" x2="{margin_left + chart_w}" y2="{axis_y}" '
        f'stroke="{PALETTE["rule"]}" stroke-width="0.6"/>'
    ]
    # The span endpoints are always labelled, so the axis is never blank even
    # when the project lives inside a single calendar year (no year tick lands).
    edge = 0.06 * chart_w
    parts.append(
        f'<text x="{margin_left}" y="{axis_y + 16}" text-anchor="start" font-size="10" '
        f'font-family="{label_font}" fill="{PALETTE["ink_dim"]}">{full_start.strftime("%b %Y")}</text>'
    )
    parts.append(
        f'<text x="{margin_left + chart_w}" y="{axis_y + 16}" text-anchor="end" font-size="10" '
        f'font-family="{label_font}" fill="{PALETTE["ink_dim"]}">{full_end.strftime("%b %Y")}</text>'
    )
    for d, label in _axis_ticks(full_start, full_end):
        x = margin_left + scale(d)
        # Skip ticks that would collide with an endpoint label.
        if x - margin_left < edge or (margin_left + chart_w) - x < edge:
            continue
        parts.append(
            f'<line x1="{x}" y1="{axis_y}" x2="{x}" y2="{axis_y + 4}" stroke="{PALETTE["rule"]}"/>'
        )
        parts.append(
            f'<text x="{x}" y="{axis_y + 16}" text-anchor="middle" font-size="10" '
            f'font-family="{label_font}" fill="{PALETTE["ink_dim"]}">{label}</text>'
        )
    return "\n".join(parts)


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


def _knotwork_ribbon_svg(width: int = 480) -> str:
    """A Celtic interlace ribbon rendered as inline SVG.

    Two strands weave over/under each other in a repeating pattern inspired by
    the Book of Kells border illuminations. Uses the broadsheet accent (oxide
    red) and ink palette.
    """
    accent = PALETTE["accent"]
    ink_dim = PALETTE["ink_dim"]
    h = 18
    cell = 24
    r = 5
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="{h}" viewBox="0 0 {width} {h}" preserveAspectRatio="none">'
    ]
    mid = h // 2
    top = 3
    bot = h - 3
    for x in range(0, width, cell):
        cx = x + cell // 2
        parts.append(
            f'<path d="M{x},{mid} Q{cx},{top} {x + cell},{mid}" '
            f'fill="none" stroke="{accent}" stroke-width="2.5" opacity="0.8"/>'
        )
        parts.append(
            f'<path d="M{x},{mid} Q{cx},{bot} {x + cell},{mid}" '
            f'fill="none" stroke="{ink_dim}" stroke-width="2" opacity="0.5"/>'
        )
        parts.append(
            f'<circle cx="{cx}" cy="{mid}" r="{r}" fill="none" stroke="{accent}" stroke-width="1" opacity="0.4"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _render_dramatis_personae(entries: list[dict[str, str]]) -> str:
    """Build the Dramatis Personae HTML section for the broadsheet."""
    if not entries:
        return ""
    ribbon = _knotwork_ribbon_svg()
    items = []
    for e in entries:
        name = _xml_escape(e["name"])
        desc = _xml_escape(e["description"])
        items.append(
            f'    <div class="dramatis-entry">'
            f'<span class="dramatis-name">{name}</span> — '
            f'<span class="dramatis-desc">{desc}</span></div>'
        )
    entries_html = "\n".join(items)
    return f"""
  <section class="dramatis">
    <div class="dramatis-heading">Dramatis Personæ</div>
    <div class="dramatis-ribbon">{ribbon}</div>
{entries_html}
  </section>"""


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

    for d, label in _axis_ticks(full_start, full_end):
        x = sx(d)
        parts.append(
            f'<line x1="{x}" y1="{bar_y + bar_h}" x2="{x}" y2="{bar_y + bar_h + 4}" stroke="{PALETTE["rule"]}"/>'
        )
        parts.append(
            f'<text x="{x}" y="{bar_y + bar_h + 16}" text-anchor="middle" font-size="10" '
            f'font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" fill="{PALETTE["ink_dim"]}">{label}</text>'
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


def _render_marginalia_note(todos: list[dict]) -> str:
    """Below the density floor: a single in-voice line, not a whole chart (#122).

    A codebase with one or two marginal notes doesn't warrant chart furniture —
    that made the frame dwarf the data. Render them as a sentence instead.
    """
    fragments = []
    for t in sorted(todos, key=lambda t: t["age_days"], reverse=True):
        basename = t["file_path"].rsplit("/", 1)[-1]
        fragments.append(
            f"<code>{_xml_escape(basename)}:{t['line_number']}</code> — "
            f'"{_xml_escape(t["text"])}", standing {t["age_days"]} days'
        )
    lead = (
        "One note still stands in the margins"
        if len(todos) == 1
        else f"{len(todos)} notes still stand in the margins"
    )
    return (
        '<p class="marginalia-note">'
        '<span class="marginalia-label">Notes left in the margins</span> '
        f"{lead}: {'; '.join(fragments)}."
        "</p>"
    )


def render_todo_strip(todos: list[dict], timeline: dict) -> str:
    """Marginalia — TODO/FIXME notes the authors left, bars sized by age (#122).

    Three regimes by density:

    - **zero** → empty string; the layout skips the atom entirely. Absence is
      information, but it doesn't need a whole section to say so.
    - **below the floor** (1–2) → a single sentence (``_render_marginalia_note``)
      rather than chart furniture that would dwarf the data.
    - **at/above the floor** → the age-ranked bar chart.

    Presented as points of interest, not a ledger of admissions — these marks
    are honest notes-to-self, per the ethos (assume good intentions).
    """
    if not todos:
        return ""

    if len(todos) < TODO_DENSITY_FLOOR:
        return _render_marginalia_note(todos)

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
        "Notes left in the margins"
        "</text>",
        f'<text x="20" y="76" font-family="EB Garamond, Iowan Old Style, serif" font-size="12" font-style="italic" fill="{PALETTE["ink_dim"]}">'
        f"{len(todos)} notes the authors left in the code — TODO and FIXME marks still standing in the surveyed files; the bar measures how long each has stood."
        "</text>",
        f'<line x1="20" y1="80" x2="{width - 20}" y2="80" stroke="{PALETTE["ink"]}" stroke-width="0.6"/>',
        f'<text x="{margin_left + bar_max / 2}" y="{margin_top - 10}" text-anchor="middle" font-size="10" '
        f'font-family="EB Garamond, serif" font-style="italic" fill="{PALETTE["ink_dim"]}">days standing</text>',
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


def render_swimlane(
    swimlane: dict,
    timeline: dict,
    file_lifespans: list[dict],
    lane_budget: int = SWIMLANE_LANE_BUDGET,
) -> str:
    """Author swimlane — absolute spine, lossy hatching, Diff size (LoC) legend.

    Lanes arrive ranked by contribution (#118). The top ``lane_budget`` render
    as SVG; the rest fold into a searchable HTML tail below the chart, so the
    SVG stays bounded while every name remains in the DOM.
    """
    lanes = swimlane["lanes"]
    if not lanes:
        return _empty_atom("Author swimlane", "No commits in cache.")

    visible_lanes = lanes[:lane_budget]
    tail_lanes = lanes[lane_budget:]

    row_h = 60
    margin_top = 130
    margin_left = 220
    chart_w = 760
    margin_right = 60
    width = margin_left + chart_w + margin_right
    bottom_pad = 80
    height = margin_top + row_h * len(visible_lanes) + bottom_pad

    axis = build_absolute_scale(timeline, chart_w)
    max_diff = (
        max(
            (c["additions"] + c["deletions"])
            for lane in visible_lanes
            for c in lane["commits"]
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
    parts.extend(
        _render_dormancy_hatch(
            timeline, axis["scale"], margin_left, chart_top, chart_bottom, labels=True
        )
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

    for i, lane in enumerate(visible_lanes):
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
    parts.append(_render_absolute_axis(timeline, margin_left, chart_w, axis_y))

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

    if tail_lanes:
        parts.append(_render_swimlane_tail(tail_lanes))

    return "\n".join(parts)


def _render_swimlane_tail(tail_lanes: list[dict]) -> str:
    """The folded long tail of contributors as a searchable HTML disclosure (#118).

    Stays in the DOM (Ctrl-F-able) and is forced open for print via the
    stylesheet, so no hand is silently dropped — only visually deferred.
    """
    hidden_commits = sum(lane["commit_count"] for lane in tail_lanes)
    items = "\n".join(
        f'<li><span class="name">{_xml_escape(lane["author"])}</span>'
        f'<span class="count">{lane["commit_count"]}</span></li>'
        for lane in tail_lanes
    )
    return (
        '<details class="swimlane-tail">'
        f"<summary>and {len(tail_lanes)} more hands "
        f"({hidden_commits} commits) — fewer than the most active</summary>"
        f"<ul>{items}</ul>"
        "</details>"
    )


def render_arc_roster(arc_band: dict, timeline: dict) -> str:
    """Honest file-grouped roster of named arcs (#112 rethink; fixes #133).

    An arc is a named set of commits, not a span — so there is no band. Every
    arc is listed, grouped by file in a collapsible ``<details>``; arcs with no
    datable commit are badged rather than dropped. (The per-arc dot-sparkline
    is added in the next task.)
    """
    arcs = arc_band["arcs"]
    if not arcs:
        return _empty_atom("The named arcs of the work", "No arcs found.")

    groups = group_arcs_by_file(arcs)
    total = len(arcs)
    undatable = sum(1 for a in arcs if datable_count(a) == 0)

    parts = [
        '<div class="arc-roster">',
        '<div class="arc-roster-head">'
        f'<span class="arc-roster-title">The named arcs of the work</span> '
        f'<span class="arc-roster-sub">{total} arc(s) across {len(groups)} file(s)'
        f"{f' — {undatable} undatable, kept as lossy marks' if undatable else ''}.</span>"
        "</div>",
    ]
    for g in groups:
        parts.append(
            f'<details class="arc-file"><summary>'
            f"<code>{_xml_escape(g.file_path)}</code> "
            f'<span class="count">{g.arc_count} arc(s)</span></summary><ul>'
        )
        for arc in g.arcs:
            parts.append(_render_arc_row(arc, timeline))
        parts.append("</ul></details>")
    parts.append("</div>")
    return "".join(parts)


def _render_arc_row(arc: dict, timeline: dict) -> str:
    """One arc: number, name, commit count, and a datable/undatable marker.

    The sparkline marker is filled in by the next task; for now datable arcs
    show their commit count and undatable arcs show the badge.
    """
    n_datable = datable_count(arc)
    name = _xml_escape(arc["name"])
    label = (
        f'<span class="arc-num">Arc {arc["arc_number"]}</span> '
        f'<span class="arc-name">{name}</span> '
        f'<span class="count">{arc["commit_count"]} commit(s)</span>'
    )
    if n_datable == 0:
        marker = (
            '<span class="undatable-badge" '
            'title="No referenced commit resolves to a dated commit in cache — '
            'a lossy region, kept rather than dropped">undatable</span>'
        )
    else:
        marker = ""
    return f'<li class="arc-row">{label} {marker}</li>'


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
# The marginalia (TODO/FIXME) atom is demoted to the end — a small section of
# notes-of-interest, not a leading ledger of "admissions" (#122).
_ATOM_ORDER = ("swimlane", "arc_roster", "todo_strip")


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


def _render_file_index(
    files: list[str], linked: set[str], descs: dict[str, str]
) -> str:
    """Render the surveyed-files list as a collapsible, searchable tree (#108/#109).

    Builds the pure tree (``file_tree``), opens it to the budget-derived depth,
    and emits ``<details>`` for folders / ``<li>`` for files. A search input sits
    above the tree; the live-search script and ``@media print`` rules (which force
    every disclosure open) live in the page template. Returns ``""`` for no files.
    """
    if not files:
        return ""
    tree = build_file_tree(files)
    open_depth = choose_open_depth(tree)
    body = _render_tree_nodes(
        tree, linked, descs, current_depth=0, open_depth=open_depth
    )
    search = (
        '<input type="search" class="file-search" '
        'placeholder="filter files…" aria-label="Filter surveyed files">'
    )
    return f'{search}<ul class="file-tree">{body}</ul>'


def _render_tree_nodes(
    nodes: list,
    linked: set[str],
    descs: dict[str, str],
    *,
    current_depth: int,
    open_depth: int,
) -> str:
    """Walk a folder/file forest, emitting ``<details>`` folders and ``<li>`` files."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, FolderNode):
            open_attr = " open" if current_depth < open_depth else ""
            children = _render_tree_nodes(
                node.children,
                linked,
                descs,
                current_depth=current_depth + 1,
                open_depth=open_depth,
            )
            summary = (
                f"<summary>{_xml_escape(node.name)} "
                f'<span class="count">{node.file_count}</span></summary>'
            )
            parts.append(
                f'<li class="folder"><details{open_attr}>{summary}'
                f"<ul>{children}</ul></details></li>"
            )
        else:
            parts.append(_render_file_leaf(node, linked, descs))
    return "".join(parts)


def _render_file_leaf(node: FileNode, linked: set[str], descs: dict[str, str]) -> str:
    """One file row: basename shown, full path on hover, linked if it has a story."""
    path = node.path
    safe = _story_md_to_html_name(path.replace("/", "__") + ".md")
    desc = descs.get(path, "")
    desc_span = f' <span class="file-desc">— {_xml_escape(desc)}</span>' if desc else ""
    label = (
        f'<span class="file-name" title="{_xml_escape(path)}">'
        f"<code>{_xml_escape(node.name)}</code></span>"
    )
    if (path.replace("/", "__") + ".md") in linked:
        label = f'<a href="stories/{safe}">{label}</a>'
    data_path = _xml_escape(path.lower())
    return f'<li class="file" data-path="{data_path}">{label}{desc_span}</li>'


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
    dramatis_personae: list[dict[str, str]] | None = None,
) -> str:
    """Render the main broadsheet HTML.

    ``stories_with_pages`` is the set of story markdown filenames (e.g.
    ``src__a.py.md``) that have rendered HTML pages alongside them. Filenames
    in this set get a clickable link in the meta-table; the rest stay as plain
    ``<code>``. None = treat as empty (no links).

    ``story_descriptions`` maps file paths to one-sentence Origin excerpts,
    shown alongside each file in the meta-table.

    ``dramatis_personae`` is a list of contributor entries extracted from the
    survey, each with ``name`` and ``description`` keys.
    """
    generated = manifest.get("generated_at", "")
    files = manifest.get("files", [])
    linked = stories_with_pages or set()
    descs = story_descriptions or {}

    file_index = _render_file_index(files, linked, descs)

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

    dramatis_html = _render_dramatis_personae(dramatis_personae or [])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Antiquarian — {_xml_escape(project)} broadsheet</title>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">
  <style>
    :root {{
      /* Global type scale (#111). All reader-facing text is rem-based, so this
         single knob bumps every element proportionally; layout reflows because
         it's HTML, not the coordinate-positioned SVG. */
      font-size: 120%;
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
    .dramatis {{
      margin: 1.5rem 0 2rem;
      padding: 1.25rem 1.5rem 1rem;
      background: var(--paper-alt);
      border: 1px solid var(--rule);
      position: relative;
    }}
    .dramatis::before, .dramatis::after {{
      content: "";
      display: block;
      height: 3px;
      background: repeating-linear-gradient(
        90deg,
        var(--accent) 0px, var(--accent) 6px,
        transparent 6px, transparent 10px,
        var(--ink-dim) 10px, var(--ink-dim) 14px,
        transparent 14px, transparent 18px
      );
    }}
    .dramatis::before {{ margin-bottom: 1rem; }}
    .dramatis::after {{ margin-top: 1rem; }}
    .dramatis-heading {{
      font-family: var(--serif);
      font-size: 1.35rem;
      font-variant: small-caps;
      letter-spacing: 0.15em;
      font-weight: 700;
      color: var(--accent);
      text-align: center;
      margin: 0 0 0.75rem;
      position: relative;
    }}
    .dramatis-heading::before {{
      content: "✦";
      margin-right: 0.6em;
      font-size: 0.7em;
      vertical-align: 0.15em;
    }}
    .dramatis-heading::after {{
      content: "✦";
      margin-left: 0.6em;
      font-size: 0.7em;
      vertical-align: 0.15em;
    }}
    .dramatis-ribbon {{
      display: block;
      width: 100%;
      height: 18px;
      margin: 0 0 0.75rem;
      overflow: hidden;
    }}
    .dramatis-entry {{
      margin: 0 0 0.6rem;
      font-size: 0.95rem;
      line-height: 1.55;
      max-width: 60ch;
    }}
    .dramatis-entry:last-child {{ margin-bottom: 0; }}
    .dramatis-name {{
      display: inline-block;
      font-family: var(--serif);
      font-weight: 700;
      color: var(--ink);
    }}
    .dramatis-name::first-letter {{
      font-size: 1.25em;
      color: var(--accent);
    }}
    .dramatis-desc {{
      font-family: var(--serif);
      font-style: italic;
      color: var(--ink);
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
    /* Marginalia note — the density-floor form of the TODO atom (#122). */
    .marginalia-note {{
      font-family: var(--serif);
      font-size: 0.95rem;
      font-style: italic;
      color: var(--ink-dim);
      max-width: 60ch;
      margin: 0.5rem 0 1rem;
    }}
    .marginalia-note .marginalia-label {{
      font-style: normal;
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 0.62rem;
      color: var(--accent);
      font-weight: 600;
      margin-right: 0.5rem;
    }}
    .marginalia-note code {{
      font-family: ui-monospace, "SF Mono", Monaco, monospace;
      font-style: normal;
      font-size: 0.82em;
    }}
    /* Honest file-grouped arc roster (#112 rethink; fixes #133). */
    .arc-roster {{ font-family: var(--serif); margin: 0.5rem 0 1rem; }}
    .arc-roster-title {{ font-size: 1.3rem; font-weight: 600; }}
    .arc-roster-sub {{ font-style: italic; font-size: 0.85rem; color: var(--ink-dim); }}
    .arc-file {{ margin: 0.2rem 0; }}
    .arc-file > summary {{ cursor: pointer; }}
    .arc-file ul {{ list-style: none; padding-left: 1.1rem; margin: 0.3rem 0; }}
    .arc-row {{ break-inside: avoid; margin-bottom: 0.15rem; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }}
    .arc-row .arc-num {{ color: var(--accent); font-variant-numeric: tabular-nums; }}
    .arc-row .count {{ color: var(--rule); font-variant-numeric: tabular-nums; font-size: 0.85em; }}
    .undatable-badge {{
      font-size: 0.7rem; font-style: italic; color: var(--accent);
      border: 1px solid var(--rule); border-radius: 2px; padding: 0 0.3rem;
    }}
    /* Folded long tail of contributors (#118) — searchable, print-expanded. */
    .swimlane-tail {{
      font-family: var(--serif);
      font-size: 0.8rem;
      color: var(--ink-dim);
      margin: 0.25rem 0 0.5rem;
    }}
    .swimlane-tail > summary {{
      cursor: pointer;
      font-style: italic;
      color: var(--accent);
    }}
    .swimlane-tail ul {{
      columns: 3;
      list-style: none;
      padding: 0;
      margin: 0.6rem 0 0;
    }}
    .swimlane-tail li {{
      display: flex;
      justify-content: space-between;
      gap: 0.5rem;
      break-inside: avoid;
    }}
    .swimlane-tail .count {{
      color: var(--rule);
      font-variant-numeric: tabular-nums;
    }}
    /* Collapsible, searchable file index (#108/#109). */
    .file-search {{
      font-family: var(--serif);
      font-size: 0.85rem;
      width: 100%;
      max-width: 22rem;
      padding: 0.2rem 0.4rem;
      margin: 0 0 0.5rem;
      border: 1px solid var(--rule);
      background: var(--paper-alt);
      color: var(--ink);
    }}
    ul.file-tree, .file-tree ul {{
      list-style: none;
      padding-left: 0;
      margin: 0;
    }}
    .file-tree ul {{ padding-left: 1.1rem; }}
    .file-tree li.file {{ break-inside: avoid; }}
    .file-tree details > summary {{
      cursor: pointer;
      font-style: italic;
      color: var(--accent);
    }}
    .file-tree .count {{
      color: var(--rule);
      font-variant-numeric: tabular-nums;
      font-style: normal;
      font-size: 0.85em;
    }}
    @media print {{
      /* Force every folded hand visible on paper; drop the toggle affordance. */
      .swimlane-tail > *:not(summary) {{ display: block !important; }}
      .swimlane-tail > summary {{ list-style: none; color: var(--ink-dim); }}
      /* The arc roster prints fully expanded (#112). */
      .arc-file > *:not(summary) {{ display: block !important; }}
      .arc-file > summary {{ list-style: none; }}
      /* The file tree prints fully expanded; the live-search box is dropped. */
      .file-tree details > *:not(summary) {{ display: block !important; }}
      .file-tree details > summary {{ list-style: none; color: var(--ink-dim); }}
      .file-search {{ display: none !important; }}
    }}
  </style>
</head>
<body>
  <div class="broadsheet">
    <div class="dateline">Antiquarian · field notes · vol. i</div>
    <h1 class="masthead-title">{_xml_escape(project)}</h1>
    <p class="masthead-sub">A reconstruction of the project's surviving record, from {full_start} to {full_end}, with the historian's lossy regions and named arcs preserved as marginalia.</p>
    <div class="double-rule"></div>

    <div class="atom">{masthead}</div>

    <div class="meta-table">
      <span class="k">files surveyed</span><div>{file_index}</div>
      <span class="k">codebase survey</span><div>{'<a href="survey.html">full narrative synthesis</a>' if has_survey else "<em>none — run <code>antiquarian survey</code> then <code>render</code></em>"}</div>
      <span class="k">generated</span><code>{_xml_escape(generated)}</code>
    </div>{dramatis_html}

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
  <script>
  /* Live file-index search (#109): a pure enhancement over the static tree.
     Narrows files in place, opens the branches that contain a match, and
     restores the server's initial open-depth when cleared. No JS → the tree
     is still fully usable; print → the box is hidden and all folders forced
     open by CSS. */
  (function () {{
    var box = document.querySelector('.file-search');
    var tree = document.querySelector('.file-tree');
    if (!box || !tree) return;
    var folders = Array.prototype.slice.call(tree.querySelectorAll('li.folder'));
    var files = Array.prototype.slice.call(tree.querySelectorAll('li.file'));
    var initialOpen = folders.map(function (li) {{
      var d = li.querySelector(':scope > details');
      return d ? d.open : false;
    }});
    function reset() {{
      files.forEach(function (li) {{ li.style.display = ''; }});
      folders.forEach(function (li, i) {{
        li.style.display = '';
        var d = li.querySelector(':scope > details');
        if (d) d.open = initialOpen[i];
      }});
    }}
    box.addEventListener('input', function () {{
      var q = box.value.trim().toLowerCase();
      if (!q) {{ reset(); return; }}
      files.forEach(function (li) {{
        var hit = (li.getAttribute('data-path') || '').indexOf(q) !== -1;
        li.style.display = hit ? '' : 'none';
      }});
      folders.forEach(function (li) {{
        var visible = false;
        var fs = li.querySelectorAll('li.file');
        for (var i = 0; i < fs.length; i++) {{
          if (fs[i].style.display !== 'none') {{ visible = true; break; }}
        }}
        var d = li.querySelector(':scope > details');
        if (d) d.open = visible;
        li.style.display = visible ? '' : 'none';
      }});
    }});
  }})();
  </script>
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
        "arc_roster": render_arc_roster(data["arc_band"], timeline),
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
        dramatis_personae=data.get("dramatis_personae"),
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
