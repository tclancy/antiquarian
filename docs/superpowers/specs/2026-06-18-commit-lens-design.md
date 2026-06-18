# Design: the commit lens (zoom-inset for the swimlane)

- **Date:** 2026-06-18
- **Evolves:** #119 (arc overlay / cross-highlight). The per-bubble hover + native `<title>` tooltip shipped in #134/#142 proved too fiddly at scale (tiny tooltips; impossible to pick a bubble in dense rows; nothing to grab in sparse rows). This supersedes the *tooltip* with a real detail surface and the *bubble-picking* with a zoom inset. The dim-the-rest highlight from #142 is **kept** (it's the macro view).
- **Status:** scoped from Tom's answers; pending his review before planning.

## The core idea: macro swimlane + micro lens

Two complementary surfaces, one click apart:

- **Macro — the swimlane (unchanged in spirit).** The whole contributor×time field. Selecting a commit dims the rest and lights that commit's **arc footprint across contributors** (the #142 dim-the-rest). *Enhancement:* the co-arc commits also **grow** and **tint to the arc's colour** (each arc gets a colour), so the arc's spread reads at a glance.
- **Micro — the commit lens.** Clicking a region of a contributor's row **pins a zoomed inset immediately below the swimlane**: that one contributor's commits in that time-window, spread far enough apart to differentiate and click individually. Selecting a bubble fills a **detail panel** reserved at the bottom of the inset.

The lens solves all three problems at once: tiny tooltips → a roomy detail panel; can't-pick-in-dense-rows → bubbles spread out in the zoom; nothing-to-grab-in-sparse-rows → the few bubbles become big targets.

## Behaviour (settled with Tom)

1. **Trigger — click to pin.** Click a region of a contributor's timeline row → the lens opens for that contributor + window and **stays pinned** until dismissed (click-away or an explicit ✕). Not hover (too twitchy; and you need it stable to click bubbles inside it).
2. **Lens scope — just that contributor**, for the clicked time-window, zoomed. The cross-contributor story stays in the macro swimlane above (see #4), not duplicated in the lens.
3. **Detail panel (bottom of the lens).** Selecting a bubble fills it with the commit's narrative — the richer of the commit `message` / PR `pr_body` — **capped at ~50 words → ellipsis**, then **links to both the PR and the commit** (some projects put the story in the PR, some in the commit, most just say "changes…"; link both when present). 50 words is a starting cap, tunable.
4. **Macro tie-in (answers Tom's Q5).** While the lens is open / a bubble selected, the swimlane keeps the arc highlight: dim the rest, and **grow + arc-colour** the selected commit's co-arc commits across every contributor's row. The lens is the micro; the swimlane is the macro; both live at once.
5. **Lifecycle.** Pinned until dismissed. Opening a new region replaces the lens.

## Surfaces / honesty / print (the standing rules)

- **Two-surface model (#40):** the lens + detail panel + grow/tint are a **pure HTML/JS layer** over the static swimlane. Print and no-JS show the swimlane as-is (the marks are the data); the lens simply doesn't exist there. Lossless.
- **Honesty:** everything in the lens is a **real commit mark**; the arc colour/grow is emphasis on real marks, never a synthesised band/span. The detail panel quotes real artifacts (commit message / PR body) and links to the source — the reader can always go check.
- Lossy: if a commit has no PR and a bare message ("changes…"), the panel says so plainly and still links the commit.

## Data — all available (verified)

- `CommitFeatures.message` (full commit message), `pr_number`, `pr_body` — the detail-panel content. (Today only `message_subject` reaches the swimlane dict; **pipe `message`, `pr_body`, `pr_number` through `_build_swimlane`.**)
- `detect_github_repo(repo_path) -> (owner, repo)` → build `https://github.com/<owner>/<repo>/commit/<sha>` and `…/pull/<n>`. Pass `(owner, repo)` into `render_swimlane` (like `arc_lookup`); when there's no GitHub remote, omit the links (lossy, say so).
- Per-commit `arcs` (slugs) + a **per-arc colour** map (assign colours to arcs — reuse the old `ARC_COLORS` palette that was retired, or a fresh ramp) for the grow/tint.

## Build phases (each shippable; the macro enhancement can land first or last)

- **Phase 1 — the lens + detail panel.** Click a row-region → pinned zoomed inset of that contributor's commits in the window; click a bubble → detail panel (≤50 words + PR/commit links). Pipe `message`/`pr_body`/`pr_number` + `(owner,repo)`. This is the bulk of the value.
- **Phase 2 — the macro enhancement.** Assign per-arc colours; on selection, grow + tint the co-arc commits across the swimlane (on top of the existing dim). Pure visual upgrade to the macro highlight.

(Phasing TBD at planning — Phase 2 is independent and could even come first as a quick win, since the dim already exists.)

## Open questions for Tom

1. **What counts as a "region"?** Click anywhere on a contributor's row → zoom a fixed window centred on the click (say ±N months)? Or divide each row into a few clickable buckets? Or click the contributor's *name* → lens their whole timeline? (Leaning: click the row → window around the click, with the window width adaptive to local density.)
2. **Where does the lens sit?** Pinned directly under the swimlane atom (pushing content down), or as a fixed panel that overlays the lower viewport? (Leaning: inline under the swimlane, so it prints/screenshots in place if expanded.)
3. **Arc colour ramp** for the grow/tint — revive the retired `ARC_COLORS` (the broadsheet's oxide/ink/blue family) or a new, more distinguishable set? With 202 arcs, colours will repeat — is colour just "this-arc-vs-not" emphasis, or do we want a stable per-arc hue?
4. **Detail source priority** when both exist — show PR body or commit message first? (Leaning: PR body if present, else commit message; label which it is.)
5. **Mobile/narrow** — out of scope for the print-first broadsheet, or should the lens degrade to a stacked panel? (Leaning: out of scope for now.)

## Out of scope
- The story-page sidebar / gutter timeline (#138 — separate thread, first cut on `claude/story-sidebar-138`).
- The masthead commit-density timeline (#136) — though the lens interaction could be reused there later.
