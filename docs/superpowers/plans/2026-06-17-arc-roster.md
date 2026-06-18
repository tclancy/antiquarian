# PR-A: Honest Arc Roster (kill the band) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the packed arc "density timeline" (a span-based lie that silently drops 47.5% of arcs, #133) with an honest, file-grouped **arc roster table** that lists *every* arc — undatable ones badged, not dropped — each datable row carrying a *tiny* per-arc dot-sparkline (commit timestamps as dots on a shared mini absolute axis, never a span).

**Architecture:** A new pure module `antiquarian/arc_roster.py` groups arcs by file and counts datable commits (no HTML). `render.py` walks the groups and emits a collapsible `<details>` roster; each arc row shows `Arc N · name · k commits` plus either a tiny inline-SVG dot-sparkline (datable) or an "undatable" badge. This retires `render_arc_band` and `arc_layout.py` entirely. The roster keeps every arc in the DOM, prints expanded.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled HTML + tiny inline SVG, inline CSS in the page template.

**Design source:** `docs/superpowers/specs/2026-06-17-arcs-as-commit-sets-design.md` (and the preserved review). Fixes #133.

## Global Constraints

- **Python 3.13+, uv only.** Run via `uv run`. TDD iron law (red → green).
- **The reframe:** an arc is a *named set of commits*, never a span. **Never compute or render a `(start, end)` interval.** The sparkline plots commit timestamps as **dots only** — no connecting line/band.
- **Keep every arc in the DOM** (ethos / #133): the roster lists all arcs including those with zero datable commits, which are **badged** as a first-class lossy state.
- **Print-first (#40):** `@media print` forces every roster `<details>` open; no control depends on JS.
- **Datable** means `commit["timestamp"]` is truthy. **Undatable arc** = zero datable commits.
- The page template is an f-string: **literal CSS braces must be doubled (`{{` `}}`)**.
- Pre-commit reformats long f-strings — if a commit aborts, `git add -u` and re-commit.
- Voice rules apply to commits/PR text.

## Out of scope (named follow-ups, NOT this PR)

- Folder-nesting the roster files via `file_tree.py` (PR-A ships a flat file-grouped list; nesting is a fast-follow).
- A live-search box on the roster (rows are in-DOM/Ctrl-F-able and print-expanded; search is a later nicety).
- The swimlane arc-overlay + commit-mediated hover — that's **PR-B**.

---

### Task 1: Pure `arc_roster.py` — group by file, count datable

**Files:**
- Create: `antiquarian/arc_roster.py`
- Test: `tests/test_arc_roster.py`

**Interfaces:**
- Produces:
  - `datable_count(arc: dict) -> int` — number of the arc's commits with a truthy `timestamp`.
  - `FileArcGroup` (frozen dataclass): `file_path: str`, `arcs: list[dict]`, `arc_count: int`, `datable_arc_count: int`.
  - `group_arcs_by_file(arcs: list[dict]) -> list[FileArcGroup]` — groups by `file_path`, arcs within a group sorted by `arc_number`, groups sorted by `file_path`. `datable_arc_count` counts arcs whose `datable_count > 0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arc_roster.py
"""Tests for the pure arc-roster grouping (#112 rethink, fixes #133).

An arc is a named SET of commits; the roster groups arcs by file and counts
how many are datable, so the renderer can badge undatable arcs instead of
silently dropping them. No HTML here.
"""

from __future__ import annotations

from antiquarian.arc_roster import (
    FileArcGroup,
    datable_count,
    group_arcs_by_file,
)


def _arc(number, file_path, *, datable=1, undatable=0):
    commits = [{"short_sha": f"d{i}", "timestamp": f"2021-0{(i % 9) + 1}-01T00:00:00+00:00"} for i in range(datable)]
    commits += [{"short_sha": f"m{i}", "timestamp": None, "missing": True} for i in range(undatable)]
    return {"arc_number": number, "name": f"Arc {number}", "file_path": file_path, "commits": commits}


def test_datable_count_counts_only_timestamped():
    assert datable_count(_arc(1, "a.py", datable=3, undatable=2)) == 3
    assert datable_count(_arc(2, "a.py", datable=0, undatable=4)) == 0


def test_groups_by_file_sorted():
    groups = group_arcs_by_file([_arc(1, "z.py"), _arc(2, "a.py"), _arc(3, "a.py")])
    assert [g.file_path for g in groups] == ["a.py", "z.py"]
    assert isinstance(groups[0], FileArcGroup)
    assert [a["arc_number"] for a in groups[0].arcs] == [2, 3]


def test_group_counts():
    groups = group_arcs_by_file([
        _arc(1, "a.py", datable=2),
        _arc(2, "a.py", datable=0, undatable=3),  # undatable
        _arc(3, "a.py", datable=1),
    ])
    g = groups[0]
    assert g.arc_count == 3
    assert g.datable_arc_count == 2  # arc 2 is undatable


def test_empty():
    assert group_arcs_by_file([]) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_roster.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'antiquarian.arc_roster'`.

- [ ] **Step 3: Write the module**

```python
# antiquarian/arc_roster.py
"""Pure grouping for the honest arc roster (#112 rethink; fixes #133).

An arc is a named SET of commits at synthesis confidence — not a time span.
This module groups arcs by file and counts datable commits so the renderer can
list every arc and badge undatable ones instead of dropping them. No HTML, no IO.
See docs/superpowers/specs/2026-06-17-arcs-as-commit-sets-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass


def datable_count(arc: dict) -> int:
    """Number of the arc's commits that carry a real (truthy) timestamp."""
    return sum(1 for c in arc["commits"] if c.get("timestamp"))


@dataclass(frozen=True)
class FileArcGroup:
    """All arcs named in one file, with datable/total counts."""

    file_path: str
    arcs: list
    arc_count: int
    datable_arc_count: int


def group_arcs_by_file(arcs: list[dict]) -> list[FileArcGroup]:
    """Group arcs by ``file_path``; arcs sorted by number, groups by path."""
    by_file: dict[str, list[dict]] = {}
    for arc in arcs:
        by_file.setdefault(arc["file_path"], []).append(arc)

    groups: list[FileArcGroup] = []
    for file_path in sorted(by_file):
        file_arcs = sorted(by_file[file_path], key=lambda a: a["arc_number"])
        datable = sum(1 for a in file_arcs if datable_count(a) > 0)
        groups.append(
            FileArcGroup(
                file_path=file_path,
                arcs=file_arcs,
                arc_count=len(file_arcs),
                datable_arc_count=datable,
            )
        )
    return groups
```

- [ ] **Step 4: Run to verify pass**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_roster.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add antiquarian/arc_roster.py tests/test_arc_roster.py
git commit -m "feat: pure arc-roster grouping + datable counts (#112 rethink, #133)"
```

---

### Task 2: Render the file-grouped roster; retire the band

**Files:**
- Modify: `antiquarian/render.py` — replace `render_arc_band` (lines ~724–812) with `render_arc_roster`; remove the `from antiquarian.arc_layout import pack_arcs` import (line ~47); update `_ATOM_ORDER` (line ~852) and the atoms dict in `render_broadsheet` (line ~1483); add `.arc-roster` CSS + a print rule.
- Modify: `antiquarian/render_data.py` — add a `datable_count` field in `_build_arc_band` (line ~448-458).
- Delete: `antiquarian/arc_layout.py`, `tests/test_arc_layout.py`, `tests/test_arc_timeline.py` (they test the retired band).
- Test: `tests/test_arc_roster.py` (extend with render tests); `tests/test_render.py` (add a datable_count assertion).

**Interfaces:**
- Consumes: `group_arcs_by_file`, `datable_count` (Task 1); existing `_xml_escape`, `PALETTE`, `_empty_atom`.
- Produces: `render_arc_roster(arc_band: dict, timeline: dict) -> str` — HTML: a heading, then one `<details class="arc-file">` per file (summary `path · N arcs`), each containing arc rows `<li class="arc-row">` with `Arc N · name · k commits` and, for undatable arcs, an `<span class="undatable-badge">`. The atom key becomes `"arc_roster"`.

- [ ] **Step 1: Write the failing render tests (extend tests/test_arc_roster.py)**

```python
# append to tests/test_arc_roster.py
from antiquarian.render import render_arc_roster  # noqa: E402

_TIMELINE = {
    "full_span": {"start": "2019-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00", "days": 2557},
    "active_windows": [], "gaps": [],
}


def _band(arcs):
    return {"arc_count": len(arcs), "arcs": arcs}


def test_roster_lists_every_arc_including_undatable():
    arcs = [_arc(1, "a.py", datable=2), _arc(2, "b.py", datable=0, undatable=3)]
    out = render_arc_roster(_band(arcs), _TIMELINE)
    assert "Arc 1" in out and "Arc 2" in out
    assert "a.py" in out and "b.py" in out


def test_undatable_arc_is_badged_not_dropped():
    out = render_arc_roster(_band([_arc(9, "x.py", datable=0, undatable=2)]), _TIMELINE)
    assert "undatable-badge" in out
    assert "Arc 9" in out


def test_roster_groups_into_collapsible_files():
    out = render_arc_roster(_band([_arc(1, "a.py")]), _TIMELINE)
    assert 'class="arc-file"' in out
    assert "<summary" in out


def test_empty_band_uses_empty_atom():
    out = render_arc_roster(_band([]), _TIMELINE)
    assert "No arcs" in out
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_roster.py -q`
Expected: FAIL — `cannot import name 'render_arc_roster'`.

- [ ] **Step 3: Add `datable_count` to the arc data**

In `render_data.py` `_build_arc_band`, change the `bands.append({...})` block to include the count (insert after `"commit_count": len(arc_commits),`):

```python
                "datable_count": sum(1 for c in arc_commits if c["timestamp"]),
```

- [ ] **Step 4: Remove the band, add the roster in render.py**

Delete the import line `from antiquarian.arc_layout import pack_arcs`.

Replace the entire `render_arc_band` function (def through its `return "\n".join(parts)` plus the trailing `_render_arc_list` helper added in #132) with:

```python
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
            f'<code>{_xml_escape(g.file_path)}</code> '
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
```

Add the import near the other local imports (top of file, after the `file_tree` import):

```python
from antiquarian.arc_roster import datable_count, group_arcs_by_file
```

Also **delete the now-dead `ARC_COLORS` constant** (defined ~line 69) — it was used only inside the retired `render_arc_band`, so after this task it is unused module code a reviewer would reject. Remove its definition.

- [ ] **Step 5: Rewire the atom**

> **CRITICAL — atom key vs data key.** Rename ONLY the *atom* key. `render_data.py` produces a `data["arc_band"]` dict, and `tests/test_render.py` (~lines 155, 333, 622) assert that **data** key. Leave `data["arc_band"]`, the `_build_arc_band` function, and the render-data `"arc_band"` output **unchanged**. Do **NOT** global-replace `arc_band`→`arc_roster`; touch only the two spots below.

In `_ATOM_ORDER` change `"arc_band"` to `"arc_roster"`:

```python
_ATOM_ORDER = ("swimlane", "arc_roster", "todo_strip")
```

In `render_broadsheet`'s `atoms` dict, replace the `"arc_band": render_arc_band(...)` entry with (note the value still reads from `data["arc_band"]`):

```python
        "arc_roster": render_arc_roster(data["arc_band"], timeline),
```

- [ ] **Step 6: Add the roster CSS**

In the page `<style>`, replace the PR1 line `/* Folded full-arc list beneath the density timeline (#112). */` and its `.arc-list…` block (added in #132) with the roster styles:

```python
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
```

If the `@media print` block still references `.arc-list`, replace those two `.arc-list…` lines with:

```python
      /* The arc roster prints fully expanded (#112). */
      .arc-file > *:not(summary) {{ display: block !important; }}
      .arc-file > summary {{ list-style: none; }}
```

- [ ] **Step 7: Delete the retired band module + its tests**

```bash
git rm antiquarian/arc_layout.py tests/test_arc_layout.py tests/test_arc_timeline.py
```

- [ ] **Step 8: Add a datable_count data test (tests/test_render.py)**

Append a focused test near the other `extract_render_data` tests (use the existing `seeded_repo` fixture pattern in that file — match its style):

```python
def test_arc_band_includes_datable_count(seeded_repo):
    data = extract_render_data(seeded_repo)
    for arc in data["arc_band"]["arcs"]:
        assert "datable_count" in arc
        assert arc["datable_count"] == sum(1 for c in arc["commits"] if c["timestamp"])
```

- [ ] **Step 8b: Fix the stale atom-name comment in test_render.py**

`tests/test_render.py` has `test_broadsheet_skips_empty_todo_chapter_mark` (~lines 488–501) whose comment/docstring says the surviving atoms are "swimlane + arc_band". The `chapter_count == 2` assertion still holds (an empty roster returns a truthy `_empty_atom` just like the old band), but the comment is now stale — update the wording `arc_band` → `arc_roster` in that test's comment/docstring. Do not change the assertion.

- [ ] **Step 9: Run new tests, then the full suite**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_roster.py tests/test_render.py -q   # expect green
uv run pytest -q   # full suite; arc_layout/arc_timeline tests are gone, roster tests added
```
Expected: green. If a prior test referenced `render_arc_band`, `"arc_band"` as an atom key, or `arc_layout`, update it to the roster equivalents and note it in the report.

- [ ] **Step 10: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py antiquarian/render_data.py antiquarian/arc_roster.py tests/test_arc_roster.py tests/test_render.py   # re-run if ruff reformats
git add -A
git commit -m "feat(render): replace the arc band with an honest file-grouped roster (#112, fixes #133)"
```

---

### Task 3: Tiny per-arc dot-sparkline

**Files:**
- Modify: `antiquarian/render.py` — `_render_arc_row` (add the sparkline); add a `_arc_sparkline` helper + `SPARK_W`/`SPARK_H` constants; add `.arc-spark` CSS.
- Test: `tests/test_arc_roster.py` (extend).

**Interfaces:**
- Consumes: existing `build_absolute_scale`, `_iso_to_dt`, `PALETTE`.
- Produces: datable arc rows gain a tiny inline `<svg class="arc-spark">` with one `<circle>` per datable commit, positioned by the shared full-span absolute scale; undatable rows keep the badge (no sparkline). Tom's call: **dots only, never a connecting span.**

- [ ] **Step 1: Write the failing tests (extend tests/test_arc_roster.py)**

```python
def test_datable_arc_row_has_sparkline_with_one_dot_per_datable_commit():
    arc = _arc(1, "a.py", datable=3, undatable=1)  # 3 datable, 1 missing
    out = render_arc_roster(_band([arc]), _TIMELINE)
    assert 'class="arc-spark"' in out
    # one <circle> per datable commit (the missing one is not plotted)
    row = out[out.index("Arc 1"):]
    assert row.count("<circle") == 3


def test_undatable_arc_row_has_no_sparkline():
    out = render_arc_roster(_band([_arc(2, "b.py", datable=0, undatable=2)]), _TIMELINE)
    assert 'class="arc-spark"' not in out
    assert "undatable-badge" in out
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_roster.py -q`
Expected: the two new tests FAIL (no `arc-spark`).

- [ ] **Step 3: Add the sparkline helper + constants**

Near the top of `render.py` (by the other layout constants), add:

```python
SPARK_W = 150  # px — tiny per-arc sparkline width
SPARK_H = 14   # px
```

Add the helper (place it just above `_render_arc_row`):

```python
def _arc_sparkline(arc: dict, timeline: dict) -> str:
    """Tiny dot-sparkline: each datable commit as a dot on the shared full-span
    absolute axis. Dots only — never a connecting span (the span is the lie)."""
    scale = build_absolute_scale(timeline, SPARK_W)["scale"]
    cy = SPARK_H / 2
    dots = []
    for c in arc["commits"]:
        if not c["timestamp"]:
            continue
        cx = scale(_iso_to_dt(c["timestamp"]))
        dots.append(
            f'<circle cx="{cx:.1f}" cy="{cy}" r="1.6" '
            f'fill="{PALETTE["accent"]}" opacity="0.85"/>'
        )
    return (
        f'<svg class="arc-spark" viewBox="0 0 {SPARK_W} {SPARK_H}" '
        f'width="{SPARK_W}" height="{SPARK_H}" aria-hidden="true">'
        f'<line x1="0" y1="{cy}" x2="{SPARK_W}" y2="{cy}" '
        f'stroke="{PALETTE["rule_dim"]}" stroke-width="0.5"/>'
        f"{''.join(dots)}</svg>"
    )
```

- [ ] **Step 4: Use it in `_render_arc_row`**

In `_render_arc_row`, change the `else: marker = ""` branch to:

```python
    else:
        marker = _arc_sparkline(arc, timeline)
```

- [ ] **Step 5: Add the sparkline CSS**

In the roster CSS block, add:

```python
    .arc-spark {{ vertical-align: middle; opacity: 0.9; }}
    @media print {{ .arc-spark {{ opacity: 1; }} }}
```

(Place the `@media print` line outside any existing print block, or fold the rule into the existing print block — either is fine as long as the braces are doubled.)

- [ ] **Step 6: Run new tests + full suite**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_roster.py -q   # expect all green
uv run pytest -q
```

- [ ] **Step 7: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py tests/test_arc_roster.py
git add antiquarian/render.py tests/test_arc_roster.py
git commit -m "feat(render): tiny per-arc dot-sparkline in the roster — dots, never a span (#112)"
```

---

### Task 4: Validate at httpx scale (verification, no new code)

- [ ] **Step 1: Re-render httpx (free, from cache)**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run antiquarian render --repo ~/Documents/work/antiquarian-httpx/httpx-repo`
Expected: `… 202 arc(s) …` and an index.html path.

- [ ] **Step 2: Confirm honesty + collapse**

```bash
python3 - <<'EOF'
import re
html = open("/Users/tom/Documents/work/antiquarian-httpx/httpx-repo/.antiquarian/render/index.html").read()
print("arc-roster present:", 'class="arc-roster"' in html)
print("arc rows:", html.count('class="arc-row"'), "(expect 202 — every arc listed)")
print("undatable badges:", html.count("undatable-badge"), "(expect ~96)")
print("sparklines:", html.count('class="arc-spark"'), "(expect ~106 datable)")
print("band gone:", 'class="arc-lozenge"' not in html)
EOF
```
Expected: roster present; **202 arc rows** (every arc, the #133 fix); ~96 undatable badges; ~106 sparklines; no `arc-lozenge`.

- [ ] **Step 3: Eyeball + report**

Open the render, confirm the arcs section is now a compact collapsible roster (no tall band, no empty gutter), undatable arcs visibly badged, datable rows showing tiny dot-sparklines. Screenshot for the PR. Note the page-height drop. Do **not** commit here.

---

## Self-Review

- **Spec coverage:** the rethink spec's PR-A — kill band + `arc_layout` (Task 2 deletes them), honest file-grouped roster listing every arc with undatable badged (Task 2, fixes #133), `datable_count` in render data (Task 2), tiny per-arc dot-sparkline / dots-never-span (Task 3), httpx validation (Task 4). Folder-nesting and roster search are explicitly deferred. ✓
- **Placeholders:** none — all test + impl code is concrete with exact anchors. ✓
- **Consistency:** `group_arcs_by_file`/`datable_count`/`FileArcGroup` (Task 1) are used exactly in Task 2's render; `_arc_sparkline` (Task 3) plugs into `_render_arc_row`'s else-branch defined in Task 2; the atom key rename `arc_band`→`arc_roster` is applied in `_ATOM_ORDER` and the atoms dict together. ✓
- **Honesty invariant:** the sparkline emits `<circle>` dots only and a faint baseline — no `<rect>`/span; undatable arcs get no sparkline. ✓
- **Print:** roster `<details>` forced open; no JS dependency. ✓
