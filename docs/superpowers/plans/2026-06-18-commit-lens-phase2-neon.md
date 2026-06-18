# Commit lens — Phase 2: neon grow on the macro arc highlight

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. `- [ ]` checkboxes.

**Goal:** Upgrade the swimlane's co-arc highlight (the dim-the-rest from #142) so that, on hover, the arc's co-commits across contributors **grow and flare to a bright/near-neon colour keyed to the arc** — making the arc footprint pop against the dimmed field. Screen-interaction state only; print/at-rest stay the muted broadsheet. (Spec: `docs/superpowers/specs/2026-06-18-commit-lens-design.md`, decision #3.) This is the macro half of the commit lens; the click-to-pin lens itself is Phase 1, separate.

**Architecture:** Extend the existing `arc_lookup` (`slug → {name, story_href}`) with a `color` (a bright palette cycled per arc). Each decisive commit bubble gets `data-arc-color` (its first arc's neon). The existing hover script, when it lights co-arc bubbles, also sets their `fill` to the **hovered** bubble's `data-arc-color` (uniform per-arc tint); CSS grows `.commit-xref` via `transform: scale`. On mouseleave, fill is cleared. No band, no new geometry — emphasis on real marks.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG, inline CSS + the existing co-arc `<script>` (f-string: braces doubled).

## Global Constraints
- Python 3.13+, uv. TDD (red → green).
- **Screen-only state:** the neon/grow appears only on hover (JS). At rest and in print the swimlane is the muted palette — `@media print` already drops the JS state. No new geometry; emphasis on real `<circle>` marks only (honest).
- `arc_lookup` stays optional/backward-compatible; bubbles without arcs stay inert (no `data-arc-color`, no listener).
- f-string: literal CSS braces doubled (`{{`/`}}`); keep the existing regex `/\\s+/`.
- Pre-commit may reformat — `git add -u` and re-commit. Voice rules on commits.

---

### Task 1: Per-arc neon colour + grow on the co-arc highlight

**Files:**
- Modify: `antiquarian/render.py` — add a `NEON_ARC_COLORS` palette constant; extend the `arc_lookup` build in `render_broadsheet` with a cycled `color`; set `data-arc-color` on decisive bubbles in `render_swimlane`; update the `.commit-xref` CSS (grow); extend the hover `<script>` to apply/clear the neon fill.
- Test: `tests/test_arc_overlay.py` (extend).

**Interfaces:**
- Consumes: existing `arc_lookup`, `data-arcs`, the co-arc hover script, `.commit-xref`/`xref-dim`.
- Produces: `arc_lookup[slug]` gains `"color"` (a hex from `NEON_ARC_COLORS`, assigned by arc order, cycled). Decisive bubbles carry `data-arc-color="<hex>"` (their first arc's colour). On hover, co-arc bubbles grow (`transform: scale`) and take the hovered arc's neon fill; cleared on leave.

- [ ] **Step 1: Write the failing tests (extend tests/test_arc_overlay.py)**

```python
def test_decisive_bubble_carries_arc_color():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": None, "color": "#ff2d95"}}
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [], arc_lookup=lookup
    )
    assert 'data-arc-color="#ff2d95"' in out


def test_non_decisive_bubble_has_no_arc_color():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", [])])]}, _TIMELINE, [])
    assert "data-arc-color=" not in out


def test_broadsheet_assigns_neon_colors_and_grow_css():
    from antiquarian.render import render_broadsheet, NEON_ARC_COLORS
    data = {
        "project": "p", "timeline": _TIMELINE, "todos": [],
        "swimlane": {"lanes": [_lane([_commit("abc123", ["a-slug"])])]},
        "arc_band": {"arc_count": 1, "arcs": [
            {"arc_number": 1, "name": "An arc", "slug": "a-slug", "file_path": "a.py",
             "commits": [], "commit_count": 0, "datable_count": 0}]},
        "file_lifespans": [], "files": [], "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert f'data-arc-color="{NEON_ARC_COLORS[0]}"' in html  # first arc → first neon
    assert "transform: scale" in html  # the grow
    assert "data-arc-color" in html  # the script reads it (see below)
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_overlay.py -q` — the three new tests FAIL.

- [ ] **Step 3: Add the neon palette**

Near the top of `render.py` (by the other palette constants), add a bright/near-neon set whose hues echo the broadsheet's accent *types* (warm/red, blue, green, violet, amber, cyan) but cranked to vivid for the active state:

```python
# Bright, near-neon arc-highlight colours — a SCREEN-ONLY interaction state
# (the at-rest swimlane and print stay the muted broadsheet palette). Cycled
# per arc as "this-arc-vs-not" emphasis (#119 commit-lens, decision #3).
NEON_ARC_COLORS = [
    "#ff2d95",  # hot magenta-red
    "#00e0ff",  # electric cyan
    "#39ff14",  # neon green
    "#ffd400",  # vivid amber
    "#b14bff",  # bright violet
    "#ff7a18",  # neon orange
]
```

- [ ] **Step 4: Add `color` to `arc_lookup`**

In `render_broadsheet`, where `arc_lookup` is built (`for arc in data.get("arc_band", {}).get("arcs", []):`), assign a cycled colour by arc order. Use `enumerate`:

```python
    arc_lookup = {}
    for i, arc in enumerate(data.get("arc_band", {}).get("arcs", [])):
        md_name = arc["file_path"].replace("/", "__") + ".md"
        href = f"stories/{_story_md_to_html_name(md_name)}" if md_name in linked else None
        arc_lookup[arc["slug"]] = {
            "name": arc["name"],
            "story_href": href,
            "color": NEON_ARC_COLORS[i % len(NEON_ARC_COLORS)],
        }
```

- [ ] **Step 5: Set `data-arc-color` on decisive bubbles**

In `render_swimlane`, in the circle-building block, after computing `arc_names`/`slugs`, derive the bubble's arc colour (first slug present in the lookup) and add the attribute to the `<circle>`:

```python
            arc_color = next((lookup[s]["color"] for s in slugs if s in lookup and lookup[s].get("color")), None)
```
and add `data-arc-color="{arc_color}"` to the `<circle ...>` open tag **only when `arc_color`** is set (otherwise omit the attribute). Build the circle string so non-decisive / no-lookup bubbles carry no `data-arc-color`. Keep the existing `class="commit-bubble"`, `data-arcs`, `<title>`, and `<a>`-wrap logic intact.

- [ ] **Step 6: Update the `.commit-xref` CSS to grow**

Replace the dim's highlight rule so the lit marks grow (the fill is applied by the script):

```python
    svg.xref-dim .commit-bubble.commit-xref {{
      opacity: 1;
      stroke: var(--ink);
      stroke-width: 1;
      transform: scale(1.8);
      transform-box: fill-box;
      transform-origin: center;
    }}
```
(Keep the `svg.xref-dim .commit-bubble {{ opacity: 0.1; … }}` dim rule above it.)

- [ ] **Step 7: Apply the neon fill in the hover script**

In the co-arc `<script>`, the `mouseenter` handler currently adds `commit-xref` to co-arc bubbles. Capture the hovered bubble's colour once and set it as the `fill` on each lit bubble; clear on `mouseleave`. In `mouseenter`:

```javascript
        var color = b.getAttribute('data-arc-color');
```
then, where it does `o.classList.add('commit-xref')`, also `if (color) o.style.fill = color;`. In `mouseleave`, where it removes the class, also `o.style.fill = '';`. (Keep the `xref-dim` svg toggle and the `/\\s+/` regex unchanged.)

- [ ] **Step 8: Run new tests + full suite + import-clean check**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_overlay.py -q
uv run python -W error::SyntaxWarning -W error::DeprecationWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
```

- [ ] **Step 9: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py tests/test_arc_overlay.py
git add antiquarian/render.py tests/test_arc_overlay.py
git commit -m "feat(render): neon grow on the co-arc highlight — bright per-arc flare on hover (#119)"
```

---

### Task 2: Validate + feel-test + present (no new code)

- [ ] **Step 1: Re-render** `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run antiquarian render --repo ~/Documents/work/antiquarian-httpx/httpx-repo`
- [ ] **Step 2: Confirm** `data-arc-color=` present (decisive bubbles); `transform: scale` in CSS; suite green.
- [ ] **Step 3: Feel-test with rodney** — dispatch a `mouseenter` on a decisive bubble; confirm co-arc bubbles grow + flare neon against the dimmed field; **screenshot, and commit it under `docs/evolution/`**. Present to Tom (don't auto-merge — it's a visual feel call on the neon intensity/palette).

## Self-Review
- Coverage: per-arc neon (decision #3) on the macro highlight; grow; screen-only; honest (real marks). ✓
- Backward-compat: `arc_lookup` color is additive; non-decisive bubbles inert. ✓
- Print/no-JS: neon/grow are hover-JS only; at-rest + print unchanged. ✓
- f-string braces doubled; regex `/\\s+/` untouched. ✓
- Screenshot committed to `docs/evolution/` per the new practice. ✓
