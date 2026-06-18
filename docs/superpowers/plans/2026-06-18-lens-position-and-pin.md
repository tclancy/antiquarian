# Commit lens — position below the clicked row + pin the footprint

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. `- [ ]` checkboxes.

**Goal:** Two feel-test refinements to the lens (#146): (1) the lens panel appears **inline below the row you clicked**, overlaying the rest of the "Hands" timeline (not parked at the bottom of the swimlane); (2) while the lens is open with a commit selected, that commit's arc footprint stays **pinned-lit across all contributor rows** (held, not the transient hover that clears when you mouse away).

**Architecture:** (1) The lens becomes `position: absolute` inside the (now `position: relative`) swimlane atom, with `top` computed from the clicked lane's bottom edge; an opaque paper background + shadow so it reads as hovering over the rows below. (2) Merge the separate co-arc hover `<script>` into the lens `<script>` so both share `paint(bubble)`/`unpaint()` and a `pinned` flag: hovers paint/clear only when not pinned; selecting a commit in the lens pins; closing the lens unpins. Still pure screen layer, DOM-nodes only, print unaffected.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG, inline CSS + the merged lens `<script>` (f-string: braces doubled; regex backslash as `\\`).

## Global Constraints
- Python 3.13+, uv. TDD.
- f-string: every literal CSS/JS `{`/`}` doubled; the `slugsOf` regex must be `/\\s+/` (double backslash) — `\s` is an invalid escape in the non-raw f-string.
- No `innerHTML`/HTML sinks (unchanged).
- Print/no-JS: the lens stays JS-only and `@media print` keeps hiding `.commit-lens`/`.lane-hit`; absolute positioning has no print effect.
- The temporary `[lens]` `console.log`s stay for now (still feel-testing); they'll be stripped in the pre-merge cleanup task, not here.
- Pre-commit reformat → `git add -u` and re-commit. Voice rules on commits.

---

### Task 1: Position the lens as an overlay below the clicked row

**Files:** Modify `antiquarian/render.py` — the `.atom`/`.commit-lens` CSS + the `openLens` insertion/positioning. Test: `tests/test_lens_markup.py` (extend).

**Interfaces:** Consumes the existing `.lane-hit[data-lane]` rects (for the row's screen rect) and the swimlane `.atom`. Produces: the lens is appended *inside* the swimlane atom and absolutely positioned with its top at the clicked lane's bottom edge.

- [ ] **Step 1: Failing test (extend tests/test_lens_markup.py)**
```python
def test_lens_css_is_absolute_overlay():
    html = _page()
    # the lens overlays (absolute), and the atom is a positioning context
    seg = html[html.index(".commit-lens {{") if ".commit-lens {{" in html else html.index(".commit-lens"):]
    assert "position: absolute" in html
    assert ".atom {" in html and "position: relative" in html
```
(Adjust the slice to just assert `"position: absolute"` appears in the `.commit-lens` rule and `.atom` has `position: relative` — keep it a simple substring check on the rendered HTML.)

- [ ] **Step 2: Run → fail.** `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_lens_markup.py -q`

- [ ] **Step 3: CSS — relative atom + absolute lens overlay.** In the page `<style>`: add `position: relative;` to the existing `.atom {{ … }}` rule. Change `.commit-lens` to an absolute overlay:
```python
    .commit-lens {{
      position: absolute; z-index: 20; left: 2.5rem; right: 2.5rem;
      font-family: var(--serif); border: 1px solid var(--rule); background: var(--paper);
      box-shadow: 0 6px 18px rgba(31, 26, 20, 0.28);
      padding: 0.6rem 0.9rem;
    }}
```
(Drop the old `margin: 0.5rem 0 1.5rem;` block-flow margins; it's positioned now. Keep the inner `.commit-lens-head/-strip/-dot/-detail` rules.)

- [ ] **Step 4: JS — append inside the atom + compute top.** In `openLens`, replace the insertion (`var atom = svg.closest('.atom') || svg.parentNode; atom.parentNode.insertBefore(lensEl, atom.nextSibling);`) with: append the lens INTO the atom and position it under the clicked lane's row:
```javascript
      var atomEl = svg.closest('.atom') || svg.parentNode;
      atomEl.appendChild(lensEl);
      var laneHit = svg.querySelector('.lane-hit[data-lane="' + lane + '"]');
      if (laneHit) {{
        var aRect = atomEl.getBoundingClientRect();
        var rRect = laneHit.getBoundingClientRect();
        lensEl.style.top = (rRect.bottom - aRect.top) + 'px';
      }}
```
(Place this where the lens is inserted, after building head/strip/detail; the preselect `.click()` block stays after it.)

- [ ] **Step 5: Run tests + import-clean + full suite + commit.**
```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_lens_markup.py -q
uv run python -W error::SyntaxWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
uv run pre-commit run --files antiquarian/render.py tests/test_lens_markup.py
git add antiquarian/render.py tests/test_lens_markup.py
git commit -m "feat(render): position the commit lens as an overlay below the clicked row (#143)"
```

---

### Task 2: Merge hover + lens scripts; pin the footprint while the lens is open

**Files:** Modify `antiquarian/render.py` — remove the separate co-arc hover `<script>` (the `/* Honest co-arc commit highlight (#119) … */` IIFE); fold its hover wiring into the lens `<script>` with shared `paint`/`unpaint`/`pinned`. Test: `tests/test_lens_markup.py`/`tests/test_arc_overlay.py` (the co-arc hover scaffold test moves/stays green).

**Interfaces:** Produces: one script owns the footprint. `paint(bubble)` dims the svg + lights co-arc bubbles (neon fill + grow) by shared arc slug; `unpaint()` clears. A module-scoped `pinned` (bubble or null). Hover handlers paint/unpaint only when `!pinned`. Selecting a lens dot sets `pinned` and paints (held); `clearLens()` unpins + unpaints.

- [ ] **Step 1: Failing test.** Add to `tests/test_lens_markup.py`:
```python
def test_single_merged_highlight_script_has_pin():
    html = _page()
    # the footprint highlight + lens now share one script with a pin concept
    assert "pinned" in html          # the pin flag exists in the script
    assert "function paint" in html  # shared paint fn
    # the old standalone co-arc IIFE marker should be gone (merged)
    assert "Honest co-arc commit highlight" not in html
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Remove the separate co-arc `<script>`.** Delete the entire `<script>` block whose comment begins `/* Honest co-arc commit highlight (#119) …`(the IIFE that wires `mouseenter`/`mouseleave` to add/remove `commit-xref` + `xref-dim`). Its behaviour is re-created in the lens script below.

- [ ] **Step 4: Add shared `paint`/`unpaint`/`pinned` + hover wiring to the lens script.** Inside the lens IIFE (which already has `svg`, `bubbleEls`), add near the top (after `clearLens` is defined, or before it — `pinned` must be in scope for both):
```javascript
    var pinned = null;
    function slugsOf(b) {{
      var v = (b.getAttribute('data-arcs') || '').trim();
      return v ? v.split(/\\s+/) : [];
    }}
    function paint(b) {{
      var slugs = slugsOf(b); if (!slugs.length) return;
      var color = b.getAttribute('data-arc-color');
      svg.classList.add('xref-dim');
      svg.querySelectorAll('.commit-bubble').forEach(function (o) {{
        var os = slugsOf(o);
        for (var i = 0; i < slugs.length; i++) {{
          if (os.indexOf(slugs[i]) !== -1) {{ o.classList.add('commit-xref'); if (color) o.style.fill = color; break; }}
        }}
      }});
    }}
    function unpaint() {{
      svg.classList.remove('xref-dim');
      svg.querySelectorAll('.commit-bubble.commit-xref').forEach(function (o) {{ o.classList.remove('commit-xref'); o.style.fill = ''; }});
    }}
```
Update `clearLens()` so it unpins + unpaints (replace its inline class-clearing with the shared call):
```javascript
    function clearLens() {{
      if (lensEl) {{ lensEl.remove(); lensEl = null; }}
      pinned = null;
      unpaint();
    }}
```
Wire hovers (re-creating the removed co-arc script), gated by `pinned`:
```javascript
    bubbleEls.forEach(function (b) {{
      b.addEventListener('mouseenter', function () {{ if (!pinned) paint(b); }});
      b.addEventListener('mouseleave', function () {{ if (!pinned) unpaint(); }});
    }});
```
In the **dot-select handler**, replace the manual class-clear + `b.dispatchEvent(new MouseEvent('mouseenter'))` with the shared, pinned paint:
```javascript
          pinned = b;
          unpaint();
          paint(b);
```
(So selecting a commit holds its footprint; subsequent hovers are inert until ✕/new region/new selection. Re-selecting another dot re-pins to that commit.)

- [ ] **Step 5: Run tests + import-clean + full suite + commit.**
```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_lens_markup.py tests/test_arc_overlay.py -q
uv run python -W error::SyntaxWarning -W error::DeprecationWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
uv run pre-commit run --files antiquarian/render.py tests/test_lens_markup.py
git add antiquarian/render.py tests/test_lens_markup.py
git commit -m "feat(render): pin the arc footprint while the lens is open; merge hover+lens scripts (#143)"
```

---

### Task 3: Validate + feel-test + update #146 (no new code)

- [ ] Re-render httpx; confirm one merged script (`"Honest co-arc commit highlight" not in html`), `position: absolute` lens, import clean.
- [ ] **rodney feel-test:** dispatch a click on a decisive bubble; confirm (a) the lens appears positioned **below that row** (its `style.top` ≈ the lane's bottom, not at the swimlane bottom), and (b) the selected commit's footprint is lit AND **stays lit** when a synthetic `mouseleave` is dispatched on a bubble (pinned). Then ✕ → footprint clears. Screenshot the open, pinned lens; commit under `docs/evolution/`.
- [ ] Push (updates #146); comment the screenshot + "lens now drops below the clicked row and holds the footprint while open." Present to Tom — still draft.

## Self-Review
- Coverage: overlay-below-row positioning; merged single highlight script; pinned footprint held while open; hover inert while pinned; ✕ clears. ✓
- Honesty/print/no-JS: unchanged (JS-only overlay; real marks; print hides). ✓
- f-string braces doubled; `/\\s+/` double-backslash. ✓
- The merge removes the duplicate hover script (no double-wiring of mouseenter). ✓
