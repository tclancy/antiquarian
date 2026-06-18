# PR-B: Arc overlay on the commit timeline — links to detail + honest co-arc highlight

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make named arcs *meaningful in context* on the swimlane (the real commit timeline), the honest way: decisive (arc-named) commits link to their file's story page and name their arc on hover; hovering a decisive commit lights the **other real commits in the same arc(s)** across the swimlane — no band, just the actual marks. This is the validated "commit timeline + arcs-as-context + links to detail" direction (issues #112/#119; supersedes the band-highlight idea), and it fixes the dishonesty where a briefly-active contributor lit a multi-year span.

**Architecture:** `render_broadsheet` builds a small `arc_lookup` (`slug → {name, story_href}`) from the arc-band data + the set of story pages that exist, and passes it (optionally) to `render_swimlane`. Each commit bubble gains `class="commit-bubble"` and `data-arcs="<slug …>"`; decisive bubbles get the arc name appended to their tooltip and are wrapped in an `<a>` to their story page when one exists. A small inline script lights every bubble sharing an arc slug on hover. Everything degrades: links are static `<a>`, tooltips static `<title>`; only the highlight needs JS.

**Tech Stack:** Python 3.13, uv, pytest, hand-rolled SVG (`<a>`-wrapped `<circle>`), inline CSS + one small vanilla `<script>` in the page f-string.

## Global Constraints

- Python 3.13+, uv only. TDD (red → green).
- **Honesty (the whole point):** the cross-highlight joins on arc **slug** and lights only **real commit marks** — never a band, never a connecting span, never a synthesized interval. A contributor's single decisive commit lights only the handful of real commits in its arc.
- **Backward-compatible signature:** `arc_lookup` is an *optional* param (default `None` → current behavior + `data-arcs`), so existing `render_swimlane` callers/tests keep passing untouched.
- **Print-first / no-JS (#40):** story links are real `<a href>` (work on paper and without JS); arc names are static `<title>`; the hover highlight is a pure JS enhancement with an early return when absent.
- The page template is an f-string: literal CSS/JS braces doubled (`{{`/`}}`).
- Voice rules on commits/PR text. Pre-commit may reformat — `git add -u` and re-commit.

## Out of scope (follow-ups)
- The masthead commit-density timeline (#136) and the story-page gutter timeline (#138) — same theme, separate tickets.
- The standalone roster's fate (#137) — untouched here.
- A contributor-active-window bracket — more natural on the masthead (#136); not here.

---

### Task 1: Enrich swimlane bubbles — data-arcs, arc-name tooltip, story link

**Files:**
- Modify: `antiquarian/render.py` — `render_swimlane` signature (line ~549) + the commit-circle block (lines ~644–656); `render_broadsheet` (build `arc_lookup`, pass it at the call site ~1450).
- Test: `tests/test_arc_overlay.py` (new).

**Interfaces:**
- Consumes: existing `_xml_escape`, `_story_md_to_html_name`, `data["arc_band"]["arcs"]` (each arc has `slug`, `name`, `file_path`), the `linked` story set in `render_broadsheet`, per-commit `c["arcs"]` (list of arc slugs).
- Produces: `render_swimlane(swimlane, timeline, file_lifespans, arc_lookup: dict | None = None) -> str`. Each commit `<circle>` gains `class="commit-bubble"` and `data-arcs="<space-joined slugs>"`. When `arc_lookup` is provided and a commit is decisive: its `<title>` appends `· arc: <name>[; <name>…]`, and if any of its arcs has a `story_href`, the circle is wrapped in `<a href="<story_href>">…</a>`. `arc_lookup` maps `slug → {"name": str, "story_href": str | None}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_arc_overlay.py
"""Tests for the arc overlay on the swimlane (#119, PR-B).

Decisive commits link to their story page and name their arc on hover; bubbles
carry their arc slugs so the hover highlight (next task) can light real co-arc
commits. Honest: marks only, never a band.
"""

from __future__ import annotations

from antiquarian.render import render_swimlane

_TIMELINE = {
    "full_span": {"start": "2020-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00", "days": 2192},
    "active_windows": [], "gaps": [],
}


def _lane(commits):
    return {"author": "Ada", "commit_count": len(commits), "total_loc": 9, "email": "a@b.c", "commits": commits}


def _commit(sha, arcs, *, ts="2021-06-01T00:00:00+00:00", add=3, dele=2, subj="do a thing"):
    return {"short_sha": sha, "timestamp": ts, "additions": add, "deletions": dele, "subject": subj, "arcs": arcs}


def test_bubble_has_class_and_data_arcs():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [])
    assert 'class="commit-bubble"' in out
    assert 'data-arcs="transport-api"' in out


def test_non_decisive_bubble_has_empty_data_arcs():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", [])])]}, _TIMELINE, [])
    assert 'data-arcs=""' in out


def test_decisive_bubble_names_arc_in_tooltip_when_lookup_given():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": None}}
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [], arc_lookup=lookup
    )
    assert "Transport API rework" in out


def test_decisive_bubble_links_to_story_when_page_exists():
    lookup = {"transport-api": {"name": "Transport API rework", "story_href": "stories/httpx___client.py.html"}}
    out = render_swimlane(
        {"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [], arc_lookup=lookup
    )
    assert '<a href="stories/httpx___client.py.html">' in out
    assert "</a>" in out


def test_no_lookup_keeps_data_arcs_but_no_link():
    out = render_swimlane({"lanes": [_lane([_commit("abc123", ["transport-api"])])]}, _TIMELINE, [])
    assert 'data-arcs="transport-api"' in out
    assert "<a href=" not in out  # no lookup → no story link
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_overlay.py -q`
Expected: FAIL — no `commit-bubble` / `data-arcs` yet.

- [ ] **Step 3: Update `render_swimlane` signature**

Change the signature (line ~549) to add the optional param. Find:

```python
def render_swimlane(
    swimlane: dict,
    timeline: dict,
    file_lifespans: list[dict],
    lane_budget: int = SWIMLANE_LANE_BUDGET,
) -> str:
```

and add `arc_lookup` before `lane_budget`:

```python
def render_swimlane(
    swimlane: dict,
    timeline: dict,
    file_lifespans: list[dict],
    arc_lookup: dict | None = None,
    lane_budget: int = SWIMLANE_LANE_BUDGET,
) -> str:
```

(If the docstring lists params, add a line noting `arc_lookup` maps arc slug → `{"name", "story_href"}`; optional, drives the decisive-commit link + tooltip.)

- [ ] **Step 4: Enrich the commit-circle block**

Replace the circle block (lines ~644–656) with:

```python
        lookup = arc_lookup or {}
        for c in lane["commits"]:
            cx = margin_left + axis["scale"](_iso_to_dt(c["timestamp"]))
            diff = c["additions"] + c["deletions"]
            r = 4 + math.sqrt(diff / max_diff) * 14
            slugs = c["arcs"]
            decisive = bool(slugs)
            fill = PALETTE["accent"] if decisive else PALETTE["lane"]
            stroke = PALETTE["ink"] if decisive else PALETTE["rule"]
            title = c["short_sha"] + " — " + c["subject"] + " (" + str(diff) + " LoC)"
            arc_names = [lookup[s]["name"] for s in slugs if s in lookup]
            if arc_names:
                title += " · arc: " + "; ".join(arc_names)
            circle = (
                f'<circle class="commit-bubble" data-arcs="{_xml_escape(" ".join(slugs))}" '
                f'cx="{cx}" cy="{y}" r="{r}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="0.8" opacity="0.88">'
                f"<title>{_xml_escape(title)}</title>"
                "</circle>"
            )
            href = next(
                (lookup[s]["story_href"] for s in slugs if lookup.get(s, {}).get("story_href")),
                None,
            )
            parts.append(f'<a href="{_xml_escape(href)}">{circle}</a>' if href else circle)
```

- [ ] **Step 5: Build + pass `arc_lookup` in `render_broadsheet`**

In `render_broadsheet`, before the `atoms = {` block (~line 1448), build the lookup from the arc band and the `linked` story set. NOTE: `render_broadsheet` must compute `linked` the same way `render_page` does — the set of `<file with / → __>.md` names that have rendered pages. `render_broadsheet` receives `stories_with_pages`; use it:

```python
    linked = stories_with_pages or set()
    arc_lookup = {}
    for arc in data.get("arc_band", {}).get("arcs", []):
        md_name = arc["file_path"].replace("/", "__") + ".md"
        href = f"stories/{_story_md_to_html_name(md_name)}" if md_name in linked else None
        arc_lookup[arc["slug"]] = {"name": arc["name"], "story_href": href}
```

The `data.get("arc_band", {}).get("arcs", [])` guard is **mandatory** (matches the codebase's defensive pattern; some callers/tests omit `arc_band`).

Then change the swimlane atom line (~1450) to pass it:

```python
        "swimlane": render_swimlane(data["swimlane"], timeline, data["file_lifespans"], arc_lookup=arc_lookup),
```

(`render_broadsheet`'s signature already has `stories_with_pages`, line ~1429.)

- [ ] **Step 6: Run new tests + full suite**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_overlay.py -q   # expect 5 passed
uv run pytest -q   # full suite green; render_swimlane's new param is optional so existing callers are unaffected
```
**Known breakage to fix in this step:** `tests/test_render.py::TestSwimlane...::test_late_commit_lands_in_right_portion` (~line 986) matches `re.findall(r'<circle cx="([\d.]+)"', out)`. After this task, swimlane commit circles read `<circle class="commit-bubble" data-arcs="…" cx="…">`, so `cx` no longer follows `<circle ` directly and the regex would match only the *legend* circles (max cx≈640), failing `cxs[-1] > 700`. **Update that regex to** `r'<circle class="commit-bubble"[^>]*cx="([\d.]+)"'` so it targets commit bubbles. Run the full suite to catch any other circle-anchored swimlane test and fix the same way.

- [ ] **Step 7: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py tests/test_arc_overlay.py
git add antiquarian/render.py tests/test_arc_overlay.py
git commit -m "feat(render): link decisive commits to their story + name their arc on the swimlane (#119)"
```

---

### Task 2: Honest co-arc hover highlight (JS + CSS)

**Files:**
- Modify: `antiquarian/render.py` — add `.commit-xref` CSS (near the other atom CSS) and a small inline `<script>` before `</body>` (after the existing file-search script).
- Test: extend `tests/test_arc_overlay.py`.

**Interfaces:**
- Consumes: `class="commit-bubble"` + `data-arcs` from Task 1.
- Produces: hovering a `.commit-bubble` with a non-empty `data-arcs` adds `.commit-xref` to every `.commit-bubble` whose `data-arcs` shares at least one slug (real co-arc commits light up; bubbles with no arcs do nothing). Pure enhancement.

- [ ] **Step 1: Write the failing tests (append to tests/test_arc_overlay.py)**

```python
from antiquarian.render import render_broadsheet  # noqa: E402


def _page():
    data = {
        "project": "p", "timeline": _TIMELINE, "todos": [],
        "swimlane": {"lanes": [_lane([_commit("abc123", ["a-slug"]), _commit("def456", ["a-slug"])])]},
        "arc_band": {"arc_count": 1, "arcs": [
            {"arc_number": 1, "name": "An arc", "slug": "a-slug", "file_path": "a.py",
             "commits": [], "commit_count": 0, "datable_count": 0}]},
        "file_lifespans": [], "files": [], "generated_at": "2026-06-18",
    }
    return render_broadsheet(data)


def test_highlight_css_and_script_present():
    html = _page()
    assert ".commit-xref" in html
    assert "data-arcs" in html
    assert "<script" in html


def test_no_arc_commits_get_inert_empty_data_arcs():
    # a commit with no arcs renders an inert bubble (empty data-arcs → the
    # script's mouseenter guard skips it, so no mass-highlight is possible)
    data = {
        "project": "p", "timeline": _TIMELINE, "todos": [],
        "swimlane": {"lanes": [_lane([_commit("zzz999", [])])]},
        "arc_band": {"arc_count": 0, "arcs": []},
        "file_lifespans": [], "files": [], "generated_at": "2026-06-18",
    }
    html = render_broadsheet(data)
    assert 'data-arcs=""' in html
    assert html.strip().endswith("</html>")  # complete document, no crash
```

- [ ] **Step 2: Run to verify fail**

Run: `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run pytest tests/test_arc_overlay.py -q`
Expected: `test_highlight_css_and_script_present` FAILs (`.commit-xref` absent).

- [ ] **Step 3: Add the `.commit-xref` CSS**

In the page `<style>`, near the other interaction CSS (e.g. just before the `@media print` block), add:

```python
    /* Co-arc commit highlight, toggled by the overlay script on hover (#119). */
    .commit-xref {{ stroke-width: 2.4 !important; opacity: 1 !important; }}
```

- [ ] **Step 4: Add the overlay script**

After the existing file-search `</script>` (before `</body>`), add:

```python
  <script>
  /* Honest co-arc commit highlight (#119): hover a decisive commit, light the
     OTHER real commits in the same arc(s). Joins on arc slug; marks only, no
     band. Pure enhancement — no JS, no highlight; nothing else depends on it. */
  (function () {{
    var bubbles = Array.prototype.slice.call(document.querySelectorAll('.commit-bubble'));
    if (!bubbles.length) return;
    function slugsOf(b) {{
      var v = (b.getAttribute('data-arcs') || '').trim();
      return v ? v.split(/\\s+/) : [];
    }}
    bubbles.forEach(function (b) {{
      var slugs = slugsOf(b);
      if (!slugs.length) return;
      b.addEventListener('mouseenter', function () {{
        bubbles.forEach(function (o) {{
          var os = slugsOf(o);
          for (var i = 0; i < slugs.length; i++) {{
            if (os.indexOf(slugs[i]) !== -1) {{ o.classList.add('commit-xref'); break; }}
          }}
        }});
      }});
      b.addEventListener('mouseleave', function () {{
        bubbles.forEach(function (o) {{ o.classList.remove('commit-xref'); }});
      }});
    }});
  }})();
  </script>
```

**Transcribe `/\\s+/` exactly — keep the DOUBLE backslash.** The page template is a plain (non-raw) Python f-string, so `\s` would be an invalid escape sequence (SyntaxWarning on import, a hard error in a future Python). `\\s+` in the f-string renders as `\s+` in the emitted JS. Do not "simplify" it to `\s+`.

- [ ] **Step 5: Run new tests + full suite**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pytest tests/test_arc_overlay.py -q   # all green
uv run pytest -q
```

- [ ] **Step 6: pre-commit + commit**

```bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
uv run pre-commit run --files antiquarian/render.py tests/test_arc_overlay.py
git add antiquarian/render.py tests/test_arc_overlay.py
git commit -m "feat(render): honest co-arc commit highlight on hover — marks only, no band (#119)"
```

---

### Task 3: Validate at httpx scale + feel-test (no new code)

- [ ] **Step 1: Re-render** `export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" && uv run antiquarian render --repo ~/Documents/work/antiquarian-httpx/httpx-repo`

- [ ] **Step 2: Confirm structure**

```bash
python3 - <<'EOF'
import re
html = open("/Users/tom/Documents/work/antiquarian-httpx/httpx-repo/.antiquarian/render/index.html").read()
print("commit-bubbles:", html.count('class="commit-bubble"'))
print("decisive story links (<a href=stories in swimlane):", html.count('<a href="stories/'))
print("commit-xref css:", ".commit-xref" in html)
print("data-arcs present:", html.count("data-arcs=") > 0)
EOF
```

- [ ] **Step 3: Feel-test with rodney + report.** Confirm: hovering a decisive (accent) commit lights the *other* real commits in its arc (and only those — a brief contributor lights a few marks, not a span); decisive commits are clickable to their story page. Use rodney to dispatch a `mouseenter` on a `.commit-bubble[data-arcs]` and count `.commit-xref` (expect ≥1, and small). Screenshot the highlighted state. Report whether the interaction reads honestly. Do **not** commit here; do **not** auto-merge — this is interaction, present to Tom for the merge call.

---

## Self-Review
- **Spec coverage:** the validated PR-B direction — decisive commits link to detail (Task 1), name their arc (Task 1), and hovering lights real co-arc commits with no band (Task 2); httpx feel-test (Task 3). Masthead/gutter timelines (#136/#138) and roster fate (#137) explicitly deferred. ✓
- **Honesty:** highlight joins on arc slug and toggles a class on real `<circle>` marks only — no span/band/`<rect>`/connector. ✓
- **Backward-compat:** `arc_lookup` optional; existing `render_swimlane` callers unaffected; `data-arcs` always emitted but `<a>` only when a story page exists. ✓
- **Placeholders:** none — concrete code + anchors throughout. ✓
- **Print/no-JS:** story links are real `<a href>`; tooltips static; highlight is JS-only with early return. ✓
