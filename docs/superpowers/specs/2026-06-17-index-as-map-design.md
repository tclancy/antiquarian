# Design: the broadsheet index as an orientation map

- **Date:** 2026-06-17
- **Issues:** #112 (arcs-at-scale layout — research → implementation), #119 (floating arcs panel + cross-atom highlight), #121 (files-surveyed annotations vs story-page sidebar)
- **Status:** approved (brainstorm), pending implementation plan
- **Companion canon:** [`docs/visualizing-at-scale.md`](../../visualizing-at-scale.md) (the six information-design principles), [`docs/visual-vocabulary.md`](../../visual-vocabulary.md) (the aesthetic commitments)

## Why

Reviewing the httpx POC (#95) exposed three heavy sections on the broadsheet
index that don't hold at scale. Two have been fixed; one remains:

- **Contributors swimlane** ("Hands that touched the work") — fixed in #118 (ranked + folded tail).
- **Files surveyed** — fixed in #108/#109 (`file_tree.py`: nested collapse + live search).
- **Named arcs** ("The named arcs of the work") — still a one-row-per-arc stacked SVG: **38px × 202 arcs ≈ 7,700px** for httpx. It is the last flat wall.

Three issues converge on the arcs section, and treating them separately risks
rework, so they are scoped together here:

- #119 wants to *float* the arcs band so a reader can hold it in view against
  the contributor scatter ~20,000px away. **You cannot float a 7,700px panel** —
  the float presupposes a *compact* arcs representation, which is exactly #112's
  deliverable. #112 → #119.
- #121 asks whether the index keeps per-file prose or becomes a pure *map*. That
  is a claim about the index's **job**, which #119/#112 reshape. Deciding #121 in
  isolation, then reshaping the index, would redo its information architecture.

## Decisions (settled in brainstorm)

1. **On screen, the index is an orientation map, not a reading document.** It is
   scanned and navigated *from*; heavy detail is one deliberate interaction away.
2. **"Map" means compact-by-default with disclosure *in place* — full detail stays
   in the index DOM, just visually folded.** Detail is *not* moved to a separate
   page. This is forced by the print-first canon (#40) and the "keep every name in
   the DOM" rule set on #108: print, in-page search, and SEO all depend on the
   full data remaining present. Same pattern the file tree and swimlane tail
   already use — collapsed on screen, expanded on paper.
3. **Named arcs become a packed density timeline** on the shared absolute spine
   (option A of three considered; see Appendix). It is the only representation
   short enough to float, and the truest orientation map.
4. **#121 = B + a glyph.** Add a directory-navigation sidebar to the story pages
   (reusing `file_tree.py`), drop the duplicate per-file prose sentence from the
   index, and keep a single **age-cohort glyph** per file in the index as a faint
   signal.
5. **Ship in four sequenced PRs** (below), each independently shippable, each
   print-degrading and TDD'd.

## Architecture

### PR1 — Packed density timeline (`arc_layout.py` + render)

A new **pure** module `antiquarian/arc_layout.py`, mirroring `file_tree.py`'s
split (layout-logic separate from rendering; principle 5):

- **in:** the arcs list (each arc carries `name`, `file_path`, `arc_number`, and
  its `commits` with timestamps) + the absolute spine from `build_absolute_scale`.
- **out:** a list of **rows**, each row a list of placed arc-intervals
  (`{arc, x_start, x_end}` in spine pixels). No HTML, no SVG.
- **algorithm — greedy interval lane-packing:** sort arcs by start time; for each
  arc, place it in the first row whose last interval ends before this arc's start
  (minus a small pixel gap so adjacent lozenges read as separate); else open a new
  row. This is the classic activity-selection packing — deterministic, O(n log n).
- **invariants (the test surface):** every arc is placed exactly once; no two
  intervals overlap within a row; rows are produced in a deterministic order; an
  empty arcs list yields no rows; a single arc yields one row.

`render.py` walks the rows and draws **unlabeled lozenges** on `build_absolute_scale`
(same spine as the swimlane and the old band). Identity is progressive disclosure:

- hover → SVG `<title>` with the arc name + decisive-commit count (already present
  on the current band's commit ticks);
- the **full per-arc list** (arc number, name, file, commit ticks) is kept in a
  folded `<details>` beneath the timeline — so search, print, and the in-DOM rule
  all still hold.

The lozenge marks carry real signal on their own: *when* arcs clustered, *where*
the record went dormant (the existing dormancy hatch is preserved under the
timeline). Lozenge fill stays restrained (uniform ink, or the arc-color ramp only
when it aids reading — eraser test applies).

This PR replaces `render_arc_band`'s stacked-row body with the packed timeline.
It **is** #112's implementation; the research deliverable is this section.

### PR2 — Sticky float (#119 phase 1)

Because the timeline is now wide-and-short, it floats as a **sticky top strip**
(`position: sticky; top: 0`) that pins while the reader is scrolled through the
contributors + arcs region, then releases. It is registered to the **same spine**,
so arc columns line up vertically with contributor columns — the cross-reference
#119 is about.

- HTML index only. **Print degrades** to: rendered inline at the top once, no
  sticky, no float (a `@media print` rule, as with the file tree / swimlane tail).
- No-JS: `position: sticky` is pure CSS; the strip still pins without script.

### PR3 — Cross-atom highlight (#119 phase 2)

Hover a contributor's commit bubble in the swimlane → light the matching arc
lozenge(s) in the timeline, and vice versa. The join is **already materialized**:
each arc carries its commit list (`arc["commits"]`), each commit the arcs it
belongs to (`render.py`: `decisive = bool(c["arcs"])`); the key is the commit SHA.
So this is rendering + interaction (data-attributes keyed by SHA + a small vanilla
script), not a data-model change.

- Print / no-JS: no hover; both atoms render statically (lossless).

### PR4 — Story-page sidebar + index glyph + prose removal (#121)

- **Sidebar:** the story-page template (`templates/story_page.html`) gains a
  directory-navigation sidebar built by **reusing `file_tree.py`** — siblings of
  the current file + parent (`..`) navigation, so a reader can walk the tree from
  any story page. The index thus becomes a *map*, relieved of carrying prose.
- **Index glyph:** each file leaf in the index tree gains one **age-cohort glyph**
  — a small mark whose shade maps to the era the file entered the record (bucketed
  on the same spine eras), derived from existing `file_lifespans` first-commit
  data. One mark, not a sentence (Tufte: earn the ink). Age-cohort is the v1
  encoding (most aligned with the "story over time" ethos); churn was considered
  as an alternative and can be swapped in one place if it reads better.
- **Prose removal:** the per-file description sentence is dropped from the index
  (it fails the eraser test — it duplicates the story page's own Origin line). The
  full prose remains on the story page.
- Print: sidebar degrades to a plain breadcrumb or is dropped; glyph prints as-is.

## Testing

- **Pure modules carry the heavy coverage** (principle 5): `arc_layout.py` —
  lane-packing invariants across flat / dense / sparse / single / empty inputs;
  `file_tree.py` reuse for the sidebar — sibling + parent derivation.
- **Render assertions** (same shape as #108's `test_file_index.py`): lozenge count
  equals arc count; lozenges register to the spine; the folded full-list `<details>`
  is present; sticky CSS present; `@media print` forces the timeline inline/open
  and the file tree/sidebar expanded; cross-highlight data-attributes keyed by SHA.
- TDD throughout (red → green), per the project's iron law.

## Print degradation (the through-line)

Every phase must survive print as a complete static view (principle 3):

| Screen | Print |
| --- | --- |
| Packed timeline + folded full-arc list | Timeline + full list expanded |
| Sticky-floating strip | Inline at top, no float |
| Hover cross-highlight | Static; both atoms fully drawn |
| Story-page sidebar | Breadcrumb or dropped |

## Out of scope (YAGNI)

- Single-child path compression in the file tree (already deferred from #108).
- Per-arc labels in the density timeline — identity is hover + the folded list;
  labelling 202 lozenges would re-create the wall.
- Churn glyph (age-cohort ships first; churn is the documented fallback).
- Any interactive feature on the **SVG broadsheet atoms** themselves — interactivity
  lives in the HTML wrapper only (#40).

## Appendix — arc-layout options considered

- **A. Packed density timeline (chosen).** All arcs on one spine, lane-packed to
  ~20 rows; the only option short enough to float; truest map.
- **B. Grouped small-multiples** (by file/epoch, one sparkline per group). Scannable
  but taller; less suited to floating.
- **C. Ranked top-N + folded tail** (the #118 swimlane pattern). Least new design,
  most consistent — but still a tall list; doesn't float.
