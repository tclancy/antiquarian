# Commit lens — Phase 1: click-to-pin zoom inset + detail panel

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. `- [ ]` checkboxes.

**Goal:** The micro half of the commit lens (#143). Click a region of a contributor's timeline row → a **pinned zoomed inset** appears inline below the swimlane showing that contributor's commits near the click, spread far enough apart to pick individually. Selecting a commit fills a **detail panel** (PR body first, else commit message, ≤50 words → ellipsis → links to both the PR and the commit) and lights that commit's arc footprint in the swimlane above (reusing the Phase-2 dim+neon-grow). Dismiss with ✕. Spec: `docs/superpowers/specs/2026-06-18-commit-lens-design.md`.

**Architecture:** Server-side, `render_data` enriches each swimlane commit with `detail` (PR-first, pre-truncated to ≤50 words), `detail_source`, `pr_url`, `commit_url` (URLs built from the repo's GitHub remote). `render_swimlane` emits these as `data-*` on each bubble, tags bubbles with `data-lane`, and lays a transparent `<rect class="lane-hit">` over each row as the click target. A vanilla `<script>` builds the inset client-side from the clicked lane's bubbles. Pure screen enhancement — print/no-JS show the static swimlane untouched.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG, inline CSS + one vanilla `<script>` (f-string: braces doubled).

## Global Constraints
- Python 3.13+, uv. TDD.
- **Two-surface / honesty:** the lens is a pure JS/HTML layer over the static swimlane. Print + no-JS are unaffected (no inset, no lane-hit behaviour). Everything shown is a real commit / real artifact (the detail quotes the real PR body or commit message and links to the source).
- **Detail is pre-truncated server-side (≤50 words)** so the page doesn't embed full PR bodies for every commit (bounded weight). Tunable constant `DETAIL_WORD_CAP = 50`.
- Detail source priority: **PR body if present, else commit message** (label which).
- f-string: literal CSS/JS braces doubled (`{{`/`}}`); any JS regex uses `\\` for a literal backslash.
- This is a first cut for feel-test; the adaptive-window heuristic + visual polish will tune by eye. Pre-commit reformat → `git add -u` and re-commit. Voice rules on commits.

## Out of scope
- Mobile/narrow (decision #5: way out of scope).
- The story-page sidebar (#145) and masthead timeline (#136).

---

### Task 1: Enrich commit data — detail (PR-first, ≤50 words) + URLs

**Files:**
- Modify: `antiquarian/render_data.py` — `_Commit` gains `message`/`pr_body`; `_load_commits` loads them; a pure `_truncate_words` helper; `_build_swimlane(commits, base_url)` emits `detail`/`detail_source`/`pr_url`/`commit_url`; `extract_render_data` computes `base_url` via `detect_github_repo`.
- Test: `tests/test_commit_detail.py` (new).

**Interfaces:**
- Consumes: `detect_github_repo` (from `antiquarian.prs`), cache columns `message`/`pr_body`/`pr_number`.
- Produces: each swimlane commit dict gains `detail` (str, ≤`DETAIL_WORD_CAP` words + "…" if cut), `detail_source` (`"pr"` | `"commit"`), `pr_url` (str|None), `commit_url` (str|None). `_truncate_words(text, n) -> str` is pure/testable.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_commit_detail.py
"""Tests for commit detail enrichment feeding the commit lens (#143)."""
from __future__ import annotations
from antiquarian.render_data import _truncate_words


def test_truncate_short_text_unchanged():
    assert _truncate_words("a b c", 5) == "a b c"


def test_truncate_long_text_adds_ellipsis():
    out = _truncate_words("one two three four five six", 3)
    assert out == "one two three…"


def test_truncate_collapses_whitespace():
    assert _truncate_words("  a\n\n  b   c ", 10) == "a b c"


def test_truncate_empty():
    assert _truncate_words("", 5) == "" and _truncate_words(None, 5) == ""
```

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError`/`ImportError` for `_truncate_words`).
Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_commit_detail.py -q`

- [ ] **Step 3: Add `_truncate_words` + `_Commit` fields + load**

In `render_data.py`, add the pure helper near the top-level helpers:

```python
DETAIL_WORD_CAP = 50


def _truncate_words(text: str | None, n: int = DETAIL_WORD_CAP) -> str:
    """Collapse whitespace and keep at most ``n`` words, adding an ellipsis if cut."""
    words = (text or "").split()
    if not words:
        return ""
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "…"
```

Add to `_Commit` (after `message_subject`): `message: str = ""` and (after `pr_number`): `pr_body: str | None = None`.

In `_load_commits`, where the `_Commit(...)` is constructed, add `message=msg,` and `pr_body=row["pr_body"],` (the row already exposes `message` and `pr_body` per the cache schema; `msg` is already computed from `row["message"]`).

- [ ] **Step 4: Thread `base_url` + emit detail/urls in `_build_swimlane`**

Change the signature to `def _build_swimlane(commits: list[_Commit], base_url: str | None = None) -> dict:`. In the per-commit dict, add:

```python
                "message": c.message,
                "pr_body": c.pr_body,
                "detail_source": "pr" if c.pr_body else "commit",
                "detail": _truncate_words(c.pr_body or c.message or c.message_subject),
                "pr_url": (f"{base_url}/pull/{c.pr_number}" if base_url and c.pr_number else None),
                "commit_url": (f"{base_url}/commit/{c.sha}" if base_url else None),
```

In `extract_render_data(repo_path)`, before building the bundle, compute the base URL and pass it:

```python
    gh = detect_github_repo(repo_path)
    base_url = f"https://github.com/{gh[0]}/{gh[1]}" if gh else None
```
and change the call to `"swimlane": _build_swimlane(commits, base_url),`. Add the import `from antiquarian.prs import detect_github_repo` if not already present.

- [ ] **Step 5: Add an integration test (tests/test_commit_detail.py)**

```python
from pathlib import Path  # noqa: E402
from antiquarian.render_data import extract_render_data  # noqa: E402


def test_swimlane_commits_carry_detail_fields(seeded_repo: Path):
    data = extract_render_data(seeded_repo)
    commits = [c for lane in data["swimlane"]["lanes"] for c in lane["commits"]]
    assert commits, "fixture should have commits"
    for c in commits:
        assert "detail" in c and "detail_source" in c
        assert c["detail_source"] in ("pr", "commit")
        assert "pr_url" in c and "commit_url" in c
```
(Reuse the `seeded_repo` fixture from the existing test suite — match how `tests/test_render.py` imports/uses it; if it's a conftest fixture it's available directly.)

- [ ] **Step 6: Run new tests + full suite + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_commit_detail.py -q
uv run pytest -q
uv run pre-commit run --files antiquarian/render_data.py tests/test_commit_detail.py
git add antiquarian/render_data.py tests/test_commit_detail.py
git commit -m "feat(render-data): per-commit detail (PR-first, <=50 words) + PR/commit URLs for the lens (#143)"
```

---

### Task 2: Emit lens data-attributes + lane-hit click targets in `render_swimlane`

**Files:**
- Modify: `antiquarian/render.py` — in `render_swimlane`, tag each commit `<circle>` with `data-lane`, `data-date`, `data-detail`, `data-detail-source`, `data-pr-url`, `data-commit-url` (in addition to the existing `data-sha`? — note: bubbles currently carry `data-arcs`/`data-arc-color` but NOT `data-sha`; add `data-sha` too). Emit a transparent `<rect class="lane-hit" data-lane data-author>` per row as the click target.
- Test: `tests/test_arc_overlay.py` (extend) or a new `tests/test_lens_markup.py`.

**Interfaces:**
- Consumes: the Task-1 commit fields (`detail`, `detail_source`, `pr_url`, `commit_url`, `date`, `sha`).
- Produces: each commit `<circle>` carries `data-sha`, `data-lane="<i>"`, `data-date`, `data-detail`, `data-detail-source`, `data-pr-url` (omit attr if None), `data-commit-url`. Each row has a `<rect class="lane-hit" data-lane="<i>" data-author="<name>" ...fill="transparent">` spanning the chart width, drawn **before** the bubbles so bubbles stay clickable above it.

- [ ] **Step 1: Write failing tests** (new `tests/test_lens_markup.py`)

```python
"""Lens markup: per-bubble data-* + lane-hit click targets (#143)."""
from __future__ import annotations
from antiquarian.render import render_swimlane

_TL = {"full_span": {"start": "2020-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00", "days": 2192}, "active_windows": [], "gaps": []}


def _commit(sha="abc123", **kw):
    base = {"short_sha": sha, "sha": sha, "timestamp": "2021-06-01T00:00:00+00:00", "date": "2021-06-01",
            "additions": 3, "deletions": 2, "subject": "s", "arcs": [], "files_changed": [],
            "detail": "did a thing", "detail_source": "commit", "pr_url": None, "commit_url": "https://x/commit/abc123"}
    base.update(kw); return base


def _lane(commits, author="Ada"):
    return {"author": author, "email": "a@b.c", "commit_count": len(commits), "total_loc": 5, "commits": commits}


def test_bubble_carries_lens_data():
    out = render_swimlane({"lanes": [_lane([_commit()])]}, _TL, [])
    assert 'data-sha="abc123"' in out
    assert 'data-lane="0"' in out
    assert 'data-date="2021-06-01"' in out
    assert 'data-detail="did a thing"' in out
    assert 'data-commit-url="https://x/commit/abc123"' in out


def test_lane_hit_rect_present():
    out = render_swimlane({"lanes": [_lane([_commit()], author="Ada")]}, _TL, [])
    assert 'class="lane-hit"' in out
    assert 'data-lane="0"' in out
    assert 'data-author="Ada"' in out


def test_no_pr_url_attr_when_absent():
    out = render_swimlane({"lanes": [_lane([_commit(pr_url=None)])]}, _TL, [])
    assert "data-pr-url=" not in out
```

- [ ] **Step 2: Run → fail.** `export PATH=... && uv run pytest tests/test_lens_markup.py -q`

- [ ] **Step 3: Emit the lane-hit rect + bubble data-attrs**

In `render_swimlane`, inside the per-lane loop (you have the lane index `i` and `y`/`row_h`), **before** drawing the lane's commit circles, append a transparent hit rect:

```python
        parts.append(
            f'<rect class="lane-hit" data-lane="{i}" data-author="{_xml_escape(lane["author"])}" '
            f'x="{margin_left}" y="{margin_top + i * row_h}" width="{chart_w}" height="{row_h}" '
            f'fill="transparent" pointer-events="all"/>'
        )
```
(Confirm the loop variable names by reading the function; mirror its existing `y`/`row_h`/`margin_top` usage.)

Then extend the commit `<circle>` open tag to include the lens attributes (keep the existing `class="commit-bubble"`, `data-arcs`, `data-arc-color`, `<title>`, `<a>`-wrap). Add, building each conditional attr so `None` ones are omitted:

```python
            lens_attrs = (
                f' data-sha="{_xml_escape(c["short_sha"])}" data-lane="{i}" '
                f'data-date="{_xml_escape(c.get("date") or "")}" '
                f'data-detail="{_xml_escape(c.get("detail") or "")}" '
                f'data-detail-source="{_xml_escape(c.get("detail_source") or "commit")}"'
            )
            if c.get("pr_url"):
                lens_attrs += f' data-pr-url="{_xml_escape(c["pr_url"])}"'
            if c.get("commit_url"):
                lens_attrs += f' data-commit-url="{_xml_escape(c["commit_url"])}"'
```
and splice `lens_attrs` into the `<circle ...>` open tag (e.g. right after `data-arcs="…"`). Keep everything else intact.

- [ ] **Step 4: Run new tests + full suite + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_lens_markup.py -q
uv run pytest -q   # update any swimlane test whose <circle …> anchor shifted, as before
uv run pre-commit run --files antiquarian/render.py tests/test_lens_markup.py
git add antiquarian/render.py tests/test_lens_markup.py
git commit -m "feat(render): lens data-attributes + per-row lane-hit click targets on the swimlane (#143)"
```

---

### Task 3: The lens itself — inset + detail panel (JS + CSS)

**Files:**
- Modify: `antiquarian/render.py` — add `.commit-lens` CSS and a `<script>` (after the existing co-arc script, before `</body>`).
- Test: `tests/test_lens_markup.py` (extend with page-level scaffold assertions).

**Interfaces:**
- Consumes: the `lane-hit` rects + bubble `data-*` from Task 2; the existing co-arc highlight (dispatch `mouseenter`/`mouseleave` on the real bubble to reuse the dim+neon-grow).
- Produces: clicking a `lane-hit` builds a pinned `<div class="commit-lens">` inserted after the swimlane atom; it shows the lane's ~`LENS_N` commits nearest the click, spread evenly, each selectable; selecting one fills the detail panel (detail text + source label + PR/commit links) and lights its arc footprint above; a ✕ dismisses it.

- [ ] **Step 1: Write the page-scaffold tests (extend tests/test_lens_markup.py)**

```python
from antiquarian.render import render_broadsheet  # noqa: E402

def _page():
    return render_broadsheet({
        "project": "p", "timeline": _TL, "todos": [],
        "swimlane": {"lanes": [_lane([_commit()])]},
        "arc_band": {"arc_count": 0, "arcs": []},
        "file_lifespans": [], "files": [], "generated_at": "2026-06-18",
    })

def test_lens_css_and_script_present():
    html = _page()
    assert ".commit-lens" in html
    assert "lane-hit" in html
    assert "commit-lens" in html  # script references the container class
    # print hides the lens
    print_block = html[html.index("@media print"):]
    assert "commit-lens" in print_block
```

- [ ] **Step 2: Run → the new test fails** (`.commit-lens` absent).

- [ ] **Step 3: Add the `.commit-lens` CSS**

In the page `<style>`, add (near the other atom CSS):

```python
    .lane-hit {{ cursor: zoom-in; }}
    .commit-lens {{
      font-family: var(--serif); border: 1px solid var(--rule); background: var(--paper-alt);
      margin: 0.5rem 0 1.5rem; padding: 0.6rem 0.9rem;
    }}
    .commit-lens-head {{ display: flex; justify-content: space-between; align-items: baseline; font-weight: 600; }}
    .commit-lens-close {{ cursor: pointer; color: var(--accent); border: none; background: none; font-size: 1rem; }}
    .commit-lens-strip {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0; }}
    .commit-lens-dot {{
      cursor: pointer; border: 1px solid var(--rule); background: var(--paper);
      border-radius: 4px; padding: 0.15rem 0.4rem; font-size: 0.75rem; font-variant-numeric: tabular-nums;
    }}
    .commit-lens-dot.sel {{ background: var(--accent); color: var(--paper); }}
    .commit-lens-detail {{ font-size: 0.85rem; min-height: 2.5em; border-top: 1px solid var(--rule); padding-top: 0.4rem; }}
    .commit-lens-detail a {{ color: var(--accent); margin-right: 0.8rem; }}
    @media print {{ .commit-lens, .lane-hit {{ display: none !important; }} }}
```

- [ ] **Step 4: Add the lens `<script>`**

After the existing co-arc `</script>`, before `</body>`, add (every brace doubled):

```python
  <script>
  /* Commit lens (#143): click a contributor's row region -> pinned zoom inset
     of that contributor's nearby commits; pick one -> detail panel (PR body or
     commit message, +links) and light its arc footprint above. Pure screen
     enhancement; print/no-JS show only the static swimlane. */
  (function () {{
    var LENS_N = 12;
    var first = document.querySelector('.commit-bubble');
    if (!first) return;
    var svg = first.closest('svg');
    var hits = svg.querySelectorAll('.lane-hit');
    if (!hits.length) return;
    var lensEl = null;

    function svgX(evt) {{
      var pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(svg.getScreenCTM().inverse()).x;
    }}
    function clearLens() {{
      if (lensEl) {{ lensEl.remove(); lensEl = null; }}
      svg.querySelectorAll('.commit-bubble.commit-xref').forEach(function (b) {{
        b.classList.remove('commit-xref'); b.style.fill = '';
      }});
      svg.classList.remove('xref-dim');
    }}
    function pick(bubbles, x) {{
      return bubbles
        .map(function (b) {{ return {{ b: b, d: Math.abs(parseFloat(b.getAttribute('cx')) - x) }}; }})
        .sort(function (p, q) {{ return p.d - q.d; }})
        .slice(0, LENS_N).map(function (p) {{ return p.b; }})
        .sort(function (a, c) {{ return parseFloat(a.getAttribute('cx')) - parseFloat(c.getAttribute('cx')); }});
    }}
    function showDetail(panel, b) {{
      var src = b.getAttribute('data-detail-source') === 'pr' ? 'PR' : 'commit';
      var html = '<em>' + src + ':</em> ' + (b.getAttribute('data-detail') || '(no message)') + '<br>';
      var pr = b.getAttribute('data-pr-url'); var cm = b.getAttribute('data-commit-url');
      if (pr) html += '<a href="' + pr + '" target="_blank" rel="noopener">view PR &rarr;</a>';
      if (cm) html += '<a href="' + cm + '" target="_blank" rel="noopener">view commit &rarr;</a>';
      panel.innerHTML = html;
    }}
    hits.forEach(function (hit) {{
      hit.addEventListener('click', function (evt) {{
        clearLens();
        var lane = hit.getAttribute('data-lane');
        var bubbles = Array.prototype.slice.call(svg.querySelectorAll('.commit-bubble[data-lane="' + lane + '"]'));
        if (!bubbles.length) return;
        var chosen = pick(bubbles, svgX(evt));
        lensEl = document.createElement('div');
        lensEl.className = 'commit-lens';
        var head = document.createElement('div'); head.className = 'commit-lens-head';
        head.innerHTML = '<span>' + (hit.getAttribute('data-author') || '') + ' &middot; ' + chosen.length + ' commits</span>';
        var close = document.createElement('button'); close.className = 'commit-lens-close'; close.textContent = '×';
        close.addEventListener('click', clearLens); head.appendChild(close);
        var strip = document.createElement('div'); strip.className = 'commit-lens-strip';
        var detail = document.createElement('div'); detail.className = 'commit-lens-detail';
        detail.textContent = 'Select a commit to see its story.';
        chosen.forEach(function (b) {{
          var dot = document.createElement('button'); dot.className = 'commit-lens-dot';
          dot.textContent = b.getAttribute('data-date') || b.getAttribute('data-sha');
          dot.addEventListener('click', function () {{
            strip.querySelectorAll('.sel').forEach(function (s) {{ s.classList.remove('sel'); }});
            dot.classList.add('sel');
            showDetail(detail, b);
            svg.querySelectorAll('.commit-bubble.commit-xref').forEach(function (x) {{ x.classList.remove('commit-xref'); x.style.fill=''; }});
            b.dispatchEvent(new MouseEvent('mouseenter'));
          }});
          strip.appendChild(dot);
        }});
        lensEl.appendChild(head); lensEl.appendChild(strip); lensEl.appendChild(detail);
        var atom = svg.closest('.atom') || svg.parentNode;
        atom.parentNode.insertBefore(lensEl, atom.nextSibling);
      }});
    }});
  }})();
  </script>
```

- [ ] **Step 5: Run tests + import-clean + full suite + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_lens_markup.py -q
uv run python -W error::SyntaxWarning -W error::DeprecationWarning -c "import antiquarian.render; print('import clean')"
uv run pytest -q
uv run pre-commit run --files antiquarian/render.py tests/test_lens_markup.py
git add antiquarian/render.py tests/test_lens_markup.py
git commit -m "feat(render): commit lens — click-to-pin zoom inset + detail panel (#143)"
```

---

### Task 4: Validate + feel-test + present (no new code)

- [ ] **Re-render** httpx; confirm `.commit-lens` CSS, `lane-hit` rects, `data-detail`/`data-commit-url` on bubbles.
- [ ] **Feel-test with rodney:** dispatch a `click` on a `.lane-hit` (synthesize an event with clientX over a dense part of a row); confirm a `.commit-lens` appears with dot buttons; click a dot; confirm the detail panel fills (detail + links) and the arc footprint lights above. Screenshot the open lens, **commit it under `docs/evolution/`**.
- [ ] **Present to Tom — do NOT auto-merge.** This is the big interactive first cut; expect feel-test iteration (window heuristic, inset density, dismiss). Flag known rough edges (adaptive window = nearest-12 for now; no click-away dismiss yet, ✕ only).

## Self-Review
- Coverage: data (detail PR-first ≤50w + URLs), markup (data-* + lane-hit), the inset+detail+macro-tie-in+dismiss; httpx feel-test. ✓
- Two-surface/honesty: lens is JS-only over the static swimlane; print hides it; quotes/links real artifacts. ✓
- Bounded weight: detail pre-truncated server-side. ✓
- f-string braces doubled; conditional `None` attrs omitted. ✓
- Known first-cut roughness (window heuristic; ✕-only dismiss) flagged for the feel-test, not hidden. ✓
