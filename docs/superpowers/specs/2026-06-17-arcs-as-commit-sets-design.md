# Design: arcs as commit-sets, not spans (the named-arcs rethink)

- **Date:** 2026-06-17
- **Supersedes:** the arc-timeline / float / cross-highlight portions of `2026-06-17-index-as-map-design.md` (PR1 shipped #112/#130/#132; PR2 paused and now abandoned).
- **Grounded in:** `2026-06-17-second-eyes-arc-review.md` (the full data-modeling review — read it for the rationale; this doc is the decision + plan).
- **Fixes:** #133 (47.5% of arcs silently dropped).
- **Issues:** #112, #119, #121.

## The reframe (the one idea everything hangs on)

A named **arc** is an LLM-named **set of commits** at synthesis confidence — `name`, `file_path`, a prose `body`, and a handful of cited SHAs. **It is not a measured time interval.** Drawing it as a horizontal band asserts two things the data does not support: that the arc was active across the whole width (it is active only at its named commits, which may be two dots years apart), and that width is comparable between arcs (width is an artifact of which SHAs the prose cited). That is confabulated certainty in visual form — the exact thing the ethos forbids.

Two facts from the review make this concrete on httpx:
1. **96 of 202 arcs (47.5%) have zero datable commits** and are silently dropped by `pack_arcs` (#133) — the primary data, unmarked, gone.
2. Of the 106 datable arcs, many resolve to a **single SHA** (`MIN_LOZENGE_PX` exists for exactly this); the wide multi-year bands rest on as few as two LLM-cited commits.

**The data-model change:** stop computing or rendering a `(start, end)` span from an arc. The commits are real and datable; the span between them is not. If a "when" is wanted, it is the *set of commit timestamps plotted as points*, never a filled span. `date_range` (the LLM's parenthetical) is **prose metadata only**, never plotting coordinates — it is the lowest-trust relay artifact and the real timestamps outrank it.

## The chosen direction: one spine + overlay + roster

Promote the **swimlane to the single canonical time spine** (it already plots real commits at real positions). Express arcs two ways, both commit-mediated and honest:

1. **Overlay on the commits already plotted.** Arc-named ("decisive") commits keep their pigment outline (already implemented). Hovering an arc (in the roster) or a decisive commit **brackets the *set* of that arc's commits** through their real x-positions — a connector across real points, never a filled band. Arc-named commits authored by *tail* contributors (whose lane is folded) get a slim **"decisive commits" rail** beneath the axis, so no named commit is invisible.
2. **A first-class arc roster** beneath the spine: the current folded `<details>` arc list, **promoted to a file-grouped table** (reuse `file_tree.py` grouping), print-expanded and searchable. Each row: `Arc N · name · file · k named commits · [tiny sparkline]`, with an **undatable badge** when no commit resolves — so the 96 dropped arcs become a labeled lossy state, not a silent drop (#133).

   **Per-arc sparkline (Tom's call, 2026-06-17):** each datable row carries a *small* sparkline — the arc's commit timestamps plotted as **dots on a mini absolute axis** (shared full-span scale), **never a connecting span/band**. This gives an honest at-a-glance "when" per arc without re-introducing the lie. Undatable rows show the badge in place of the sparkline. Watch the ink budget — keep it genuinely tiny (a thin strip), since over-decorating each of ~200 rows is the clutter we're escaping.

### The honest interaction (replaces PR2's band-highlight)

The only honest joins are commit-mediated (the review's accounting):
- contributor → their commits (real) → some are arc-named (pigment, already distinct) → click a named commit → its story page.
- arc (roster row) → its named commits on the spine (highlight the real marks; bracket the set). **No band.**
- A contributor's "active window" is derivable from real timestamps and may be bracketed faintly — honest, unlike an arc span.

The `data-sha` join key (added on swimlane bubbles in the abandoned PR2) is **kept and repurposed** for this commit-overlay highlight.

## What is removed vs kept

**Remove:** `render_arc_band` (the packed timeline), `antiquarian/arc_layout.py` / `pack_arcs` (nothing to pack once spans are gone), the shared-geometry coupling and its borrowed 220px gutter, and the abandoned PR2 sticky-float + bidirectional band-highlight (branch `claude/arc-timeline-float`, never merged).

**Keep / repurpose:** the swimlane (the real spine), `build_absolute_scale`, the dormancy hatch (on-ethos), `file_tree.py` (roster grouping), the folded-list/print-degradation patterns (promoted to the roster), and the `data-sha` join key.

## Build sequence (two PRs, each shippable + TDD'd)

- **PR-A — Honest roster + kill the band (fixes #133).** Remove `render_arc_band` + `arc_layout.py`; replace the arc atom with the file-grouped roster table listing **every** arc, undatable badged; add a `datable_count` to the arc render data so the badge and any future rail are derivable. This alone removes the lie, fixes the silent-drop bug, and reclaims the page height. The roster is honest and complete on its own.
- **PR-B — Swimlane arc overlay + commit-mediated hover.** Emphasize arc-named commits on the spine (re-add `data-sha` on bubbles), add the decisive-commits rail for tail-author named commits, bracket-the-set on roster-row / commit hover, and commit→story links. The interaction budget from PR2 is re-spent here, honestly.

## Out of scope (named follow-ups, not this rework)

The review's strongest secondary finding: the **measured** structures in `profile.py` barely reach the broadsheet and are more honest + scale-stable than the LLM arc layer — the **co-change graph** (`build_co_changes`/`related_files`) as the real basis for any cross-file view, **regions + `notable_evolutions`** (z>2 outliers) to triangulate decisive-commit emphasis independently of arcs, and **`AuthorBaseline`** fingerprints for Dramatis Personae. These are the next thread after the arc rethink lands — tracked separately, not built here.

## Constraints carried forward

Print-first (#40); compact-on-screen / full-in-DOM (the roster lists every arc); one absolute spine (this *strengthens* it by removing the pseudo-spine); voice rules on commits/PRs; Python 3.13 / uv; TDD.
