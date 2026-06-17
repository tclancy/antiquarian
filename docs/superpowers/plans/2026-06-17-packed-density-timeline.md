# Packed Density Timeline Implementation Plan (PR1 of #112/#119/#121)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-row-per-arc stacked SVG band ("The named arcs of the work") with a packed density timeline — all arcs lane-packed onto the shared absolute spine, collapsing ~202 rows (~7,700px) to ~20 rows, with the full per-arc list kept in a folded, print-expanded `<details>` so nothing leaves the DOM.

**Architecture:** A new pure module `antiquarian/arc_layout.py` does greedy interval lane-packing (no HTML, dependency-injected scale function), mirroring `file_tree.py`'s logic/render split. `render.py`'s `render_arc_band` becomes a thin shell that walks the packed rows and draws lozenges on `build_absolute_scale`, sharing the swimlane's margins so a later PR can float the two atoms aligned.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG strings, inline CSS in the page template.

## Global Constraints

- **Python 3.13+, uv only.** Never `pip`/`poetry`. Run via `uv run`.
- **TDD iron law:** no production code without a failing test first (red → green).
- **Print-first (#40):** every screen affordance degrades to a complete static view; `@media print` forces the folded list open.
- **Keep every arc in the DOM** (the #108 rule): the folded list contains *all* arcs, including any with no datable commits.
- **Spine alignment:** the arc timeline MUST use the same `margin_left=220`, `chart_w=760`, `width=1040` as `render_swimlane`, so the two atoms register to identical x-coordinates (PR2 floats them aligned).
- **Voice rules apply to commits/PR bodies:** `introduced/wrote/chose/appears to have`; never `blame/fault/should have`.
- Pre-commit reformats long f-strings — if `git commit` aborts, `git add -u` and re-commit.

---

### Task 1: Pure lane-packing module `arc_layout.py`

**Files:**
- Create: `antiquarian/arc_layout.py`
- Test: `tests/test_arc_layout.py`

**Interfaces:**
- Consumes: nothing (pure; the spine `scale` is injected as a `Callable[[datetime], float]`).
- Produces:
  - `PlacedArc` (frozen dataclass): `arc: dict`, `x_start: float`, `x_end: float`.
  - `pack_arcs(arcs: list[dict], scale: Callable[[datetime], float], *, gap: float = LANE_GAP_PX, min_width: float = MIN_LOZENGE_PX) -> list[list[PlacedArc]]` — returns rows; each row is a left-to-right list of non-overlapping `PlacedArc`. Arcs with no datable commits are excluded from packing (they still appear in the renderer's full list). Module constants `LANE_GAP_PX = 4.0`, `MIN_LOZENGE_PX = 3.0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arc_layout.py
"""Tests for the pure arc lane-packing module (#112).

pack_arcs places every datable arc onto the fewest horizontal rows such that
no two lozenges overlap within a row — a greedy interval packing, proven here
independently of any SVG. The spine is injected as a plain callable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from antiquarian.arc_layout import (
    LANE_GAP_PX,
    MIN_LOZENGE_PX,
    PlacedArc,
    pack_arcs,
)

BASE = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _scale(dt: datetime) -> float:
    """Days-since-BASE as the pixel coordinate — a simple injectable spine."""
    return (dt - BASE).total_seconds() / 86400.0


def _arc(number: int, start_day: float, end_day: float, *, extra_commits: int = 0) -> dict:
    """An arc whose datable commits span [start_day, end_day]."""
    commits = [
        {"timestamp": (BASE + timedelta(days=start_day)).isoformat(), "short_sha": "a"},
        {"timestamp": (BASE + timedelta(days=end_day)).isoformat(), "short_sha": "b"},
    ]
    commits += [{"timestamp": None, "short_sha": "x"} for _ in range(extra_commits)]
    return {"arc_number": number, "name": f"Arc {number}", "file_path": "a.py", "commits": commits}


def _no_overlap_within_rows(rows: list[list[PlacedArc]], gap: float) -> bool:
    for row in rows:
        ordered = sorted(row, key=lambda p: p.x_start)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.x_start < prev.x_end + gap:
                return False
    return True


def test_empty_arcs_yields_no_rows():
    assert pack_arcs([], _scale) == []


def test_single_arc_one_row():
    rows = pack_arcs([_arc(1, 0, 10)], _scale)
    assert len(rows) == 1
    assert len(rows[0]) == 1
    assert rows[0][0].x_start == 0.0
    assert rows[0][0].x_end == 10.0


def test_overlapping_arcs_get_separate_rows():
    rows = pack_arcs([_arc(1, 0, 10), _arc(2, 5, 15)], _scale)
    assert len(rows) == 2


def test_disjoint_arcs_share_a_row():
    # second arc starts well after the first ends (> gap)
    rows = pack_arcs([_arc(1, 0, 10), _arc(2, 40, 50)], _scale)
    assert len(rows) == 1
    assert len(rows[0]) == 2


def test_every_datable_arc_placed_exactly_once():
    arcs = [_arc(i, i * 2, i * 2 + 1) for i in range(20)] + [_arc(99, 0, 100)]
    rows = pack_arcs(arcs, _scale)
    placed = [p.arc["arc_number"] for row in rows for p in row]
    assert sorted(placed) == sorted(a["arc_number"] for a in arcs)
    assert len(placed) == len(set(placed))  # exactly once


def test_no_overlap_within_any_row():
    arcs = [_arc(i, i, i + 5) for i in range(30)]
    rows = pack_arcs(arcs, _scale)
    assert _no_overlap_within_rows(rows, LANE_GAP_PX)


def test_non_datable_arcs_are_excluded():
    nodate = {"arc_number": 7, "name": "Arc 7", "file_path": "a.py",
              "commits": [{"timestamp": None, "short_sha": "x"}]}
    rows = pack_arcs([_arc(1, 0, 10), nodate], _scale)
    placed = [p.arc["arc_number"] for row in rows for p in row]
    assert placed == [1]


def test_single_commit_arc_gets_min_width():
    rows = pack_arcs([_arc(1, 5, 5)], _scale)  # zero-span
    pa = rows[0][0]
    assert pa.x_end - pa.x_start == MIN_LOZENGE_PX


def test_deterministic_and_sorted_by_start():
    arcs = [_arc(3, 30, 31), _arc(1, 0, 1), _arc(2, 60, 61)]
    rows = pack_arcs(arcs, _scale)
    # all disjoint -> one row, ordered by start time regardless of input order
    assert [p.arc["arc_number"] for p in rows[0]] == [1, 3, 2]
    assert pack_arcs(arcs, _scale) == rows  # stable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_layout.py -q`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'antiquarian.arc_layout'`.

- [ ] **Step 3: Write the module**

```python
# antiquarian/arc_layout.py
"""Pure lane-packing for the named-arcs density timeline (#112).

Turns the arcs list into the fewest horizontal rows such that no two arc
lozenges overlap within a row — classic greedy interval (activity-selection)
packing. No HTML, no SVG; the spine is injected as a ``Callable`` so this is
testable without the renderer. ``render.py`` walks the rows and draws lozenges.
See docs/superpowers/specs/2026-06-17-index-as-map-design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

#: Minimum horizontal gap (px) between two lozenges sharing a row.
LANE_GAP_PX = 4.0
#: Minimum visible width (px) for a single-commit (zero-span) arc.
MIN_LOZENGE_PX = 3.0


@dataclass(frozen=True)
class PlacedArc:
    """One arc placed on the timeline: the source ``arc`` dict and its px span."""

    arc: dict
    x_start: float
    x_end: float


def _arc_span(arc: dict) -> tuple[datetime, datetime] | None:
    """Earliest/latest datable commit timestamp, or None if the arc has none."""
    stamps = [
        datetime.fromisoformat(c["timestamp"])
        for c in arc["commits"]
        if c["timestamp"]
    ]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def pack_arcs(
    arcs: list[dict],
    scale: Callable[[datetime], float],
    *,
    gap: float = LANE_GAP_PX,
    min_width: float = MIN_LOZENGE_PX,
) -> list[list[PlacedArc]]:
    """Greedy lane-pack datable arcs into non-overlapping rows.

    Each arc is placed in the first row whose last lozenge ends at least ``gap``
    px before this arc starts; otherwise a new row opens. Arcs with no datable
    commits are skipped (the renderer lists them separately). Deterministic:
    arcs are processed sorted by (start, end).
    """
    intervals: list[tuple[float, float, dict]] = []
    for arc in arcs:
        span = _arc_span(arc)
        if span is None:
            continue
        x_start = scale(span[0])
        x_end = scale(span[1])
        if x_end < x_start + min_width:
            x_end = x_start + min_width
        intervals.append((x_start, x_end, arc))

    intervals.sort(key=lambda iv: (iv[0], iv[1]))

    rows: list[list[PlacedArc]] = []
    row_ends: list[float] = []
    for x_start, x_end, arc in intervals:
        placed = False
        for r in range(len(row_ends)):
            if x_start >= row_ends[r] + gap:
                rows[r].append(PlacedArc(arc, x_start, x_end))
                row_ends[r] = x_end
                placed = True
                break
        if not placed:
            rows.append([PlacedArc(arc, x_start, x_end)])
            row_ends.append(x_end)
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_layout.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add antiquarian/arc_layout.py tests/test_arc_layout.py
git commit -m "feat: pure lane-packing module for the arc density timeline (#112)"
```

---

### Task 2: Render the packed density timeline in `render_arc_band`

**Files:**
- Modify: `antiquarian/render.py` — the `render_arc_band` function (currently ~lines 723–812), the import block (~line 38), and the page `<style>` block (add `.arc-list` rules + `@media print`, near the existing `.swimlane-tail` rules ~line 1276).
- Test: `tests/test_arc_timeline.py` (new file — kept separate from `test_render.py` to avoid the shared-tail merge clashes seen on #128/#129).

**Interfaces:**
- Consumes: `pack_arcs`, `PlacedArc` from Task 1; existing `build_absolute_scale`, `_atom_timeline_strip`, `_render_dormancy_hatch`, `_render_absolute_axis`, `_defs`, `_iso_to_dt`, `_xml_escape`, `ARC_COLORS`, `PALETTE` (all already in `render.py`).
- Produces: `render_arc_band(arc_band: dict, timeline: dict) -> str` returning SVG **plus** a trailing `<details class="arc-list">…</details>`. Lozenge rects carry `class="arc-lozenge"` and `data-arc="<arc_number>"` (the data attribute is forward-compat for PR3's cross-highlight).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arc_timeline.py
"""Tests for the packed density-timeline rendering of named arcs (#112).

The lane-packing math is proven in test_arc_layout.py; here we assert the SVG
shell wires it in: one lozenge per datable arc, registered to the shared spine,
plus a folded full-arc list that prints expanded.
"""

from __future__ import annotations

from antiquarian.render import render_arc_band

TIMELINE = {
    "full_span": {
        "start": "2020-01-01T00:00:00+00:00",
        "end": "2026-01-01T00:00:00+00:00",
        "days": 2192,
    },
    "active_windows": [],
    "gaps": [],
}


def _arc(number: int, start: str, end: str, name: str = "An arc", path: str = "a.py") -> dict:
    return {
        "arc_number": number,
        "name": name,
        "file_path": path,
        "commits": [
            {"timestamp": f"{start}T00:00:00+00:00", "short_sha": "aaa", "subject": "s"},
            {"timestamp": f"{end}T00:00:00+00:00", "short_sha": "bbb", "subject": "s"},
        ],
    }


def _band(arcs: list[dict]) -> dict:
    return {"arc_count": len(arcs), "arcs": arcs}


def test_one_lozenge_per_datable_arc():
    arcs = [_arc(1, "2021-01-01", "2021-06-01"), _arc(2, "2023-01-01", "2023-03-01")]
    out = render_arc_band(_band(arcs), TIMELINE)
    assert out.count('class="arc-lozenge"') == 2


def test_lozenge_carries_arc_number_dataattr():
    out = render_arc_band(_band([_arc(7, "2022-01-01", "2022-02-01")]), TIMELINE)
    assert 'data-arc="7"' in out


def test_full_arc_list_present_and_lists_every_arc():
    arcs = [_arc(1, "2021-01-01", "2021-02-01", name="Alpha"),
            _arc(2, "2022-01-01", "2022-02-01", name="Beta")]
    out = render_arc_band(_band(arcs), TIMELINE)
    assert 'class="arc-list"' in out
    assert "Alpha" in out and "Beta" in out


def test_non_datable_arc_listed_but_not_drawn():
    nodate = {"arc_number": 9, "name": "Ghost", "file_path": "a.py",
              "commits": [{"timestamp": None, "short_sha": "x", "subject": "s"}]}
    out = render_arc_band(_band([nodate]), TIMELINE)
    assert out.count('class="arc-lozenge"') == 0  # nothing on the spine
    assert "Ghost" in out  # but kept in the list (in-DOM rule)


def test_empty_arcs_uses_empty_atom():
    out = render_arc_band(_band([]), TIMELINE)
    assert "No arcs found." in out


def test_uses_swimlane_margins_for_spine_alignment():
    # width must match the swimlane (margin_left 220 + chart_w 760 + margin_right 60)
    out = render_arc_band(_band([_arc(1, "2021-01-01", "2021-06-01")]), TIMELINE)
    assert 'viewBox="0 0 1040 ' in out
```

```python
# tests/test_arc_timeline.py  (append — page-level print rule)
from antiquarian.render import render_broadsheet  # noqa: E402


def test_arc_list_prints_expanded():
    # minimal data bundle with one arc; render the whole page and check print CSS
    data = {
        "project": "p",
        "timeline": TIMELINE,
        "todos": [],
        "swimlane": {"lanes": []},
        "arc_band": _band([_arc(1, "2021-01-01", "2021-06-01")]),
        "file_lifespans": [],
        "files": [],
        "generated_at": "2026-06-17",
    }
    html = render_broadsheet(data)
    assert "@media print" in html
    assert ".arc-list" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_timeline.py -q`
Expected: FAIL — `test_one_lozenge_per_datable_arc` etc. fail because the current band emits no `class="arc-lozenge"`; `test_uses_swimlane_margins` fails because the current band width is `320+720+60=1100`, not `1040`.

- [ ] **Step 3: Add the import**

In `antiquarian/render.py`, extend the existing `from antiquarian.file_tree import (...)` import block by adding a second import directly beneath it:

```python
from antiquarian.arc_layout import PlacedArc, pack_arcs
```

(`PlacedArc` is imported for the type reference in the loop; if the linter flags it as unused, reference it only via `pack_arcs`'s return and drop the name — keep `pack_arcs`.)

- [ ] **Step 4: Replace the body of `render_arc_band`**

Replace the entire current `render_arc_band` function (from `def render_arc_band` through its `return "\n".join(parts)`) with:

```python
def render_arc_band(arc_band: dict, timeline: dict) -> str:
    """Packed density timeline of named arcs — broadsheet style (#112).

    All datable arcs are lane-packed onto the shared absolute spine (so they
    register x-for-x with the swimlane), collapsing ~one-row-per-arc into a
    handful of rows. Identity is progressive disclosure: hover a lozenge for
    its name, or open the folded full-arc list beneath (which lists every arc,
    including any with no datable commits, so nothing leaves the DOM).
    """
    arcs = arc_band["arcs"]
    if not arcs:
        return _empty_atom("The named arcs of the work", "No arcs found.")

    # Share the swimlane's geometry so the two atoms align (PR2 floats them).
    margin_top = 130
    margin_left = 220
    chart_w = 760
    margin_right = 60
    width = margin_left + chart_w + margin_right  # 1040
    lozenge_h = 12
    row_pitch = 18
    bottom_pad = 60

    axis = build_absolute_scale(timeline, chart_w)
    rows = pack_arcs(arcs, axis["scale"])
    file_paths = {arc["file_path"] for arc in arcs}

    height = margin_top + row_pitch * max(len(rows), 1) + bottom_pad

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" style="display:block; max-width: 100%; background: {PALETTE["paper"]};">',
        _defs(),
        _atom_timeline_strip(timeline, width, 30, width - 60),
        f'<text x="30" y="64" font-family="EB Garamond, Iowan Old Style, Palatino, Georgia, serif" '
        f'font-size="22" font-weight="600" fill="{PALETTE["ink"]}">The named arcs of the work</text>',
        f'<text x="30" y="86" font-family="EB Garamond, Iowan Old Style, serif" font-style="italic" '
        f'font-size="12" fill="{PALETTE["ink_dim"]}">'
        f"{len(arcs)} arc(s) across {len(file_paths)} file(s), packed onto the shared time spine. "
        "Each lozenge spans an arc's first to last decisive commit; hover for its name, "
        "or open the full list below."
        "</text>",
        f'<line x1="30" y1="90" x2="{width - 30}" y2="90" stroke="{PALETTE["ink"]}" stroke-width="0.6"/>',
        f'<line x1="30" y1="93" x2="{width - 30}" y2="93" stroke="{PALETTE["ink"]}" stroke-width="0.3"/>',
    ]

    chart_top = margin_top - 6
    chart_bottom = margin_top + row_pitch * max(len(rows), 1)
    parts.extend(
        _render_dormancy_hatch(
            timeline, axis["scale"], margin_left, chart_top, chart_bottom
        )
    )

    for r, row in enumerate(rows):
        y = margin_top + r * row_pitch
        for placed in row:
            arc = placed.arc
            color = ARC_COLORS[arc["arc_number"] % len(ARC_COLORS)]
            x = margin_left + placed.x_start
            w = max(placed.x_end - placed.x_start, 3)
            n_commits = len(arc["commits"])
            title = f"Arc {arc['arc_number']}: {arc['name']} — {n_commits} commit(s)"
            parts.append(
                f'<rect class="arc-lozenge" data-arc="{arc["arc_number"]}" '
                f'x="{x}" y="{y}" width="{w}" height="{lozenge_h}" '
                f'fill="{color}" opacity="0.4" stroke="{color}" stroke-width="0.6" rx="1.5">'
                f"<title>{_xml_escape(title)}</title></rect>"
            )

    axis_y = chart_bottom + 8
    parts.append(_render_absolute_axis(timeline, margin_left, chart_w, axis_y))
    parts.append("</svg>")

    return "\n".join(parts) + _render_arc_list(arcs)


def _render_arc_list(arcs: list[dict]) -> str:
    """Folded, print-expanded list of every arc — keeps all arcs in the DOM."""
    items = []
    for arc in arcs:
        datable = sum(1 for c in arc["commits"] if c["timestamp"])
        items.append(
            f'<li><span class="arc-num">Arc {arc["arc_number"]}</span> '
            f'{_xml_escape(arc["name"])} '
            f'<span class="arc-file">{_xml_escape(arc["file_path"])}</span> '
            f'<span class="count">{datable} dated commit(s)</span></li>'
        )
    return (
        '<details class="arc-list"><summary>all '
        f"{len(arcs)} arcs in full</summary><ul>" + "".join(items) + "</ul></details>"
    )
```

- [ ] **Step 5: Add the `.arc-list` CSS and print rule**

In `render.py`, find the `@media print {` block that contains `.swimlane-tail > *:not(summary)` (inside the page `<style>`, ~line 1276). Immediately **before** that `@media print {` block, insert the `.arc-list` styles, and **inside** that same `@media print` block add the arc-list expansion. Concretely, replace:

```python
    /* Folded long tail of contributors (#118) — searchable, print-expanded. */
    .swimlane-tail {{
```

with:

```python
    /* Folded full-arc list beneath the density timeline (#112). */
    .arc-list {{
      font-family: var(--serif);
      font-size: 0.8rem;
      color: var(--ink-dim);
      margin: 0.25rem 0 0.5rem;
    }}
    .arc-list > summary {{
      cursor: pointer;
      font-style: italic;
      color: var(--accent);
    }}
    .arc-list ul {{
      columns: 2;
      list-style: none;
      padding: 0;
      margin: 0.6rem 0 0;
    }}
    .arc-list li {{ break-inside: avoid; margin-bottom: 0.2rem; }}
    .arc-list .arc-num {{ color: var(--accent); font-variant-numeric: tabular-nums; }}
    .arc-list .arc-file {{
      font-family: ui-monospace, "SF Mono", Monaco, monospace;
      font-size: 0.82em;
    }}
    .arc-list .count {{ color: var(--rule); font-variant-numeric: tabular-nums; }}
    /* Folded long tail of contributors (#118) — searchable, print-expanded. */
    .swimlane-tail {{
```

Then find this existing block:

```python
    @media print {{
      /* Force every folded hand visible on paper; drop the toggle affordance. */
      .swimlane-tail > *:not(summary) {{ display: block !important; }}
      .swimlane-tail > summary {{ list-style: none; color: var(--ink-dim); }}
```

and insert two lines after the `.swimlane-tail > summary` line (still inside the `@media print` block):

```python
      /* The full arc list prints expanded beneath the timeline (#112). */
      .arc-list > *:not(summary) {{ display: block !important; }}
      .arc-list > summary {{ list-style: none; color: var(--ink-dim); }}
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_timeline.py -q`
Expected: PASS (7 passed).

- [ ] **Step 7: Run the full suite to verify no regressions**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest -q`
Expected: PASS (all green — prior count + 16 new).

- [ ] **Step 8: Run pre-commit (ruff format/lint)**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pre-commit run --files antiquarian/arc_layout.py antiquarian/render.py tests/test_arc_layout.py tests/test_arc_timeline.py`
Expected: ruff-format may reformat long f-strings (it rewrites and "fails" once). If so, re-run the same command; expected second run all Passed.

- [ ] **Step 9: Commit**

```bash
git add antiquarian/render.py tests/test_arc_timeline.py
git commit -m "feat(render): pack named arcs into a density timeline on the shared spine (#112)"
```

---

### Task 3: Validate at httpx scale (verification, no new code)

**Files:** none (uses the recovered free re-render engine).

- [ ] **Step 1: Re-render httpx from the existing cache (free — no `claude -p` spend)**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run antiquarian render --repo ~/Documents/work/antiquarian-httpx/httpx-repo`
Expected: `115 file(s), 1317 commit(s), 202 arc(s), 1 todo(s)` and an `index.html` path.

- [ ] **Step 2: Confirm the band collapsed and the list is complete**

```bash
python3 - <<'EOF'
html = open("/Users/tom/Documents/work/antiquarian-httpx/httpx-repo/.antiquarian/render/index.html").read()
print("lozenges:", html.count('class="arc-lozenge"'))
print("arc-list present:", 'class="arc-list"' in html)
EOF
```
Expected: `lozenges:` close to 202 (datable arcs); `arc-list present: True`.

- [ ] **Step 3: Eyeball the page height drop**

Open `file:///Users/tom/Documents/work/antiquarian-httpx/httpx-repo/.antiquarian/render/index.html`; confirm "The named arcs of the work" is now a compact (~20-row) lozenge field on the same x-axis as "Hands that touched the work" directly above it, not a multi-thousand-pixel stack. Confirm the folded "all 202 arcs in full" list opens and lists every arc.

- [ ] **Step 4: Report** the before/after page height and a screenshot to Tom; do **not** commit anything in this task.

---

## Self-Review

- **Spec coverage:** PR1 section of the spec (`arc_layout.py` greedy packing + lozenge render + folded in-DOM list + print expansion + spine sharing) → Tasks 1–2; httpx validation → Task 3. PR2 (float), PR3 (cross-highlight), PR4 (sidebar/glyph) are explicitly out of this plan and get their own plans. ✓
- **Placeholders:** none — all test and impl code is concrete. ✓
- **Type consistency:** `pack_arcs(arcs, scale, *, gap, min_width) -> list[list[PlacedArc]]` and `PlacedArc(arc, x_start, x_end)` are used identically in Task 1 (definition), Task 1 tests, and Task 2 (`placed.arc`, `placed.x_start`, `placed.x_end`). The render adds `class="arc-lozenge"` / `data-arc` exactly as the Task 2 tests assert. ✓
- **Margins:** `width=1040` (220+760+60) matches `render_swimlane` and the Task 2 `viewBox="0 0 1040 "` assertion. ✓
