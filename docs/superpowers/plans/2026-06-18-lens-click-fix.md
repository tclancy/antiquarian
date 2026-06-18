# Commit lens — click a commit opens the panel (not navigate)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. `- [ ]` checkboxes.

**Goal:** Feel-test fix on the Phase-1 lens (#146): clicking a commit bubble currently follows an `<a>` link to its story page — jarring. Make **clicking a commit open the lens, pre-selected on that commit**; the story-page link moves *into* the detail panel ("read the file's story →") alongside the existing PR/commit links. The empty-row-space click (via lane-hit) already works and stays.

**Architecture:** Drop the decisive-bubble `<a>`-wrap in `render_swimlane`; instead emit `data-story-url` on the bubble. Refactor the lens script so building the inset is a reusable `openLens(lane, centerX, preselectSha)`; both the lane-hit click and a new per-bubble click call it (bubble click passes its own sha to pre-select). The detail panel adds a story link from `data-story-url`. Pure screen layer; still DOM-nodes (no innerHTML).

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG, the existing lens `<script>` (f-string: braces doubled).

## Global Constraints
- Python 3.13+, uv. TDD.
- **No `innerHTML`** anywhere — the new story link is built with `createElement`/`textContent` like the others (untrusted-text XSS guard).
- f-string braces doubled (`{{`/`}}`); the lens script stays backslash-free.
- Print/no-JS unaffected (the lens is JS-only). Removing the `<a>`-wrap means no-JS users no longer navigate from a swimlane bubble — that's fine; story pages remain linked from the files-surveyed index.
- Pre-commit reformat → `git add -u` and re-commit. Voice rules on commits.

---

### Task 1: Drop the bubble `<a>`-wrap; emit `data-story-url`

**Files:** Modify `antiquarian/render.py` (`render_swimlane`, the circle/`<a>` block ~694-723); update `tests/test_arc_overlay.py` (the test that asserted the `<a>` wrap).

- [ ] **Step 1: Update the failing test.** In `tests/test_arc_overlay.py`, `test_decisive_bubble_links_to_story_when_page_exists` asserts `'<a href="stories/…">'` wraps the circle. Change it to assert the new contract: the story URL is on the bubble as `data-story-url` and there is **no** `<a>` wrap:
```python
def test_decisive_bubble_carries_story_url_not_link():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": "stories/httpx___client.py.html", "color": "#ff2d95"}}
    out = render_swimlane({"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [], arc_lookup=lookup)
    assert 'data-story-url="stories/httpx___client.py.html"' in out
    assert "<a href=" not in out  # no navigate-away wrap on the bubble
```
(Rename/replace the old `test_decisive_bubble_links_to_story_when_page_exists`.)

- [ ] **Step 2: Run → fail.** `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_overlay.py -q`

- [ ] **Step 3: Replace the `<a>`-wrap with a `data-story-url` attribute.** In `render_swimlane`, compute the story href as before but append it to `lens_attrs` instead of wrapping. Replace the block that builds `circle`, computes `href`, and does `parts.append(<a>…</a> if href else circle)` with:
```python
            story_href = next(
                (lookup[s]["story_href"] for s in slugs if lookup.get(s, {}).get("story_href")),
                None,
            )
            if story_href:
                lens_attrs += f' data-story-url="{_xml_escape(story_href)}"'
            circle = (
                f'<circle class="commit-bubble" data-arcs="{_xml_escape(" ".join(slugs))}"'
                f"{arc_color_attr}"
                f"{lens_attrs} "
                f'cx="{cx}" cy="{y}" r="{r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="0.8" opacity="0.88">'
                f"<title>{_xml_escape(title)}</title>"
                "</circle>"
            )
            parts.append(circle)
```
(Move the `story_href` computation ABOVE the `circle = (...)` so it's appended to `lens_attrs` first. Delete the old `href = next(...)` and the `<a>`-wrap `parts.append(...)`.) Update the `render_swimlane` docstring line that says bubbles "are wrapped in a `<a href=…>` link" → now carry `data-story-url`.

- [ ] **Step 4: Run new test + full suite + commit.**
```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_overlay.py -q
uv run pytest -q   # fix any other test asserting the swimlane <a> wrap; note it
uv run pre-commit run --files antiquarian/render.py tests/test_arc_overlay.py
git add antiquarian/render.py tests/test_arc_overlay.py
git commit -m "feat(render): swimlane commits carry data-story-url instead of an <a> wrap (#143)"
```

---

### Task 2: Bubble-click opens the lens pre-selected; story link in the panel

**Files:** Modify `antiquarian/render.py` — the lens `<script>` (factor `openLens`, add bubble click + preselect) and `showDetail` (add the story link). Test: `tests/test_lens_markup.py` (extend).

**Interfaces:** Consumes `data-lane`/`cx`/`data-sha`/`data-story-url` on bubbles + the existing lane-hit handler. Produces: clicking a `.commit-bubble` opens the lens for its lane centered on it and pre-selects that commit; the detail panel shows a "read the file's story →" link when `data-story-url` is present.

- [ ] **Step 1: Add the page-scaffold test (extend tests/test_lens_markup.py).** Assert the script wires bubble clicks + the story link:
```python
def test_lens_script_handles_bubble_click_and_story_link():
    html = _page()
    assert "data-story-url" in html  # script references the story link attr
    assert "commit-bubble" in html
```
(This is a light scaffold check; the real proof is the rodney feel-test in Task 3.)

- [ ] **Step 2: Refactor the lens script.** In the lens `<script>`, factor the inset-building body currently inside `hits.forEach(hit => hit.addEventListener('click', evt => {{ … }}))` into a function `openLens(lane, centerX, preselectSha)`. Concretely:
  - Define `function openLens(lane, centerX, preselectSha) {{ … }}` containing the existing build logic, where `lane`, the bubble set (`querySelectorAll('.commit-bubble[data-lane="'+lane+'"]')`), `centerX`, and the author come from params/lookup (read author from the lane-hit: `svg.querySelector('.lane-hit[data-lane="'+lane+'"]').getAttribute('data-author')`).
  - When building each dot, tag it so preselect can find it: `dot.dataset.sha = b.getAttribute('data-sha');` Keep the dot's click handler as-is (select + showDetail + dispatch mouseenter).
  - After appending all dots, if `preselectSha`, find `strip.querySelector('.commit-lens-dot[data-sha="'+preselectSha+'"]')` and call `.click()` on it (so the panel opens already showing that commit).
  - Lane-hit handler becomes: `openLens(hit.getAttribute('data-lane'), svgX(evt), null);` (preceded by `clearLens()`).
  - **Add bubble clicks:** after wiring the hits, add
    ```javascript
    svg.querySelectorAll('.commit-bubble').forEach(function (b) {{
      b.addEventListener('click', function (evt) {{
        evt.stopPropagation();
        clearLens();
        openLens(b.getAttribute('data-lane'), parseFloat(b.getAttribute('cx')), b.getAttribute('data-sha'));
      }});
    }});
    ```
  (`openLens` must call `clearLens()` itself OR callers call it first — keep one consistent place; the brief has callers call `clearLens()` then `openLens`. Ensure no double-clear bug.)

- [ ] **Step 3: Add the story link to `showDetail`.** In `showDetail(panel, b)`, after the PR/commit link loop, append a story link when present (DOM nodes, not innerHTML):
```javascript
      var story = b.getAttribute('data-story-url');
      if (story) {{
        var sa = document.createElement('a');
        sa.href = story; sa.textContent = "read the file's story →";
        panel.appendChild(sa);
      }}
```

- [ ] **Step 4: Run tests + import-clean + full suite + commit.**
```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_lens_markup.py -q
uv run python -W error::SyntaxWarning -W error::DeprecationWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
uv run pre-commit run --files antiquarian/render.py tests/test_lens_markup.py
git add antiquarian/render.py tests/test_lens_markup.py
git commit -m "feat(render): click a commit to open the lens pre-selected; story link in the panel (#143)"
```

---

### Task 3: Validate + feel-test + update #146 (no new code)

- [ ] Re-render httpx; confirm no `<a href="stories` wrapping bubbles, `data-story-url` present, import clean.
- [ ] **rodney feel-test:** dispatch a `click` directly on a decisive `.commit-bubble`; confirm it does NOT navigate, the lens opens **with that commit already selected** (detail panel populated), and the panel shows commit/PR + "read the file's story →" links. Also confirm the empty-row-space (lane-hit) click still works. Screenshot the bubble-click-opened lens, commit under `docs/evolution/`.
- [ ] Push; the draft PR #146 updates automatically. Comment the new screenshot + "fixed: clicking a commit now opens the panel (pre-selected); story link moved into the panel." Present to Tom — still draft, his call to merge.

## Self-Review
- Coverage: drop navigate-away (`<a>`→`data-story-url`); bubble-click opens+preselects; story link in panel; lane-hit still works. ✓
- No innerHTML; DOM nodes for the new link. ✓
- f-string braces doubled; no backslashes. ✓
- Print/no-JS: lens still JS-only; story pages still reachable via files index. ✓
