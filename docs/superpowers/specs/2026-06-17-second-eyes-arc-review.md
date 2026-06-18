# Second eyes: the named-arcs view and the data behind it

**Reviewer brief:** information-design + data-modeling second opinion on the
broadsheet "named arcs" view, which the maintainer reports isn't working.
**Deliverable:** a written recommendation, not code. Opinionated by request.
**Date:** 2026-06-17. **Fixture:** httpx (115 files, 1,317 commits, 235 contributors,
202 arcs across 55 files).

---

## TL;DR

The packed density timeline is failing because it is **visualizing a derived
artifact (LLM-named arcs) as if it were a measured one (commit activity)**, and
the two have almost nothing to do with each other dimensionally. The arc layer
carries narrative-importance signal; the swimlane carries volume-over-time
signal; the design tries to make them register x-for-x on a shared spine and
cross-highlight by SHA. They don't line up because *they aren't the same kind of
thing*, and no amount of layout tuning fixes a category error.

**The single most important data-model change:** stop treating
`arc = (file_path, name, first-commit → last-commit span)` as the timeline
primitive. The per-file arc is a **narrative label on a set of commits**, not a
time interval, and it should not be drawn as a band. Replace the spanned-band
representation with a **commit-anchored** one: the decisive commits an arc names
are the real, datable, honest marks — the arc is their grouping, surfaced as
prose/legend, not as geometry. Everything below follows from this.

**Recommended direction:** kill the packed-arc timeline. Promote the **swimlane
to the single time spine** and overlay arc membership *on the commits that
already exist there* (decisive commits get the arc pigment + a hover that names
the arc). Move the arc roster to a compact, file-grouped **table/legend** beneath
it. This collapses three half-working things (tall arc band, dead gutter, broken
cross-highlight) into one honest atom and is the truest "orientation map."

---

## What I verified against the data (corrections to the brief)

I read `models.py`, `render_data.py`, `profile.py`, `render.py`, `arc_layout.py`,
the design spec, and the live render, then checked the fixture's `cache.db` and
stories directly. The brief is essentially correct. Precise numbers:

| Claim | Verified value |
|---|---|
| 202 arcs across 55 files | **Confirmed.** 202 arcs, 55 files. Mean 3.7 arcs/file, median 4, max 5. |
| Arc explosion is per-file | **Confirmed and it's a hard ceiling.** The synthesizer emits up to ~5 arcs *per file*; 55 files × ~4 = 202. The count is a function of file-count, not of how many distinct things actually happened in the repo. |
| `decisive = bool(commit.arcs)` | Confirmed (`render.py` swimlane loop). |
| 22 arc commits have no on-screen bubble | **21** by my dedup (235 contributors, top-30 lane budget). Same finding; rounding. |
| Arcs span first→last decisive commit | Confirmed (`arc_layout._arc_span`). |
| Arc-membership tracks narrative importance, not size | Confirmed — and this is the crux (see below). |

**Two facts the brief didn't surface, and they're the most important ones:**

1. **96 of 202 arcs (47.5%) have *zero* datable commits.** `arc_layout.pack_arcs`
   silently skips any arc whose body references no resolvable SHA. So the packed
   timeline you're looking at — the "goofy, too tall" 17-row wall — is drawn from
   only **106 arcs**, and the folded list below it is the *only* place the other
   96 exist. Nearly half the data this atom claims to be about is invisible in the
   visual. That is the opposite of the "lossy regions are first-class / say what
   was lost" ethos: here the *primary* data is the thing being silently dropped,
   with no hatch, no "+96 undatable," nothing. **This alone is a correctness bug
   against the project's own stated values.**

2. **The arc-to-time mapping is mostly an illusion of precision.** Of the 106
   datable arcs, many resolve to a *single* SHA (`MIN_LOZENGE_PX = 3.0` exists
   precisely because zero-span arcs are common), so their "span" is a 3px
   render-minimum, not a real interval. The wide multi-year lozenges the
   maintainer complains about (symptom 5) are the few arcs whose first and last
   named commit happen to be years apart — but those endpoints were chosen by an
   LLM writing prose, not by any activity measure. A 4-year-wide band can rest on
   exactly two commits. The band *looks* like sustained activity and *is* two
   dots. This is confabulated certainty in visual form — the thing the ethos
   explicitly forbids.

So the brief's instinct ("arcs should be broken into sub-pieces") is directionally
right but doesn't go far enough: **the span itself is the lie.** You don't want
smaller bands; you want to stop drawing bands at all and draw the commits.

---

## Why the current approach is failing (root cause, not symptoms)

The five reported symptoms are surface readings of three structural faults.

### Fault 1 — A band is the wrong primitive for a narrative label

An arc, as produced, is: *"an LLM read one file's story and named up to ~5 themes,
each citing a few commit SHAs."* That is a **grouping of commits with a name and a
confidence-laden prose body.** It is not a measured time interval. Drawing it as a
horizontal span asserts two things the data does not support:

- that the arc was *active across the whole span* (false — it's active at its
  named commits, which may be two dots 4 years apart), and
- that the *width* means something comparable across arcs (false — width is an
  artifact of which SHAs the prose happened to cite).

Tufte's lie factor is the diagnostic here: the visual magnitude (band width,
17 stacked rows) wildly overstates the data magnitude (a few decisive commits per
arc, ~half of them undatable). The "goofy and too tall" feeling (symptom 1) is the
reader's eye correctly detecting that the ink-to-data ratio is inverted.

### Fault 2 — The shared-spine cross-reference joins two incommensurable layers

The design's elegant idea is: swimlane and arc band on one absolute spine, so
columns line up and you can cross-highlight by SHA (spec PR2/PR3). The problem is
**dimensional**, and the data proves it:

- Arc membership tracks *narrative importance*. Commit size (the swimlane's bubble
  radius) tracks *volume*. These are deliberately decorrelated — the project even
  says so ("don't precompute divisiveness; let synthesis derive it"). So the big
  bubbles (large diffs) and the lit lozenges (named commits) are **different
  commits**. Hovering a fat mark lights nothing; hovering a tiny one lights an arc.
  The interaction feels broken because it is reporting an honest truth in a
  confusing way: *importance and size are not the same axis.*
- The join only fires when a commit is **both** arc-named **and** in a top-30 lane.
  21 of 133 arc commits fail that (their author is in the 205-person tail). The
  cross-highlight is structurally partial and always will be, because the two
  budgets (top-30 lanes, named-commits) are independent cuts of the data.

### Fault 3 — The empty left gutter is a borrowed-geometry artifact

The dead space (symptom 2) is not a styling bug to nudge; it's the arc band
inheriting the swimlane's `margin_left = 220`, which exists to hold **author
labels the arc band doesn't have** (`render_arc_band`, line ~741). The band reads
as "doesn't span the area" because 220px of every row is reserved for nothing.
This is a direct consequence of the PR2 decision to make the two atoms share
geometry so they could float together — a decision that only made sense while the
shared-spine cross-reference (Fault 2) was believed to be the payoff. Remove the
payoff and the shared geometry is just inherited dead space.

---

## The honest contributor ↔ arc ↔ time relationship

The maintainer asks: what's the *honest, intuitive* cross-reference, and is
"light the active periods + link to detail" better than whole-arc highlight?

Here is the honest accounting of what each layer actually knows:

- **Commits** know: when, who, how big, which file(s). Measured. Trustworthy.
- **Contributors** know: a set of commits → therefore active periods are
  *derivable and real* (you can compute "Jane was active Mar–Jun 2021" from her
  commit timestamps — this is behavioral signal, the kind the ethos most trusts).
- **Arcs** know: a name + a prose body + a handful of cited SHAs, at LLM
  confidence. The *commits* are real; the *span between them* is not; the *name*
  is an interpretation.

So the only honest joins are **commit-mediated**:

- contributor → commits → (some are) arc-named ✅ honest
- arc → its named commits → their authors/dates ✅ honest
- contributor "active period" → time ✅ honest (derived from real timestamps)
- arc → "a span of time it covers" ❌ **not honest** (the span is confabulated)

This validates the maintainer's instinct precisely. **"Light the periods a
contributor was active" is honest because active periods are real, derived from
commit timestamps. "Light the whole arc band" is dishonest because the band's
extent is an artifact.** Switch the cross-reference to operate on **commits and
derived active-windows**, never on arc spans.

Concretely, the honest interaction is:
- Hover a contributor → highlight *their commits* on the spine (already drawn) and
  faintly bracket *their derived active window(s)*. Of those commits, the
  arc-named ones are already visually distinct (pigment). Clicking a named commit
  → its story page (the "link to detail").
- Hover/ья click an arc in the roster → highlight *its named commits* on the spine.
  No band. The commits are the arc.

This keeps every mark anchored to a measured quantity. It also fixes the partial-
join problem: you're joining on commits-that-exist, and you can choose to render
arc-named commits from tail contributors too (they're few — 21 — and they're the
*decisive* ones, so they earn the ink even if their author's lane is folded).

---

## Recommended direction (pick one)

### ✅ RECOMMENDED — "One spine, arcs as an overlay + roster"

**Throw away `render_arc_band` and the packed-timeline atom entirely.** Promote the
**swimlane to the canonical time spine** and express arcs as:

1. **An overlay on the commits already plotted.** Decisive (arc-named) commits keep
   their pigment outline (already implemented). Add: a thin **bracket/tick above
   the spine** marking the *set* of commits in a given arc on hover, drawn through
   the real commit x-positions — not a filled span. (Tufte: the marks are the data;
   a bracket connecting real points is honest, a filled band between two points is
   not.) Render arc-named commits from *tail* contributors too, on a slim "decisive
   commits" rail under the axis, so no named commit is invisible (fixes the 21-orphan
   and the 96-undatable problems: undatable arcs simply have no rail mark and are
   labeled as such in the roster).
2. **A compact arc roster** beneath the spine — the current folded `<details>` list,
   but **promoted to a first-class file-grouped table** (reuse `file_tree.py`'s
   grouping), 2–3 columns, each row: `Arc N · name · file · k named commits ·
   [undatable badge if k_datable==0]`. This is where identity and the 96 undatable
   arcs live, in the DOM, print-expanded, searchable. It is the orientation map's
   index.

**Why this one (against the ethos + the budget doc):**
- **Honest (ethos).** No confabulated spans. Every visual mark is a real commit or
  a derived-from-real-commits window. The 96 undatable arcs are *named as such*
  instead of silently dropped — that's the "lossy regions are signal" rule applied
  to the arc layer for the first time.
- **One time spine (visual-vocabulary #3).** It *strengthens* the single-spine
  commitment by removing the second pseudo-spine that pretended arcs were
  independently time-positioned.
- **Budget (visualizing-at-scale #1–2).** The atom's height becomes O(visible
  contributors), which is already budgeted at 30 — not O(arcs ≈ 202). The roster is
  a table, which scales by disclosure like the file tree. The arc layer stops having
  its own runaway height.
- **Kills all three faults at once:** no band (Fault 1), no incommensurable shared-
  spine join — the join is now commit-to-commit on a single chart (Fault 2), no
  borrowed gutter because there's no second chart (Fault 3).
- **Print-first.** Overlay degrades to "decisive commits are the outlined ones"
  (already true on paper); roster prints expanded.

What you throw away: `render_arc_band`, `arc_layout.py` (the packing is moot —
there's nothing to pack), the sticky-float (#119 PR2) and the SHA cross-highlight
script in its current bidirectional-band form (#119 PR3). The `data-shas` join key
survives, repurposed for the commit-overlay.

---

### Alternative A — "Arc small-multiples by file" (spec option B)

One sparkline-row per *file that has arcs* (55 rows, not 202), each showing that
file's commits on a mini absolute spine with arc-named commits emphasized. Scannable,
honest (it's commits, not spans), and it makes the per-file arc granularity *legible*
instead of *exploded*. Trade-offs: 55 rows still needs the budget+disclosure
treatment (top-N files by activity, fold the rest); it's taller than the recommended
overlay; it can't float. Good **fallback** if reviewers want arcs to keep a dedicated
atom rather than living as a swimlane overlay. Reuses `file_tree.py` grouping.

### Alternative B — "Arc roster only; no arc chart at all"

Demote arcs to a pure **table** (the roster above), no spine geometry whatsoever.
Arcs are inherently prose/narrative artifacts; maybe they don't want a chart.
Cheapest to build, most honest of all (no geometry to lie with), and arguably the
truest "index as map" reading. Trade-off: loses the at-a-glance "when did named work
cluster" signal — though that signal is largely already carried by the swimlane's
density and the masthead dormancy strip, so the loss is smaller than it looks. Worth
seriously considering if the overlay (recommended) proves fiddly.

### Alternative C — Keep the packed timeline, just fix it (NOT recommended)

De-tune symptom-by-symptom: drop the 220px gutter, cap rows with a budget+fold,
hatch the 96 undatable arcs, narrow multi-year bands. This is achievable but treats
the symptoms while preserving Fault 1 (band-as-primitive) and Fault 2 (the
dimensional mismatch). The maintainer explicitly said he wants to revisit the *idea*,
not tune it. Listed only for completeness; I'd discard it.

---

## Latent structure in `profile.py` that is underused

The brief asks what in `profile.py` could carry more load. Three things, all
currently computed-or-derivable and **not** reaching the broadsheet:

1. **`build_co_changes` / `related_files` (co-change graph).** This is the single
   strongest *behavioral* signal the project has and it appears **nowhere** in the
   render. The ethos ranks behavioral signals above declarative ones; co-change is
   exactly that ("what files move together" is harder to fake than a commit message).
   It belongs to survey section 3 ("Coupling/divergence") and is a far better basis
   for a "cross-file arc" view than the per-file LLM arcs are — a co-change cluster
   is a *measured* multi-file structure, whereas a "cross-file arc" is currently
   re-derived by the LLM. **Recommendation:** if you want an honest multi-file
   timeline atom, build it from co-change edges (real) rather than from arc spans
   (confabulated). The `commit_shas` on each `CoChange` already give you datable
   anchor points and the machinery to reconstruct triples.

2. **`build_regions` + `notable_evolutions`.** Regions (top-level dir clusters) with
   their **statistically-notable commits** (region-relative z>2 outliers) are a
   ready-made, *measured* answer to "where did unusually large work land, and when."
   This is a stronger, cheaper "significant change" signal than arc membership, and
   it's region-relative so it scales. It could drive the decisive-commit emphasis on
   the spine **independently of the LLM arcs**, giving you triangulation (ethos:
   "triangulation beats single-source") — a commit emphasized when it is *both*
   arc-named *and* a region outlier is far more trustworthy than either alone.

3. **`AuthorBaseline.typical_hours / typical_days / regions_touched / tenure`.** The
   Dramatis Personae section is currently pure LLM prose. These baselines are
   measured and would let each contributor carry an honest behavioral fingerprint
   (tenure span, home region, working rhythm) next to the prose — triangulating the
   narrative against behavior. Underused; cheap to surface.

The throughline: **the broadsheet currently leans almost entirely on the LLM-derived
arc layer and barely touches the measured structural layer.** The measured layer is
both more honest and more scale-stable. Shifting load from arcs → co-change/regions/
baselines is the data-organization move that most aligns with the ethos.

---

## On the arc primitive itself (the data-model recommendation, stated sharply)

Today: `_Arc(file_path, arc_number, name, slug, date_range, body, commit_shas)`,
rendered as a span via `_arc_span` = (min, max) of resolvable SHA timestamps.

Recommended shape change — **make the commits, not the span, the primitive:**

- Keep the arc as a **named set of commits** (`name`, `file_path`, `commit_shas`,
  `body`, `confidence`/`date_range` as prose only).
- **Never compute or render a `(start, end)` interval from it.** If a "when" is
  wanted, it is the *set of commit timestamps*, plotted as points, not a span.
- Add an explicit **`datable_count`** so the renderer can mark and the roster can
  badge the 96 zero-datable arcs as a first-class lossy state instead of dropping
  them in `pack_arcs`.
- Treat `date_range` (the LLM's parenthetical "(late March → early April 2026)") as
  **prose metadata only** — never as plotting coordinates. It's a relay artifact at
  the lowest trust tier; the real timestamps outrank it.

This is the one change that everything else hangs on: once arcs are sets-of-commits
rather than spans, the band disappears, the gutter problem disappears with it, the
cross-highlight becomes commit-to-commit (honest and total), and the undatable arcs
become a labeled lossy region instead of a silent 47.5% drop.

---

## What I'd throw away

- `render_arc_band` (the packed-timeline atom).
- `arc_layout.py` / `pack_arcs` — nothing to pack once spans are gone.
- The shared-geometry coupling of swimlane + arc band (the 220px borrowed gutter).
- The sticky-float arc panel (#119 PR2) and the bidirectional band-highlight
  (#119 PR3) **in their current form** — re-spend that interaction budget on
  honest commit-overlay highlighting on the single spine.
- The `date_range`-as-coordinates assumption, everywhere.

Keep: the swimlane (it's the real spine), the absolute-scale machinery
(`build_absolute_scale`), the dormancy hatch (genuinely good and on-ethos), the
`data-sha` join key (repurposed), the folded-list/print-degradation patterns
(promote the arc list to the roster table), and `file_tree.py` (reuse for the
roster grouping).
