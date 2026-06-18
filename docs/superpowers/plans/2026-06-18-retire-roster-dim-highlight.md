# Retire the arc roster + dim-the-rest highlight + richer hover context

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Per Tom's review of the live render: (1) **delete the "The named arcs of the work" roster** entirely — it's a context-free list of files with arcs buried in them and nothing to navigate to; arcs live on story pages (Major Arcs) and as the swimlane overlay (resolves #137). (2) Make the swimlane co-arc hover **legible by dimming the rest** (fade unrelated marks so the arc's real commits pop). (3) Give the hover **real context** — a tooltip with the arc name, when, and the files changed (or "N files changed").

**Architecture:** Remove `render_arc_roster`/`_render_arc_row`/`_arc_sparkline`, the `arc_roster` atom, the roster CSS, and `antiquarian/arc_roster.py` + its tests; the swimlane overlay's `arc_lookup` is independent and stays. Pipe `CommitFeatures.files_changed` into the swimlane commit dict and enrich the bubble `<title>`. Change the existing hover script to add a `xref-dim` class to the swimlane `<svg>` (CSS fades all `.commit-bubble`, keeps `.commit-xref` full).

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG, inline CSS + the existing inline `<script>` (f-string: braces doubled).

## Global Constraints
- Python 3.13+, uv. TDD (red → green).
- **Honesty unchanged:** the highlight still toggles classes on **real circle marks only** — dimming is opacity on existing marks, no new geometry, no band/span.
- The swimlane overlay (`arc_lookup`, `data-arcs`, story links from the prior PR) **stays** — only the standalone roster atom is removed.
- Print-first: the dim effect is a JS hover enhancement (degrades to nothing); tooltips are static `<title>`.
- Page template is an f-string: literal CSS/JS braces doubled (`{{`/`}}`); keep the regex `/\\s+/` (double backslash).
- Pre-commit may reformat — `git add -u`/`-A` and re-commit. Voice rules on commits.

---

### Task 1: Retire the arc roster atom

**Files:**
- Modify: `antiquarian/render.py` — remove the `arc_roster` import (line ~47), `render_arc_roster` + `_render_arc_row` + `_arc_sparkline` (lines ~736–815), the `_ATOM_ORDER` entry (line ~852), the atoms-dict entry (line ~1514), and the roster CSS block (`.arc-roster`, `.arc-file`, `.arc-row`, `.undatable-badge`, `.arc-spark` and their `@media print` lines).
- Delete: `antiquarian/arc_roster.py`, `tests/test_arc_roster.py`.
- Test: `tests/test_render.py` (update any atom-count/roster assertions).

**Interfaces:**
- Produces: `_ATOM_ORDER = ("swimlane", "todo_strip")`. No `render_arc_roster`. The arc *data* (`data["arc_band"]`) and `render_broadsheet`'s `arc_lookup` for the swimlane overlay are untouched.

- [ ] **Step 1: Write/adjust the failing test**

Add to `tests/test_render.py` (near other `render_broadsheet` tests, using its fixtures) a test pinning the removal:

```python
def test_no_standalone_arc_roster_section(seeded_repo):
    from antiquarian.render_data import extract_render_data
    data = extract_render_data(seeded_repo)
    html = render_broadsheet(data)
    assert 'class="arc-roster"' not in html
    assert "The named arcs of the work" not in html
    # arc data still flows to the swimlane overlay
    assert "data-arcs=" in html
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_render.py::TestBroadsheet -q` (or the class holding it) — the new test FAILs (roster still present).

- [ ] **Step 3: Remove the import + atom wiring**

In `render.py`: delete the line `from antiquarian.arc_roster import datable_count, group_arcs_by_file`. Change `_ATOM_ORDER` to `("swimlane", "todo_strip")`. In `render_broadsheet`'s atoms dict, delete the `"arc_roster": render_arc_roster(data["arc_band"], timeline),` line.

- [ ] **Step 4: Delete the roster render functions**

Delete `render_arc_roster`, `_render_arc_row`, and `_arc_sparkline` entirely (the contiguous block ~736–815; confirm by reading the surrounding defs). Also delete the `SPARK_W`/`SPARK_H` constants if they were added near the top for the sparkline (grep `SPARK_W`).

- [ ] **Step 5: Delete the roster CSS**

In the page `<style>`, remove the roster style block (the `.arc-roster` / `.arc-file` / `.arc-row` / `.undatable-badge` / `.arc-spark` rules) and the roster-specific `@media print` lines (`.arc-file > *:not(summary)` etc.). Leave the swimlane/`commit-bubble`/`commit-xref` and other atoms' CSS intact.

- [ ] **Step 6: Delete the module + its tests**

```bash
git rm antiquarian/arc_roster.py tests/test_arc_roster.py
```

- [ ] **Step 7: Run new test + full suite, fixing atom-count fallout**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_render.py -q
uv run pytest -q
```
Known fallout to fix: `test_broadsheet_skips_empty_todo_chapter_mark` (~line 488) asserted "swimlane + arc_roster" = 2 chapter marks. With the roster gone, atoms are `(swimlane, todo_strip)`; update that test's expectation/comment to match the new atom set (e.g. with a TODO present the marks are swimlane + todo_strip; with empty TODO only swimlane). Read the test and set the correct count. Fix any other test referencing `render_arc_roster`, `arc_roster`, `"arc_roster"`, `_arc_sparkline`, `datable_count`, or the roster markup; note each in your report.

- [ ] **Step 8: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py tests/test_render.py
git add -A
git commit -m "feat(render): retire the standalone arc roster — arcs live on story pages + the overlay (#137)"
```

---

### Task 2: Dim-the-rest highlight + richer hover tooltip

**Files:**
- Modify: `antiquarian/render_data.py` — add `files_changed` to the swimlane commit dict in `_build_swimlane`.
- Modify: `antiquarian/render.py` — enrich the bubble `<title>` (when + files) in `render_swimlane`; swap the `.commit-xref` CSS for the dim-the-rest rules; add `xref-dim` toggling in the hover script.
- Test: `tests/test_arc_overlay.py` (extend).

**Interfaces:**
- Consumes: per-commit `files_changed` (now in the swimlane dict), existing `arc_lookup`, `c["date"]`.
- Produces: each commit `<title>` reads `<sha> — <subject> (<LoC> LoC) · <when> · <files summary>[ · arc: <names>]`, where files summary is the names if ≤2 else `"N files changed"`. On hover, the swimlane `<svg>` gets `xref-dim`; CSS fades every `.commit-bubble` except `.commit-xref`.

- [ ] **Step 1: Write the failing tests (extend tests/test_arc_overlay.py)**

```python
def test_tooltip_includes_when_and_files():
    c = _commit("abc123", ["transport-api"])
    c["date"] = "2021-06-01"
    c["files_changed"] = ["httpx/_client.py", "httpx/_models.py"]
    out = render_swimlane({"lanes": [_lane([c])]}, _TIMELINE, [])
    assert "2021-06-01" in out
    assert "httpx/_client.py" in out and "httpx/_models.py" in out


def test_tooltip_summarizes_many_files():
    c = _commit("abc123", [])
    c["date"] = "2021-06-01"
    c["files_changed"] = ["a.py", "b.py", "c.py", "d.py"]
    out = render_swimlane({"lanes": [_lane([c])]}, _TIMELINE, [])
    assert "4 files changed" in out


def test_dim_the_rest_css_present():
    from antiquarian.render import render_broadsheet
    data = {
        "project": "p", "timeline": _TIMELINE, "todos": [],
        "swimlane": {"lanes": [_lane([_commit("abc123", ["a-slug"])])]},
        "arc_band": {"arc_count": 0, "arcs": []},
        "file_lifespans": [], "files": [], "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert "xref-dim" in html  # the hover-dim class is wired in CSS + script
```

Update the `_commit` helper to accept/carry `files_changed` and `date` if it doesn't already (it builds the commit dict — add `"files_changed": [], "date": ts[:10]` defaults so existing tests keep passing).

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_overlay.py -q` — the three new tests FAIL.

- [ ] **Step 3: Pipe `files_changed` into the swimlane commit dict**

In `render_data.py` `_build_swimlane`, in the per-commit dict (the block with `"subject": c.message_subject, "arcs": c.arcs,`), add:

```python
                "files_changed": c.files_changed,
```

- [ ] **Step 4: Enrich the tooltip in `render_swimlane`**

Replace the title-building lines (currently):

```python
            title = c["short_sha"] + " — " + c["subject"] + " (" + str(diff) + " LoC)"
            arc_names = [lookup[s]["name"] for s in slugs if s in lookup]
            if arc_names:
                title += " · arc: " + "; ".join(arc_names)
```

with:

```python
            title = c["short_sha"] + " — " + c["subject"] + " (" + str(diff) + " LoC)"
            when = c.get("date") or (c["timestamp"][:10] if c.get("timestamp") else "")
            if when:
                title += " · " + when
            files = c.get("files_changed") or []
            if files:
                title += " · " + (
                    ", ".join(files) if len(files) <= 2 else f"{len(files)} files changed"
                )
            arc_names = [lookup[s]["name"] for s in slugs if s in lookup]
            if arc_names:
                title += " · arc: " + "; ".join(arc_names)
```

- [ ] **Step 5: Swap the highlight CSS for dim-the-rest**

Find the existing rule `.commit-xref {{ stroke-width: 2.4 !important; opacity: 1 !important; }}` and replace it with:

```python
    /* Co-arc hover: dim the rest so the arc's real commits pop (#119). */
    svg.xref-dim .commit-bubble {{ opacity: 0.1; transition: opacity 0.12s ease; }}
    svg.xref-dim .commit-bubble.commit-xref {{ opacity: 1; stroke-width: 1.4; }}
```

- [ ] **Step 6: Add `xref-dim` toggling to the hover script**

In the existing co-arc `<script>`, in the `mouseenter` handler add (before/after the co-arc loop) a line to dim the host svg, and in `mouseleave` remove it:

mouseenter — add at the top of the handler:
```javascript
        var svg = b.closest('svg'); if (svg) svg.classList.add('xref-dim');
```
mouseleave — add at the top of the handler:
```javascript
        var svg = b.closest('svg'); if (svg) svg.classList.remove('xref-dim');
```
(Keep the existing `commit-xref` add/remove loop; the hovered bubble shares its own slug so it stays full — intended.)

- [ ] **Step 7: Run new tests + full suite**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_overlay.py -q
uv run python -W error::SyntaxWarning -W error::DeprecationWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
```

- [ ] **Step 8: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py antiquarian/render_data.py tests/test_arc_overlay.py
git add antiquarian/render.py antiquarian/render_data.py tests/test_arc_overlay.py
git commit -m "feat(render): dim-the-rest co-arc highlight + arc/when/files hover context (#119)"
```

---

### Task 3: Validate + feel-test + present (no new code)

- [ ] **Step 1: Re-render** `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run antiquarian render --repo ~/Documents/work/antiquarian-httpx/httpx-repo`

- [ ] **Step 2: Confirm**
```bash
python3 - <<'EOF'
html = open("/Users/tom/Documents/work/antiquarian-httpx/httpx-repo/.antiquarian/render/index.html").read()
print("roster gone:", "The named arcs of the work" not in html and 'class="arc-roster"' not in html)
print("swimlane overlay intact:", html.count("data-arcs=") > 100)
print("dim css:", "xref-dim" in html)
EOF
```
Expect: roster gone True; overlay intact; dim css present.

- [ ] **Step 3: Feel-test with rodney + present to Tom.** Add `xref-dim` to the swimlane svg + `commit-xref` to a few co-arc bubbles via dispatched hover; screenshot — confirm the arc's commits now read clearly against the dimmed field, and the tooltip shows arc + when + files. Report; do NOT auto-merge — present for Tom's nod.

---

## Self-Review
- Coverage: roster fully retired incl. module/tests/CSS/atom (#137); overlay preserved; dim-the-rest legibility; tooltip context (arc/when/files via piped `files_changed`). ✓
- Honesty: dimming is opacity on real marks; no geometry/band added. ✓
- Print/no-JS: dim is a hover JS enhancement; tooltips static; links unaffected. ✓
- f-string: CSS braces doubled; regex stays `/\\s+/`. ✓
- Fallout: atom-count test (`test_broadsheet_skips_empty_todo_chapter_mark`) named for fixing; grep for other roster refs in Step 7. ✓
