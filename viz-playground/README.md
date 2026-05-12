# Antiquarian viz playground

Feel-testing infrastructure for issue [#8](https://github.com/tclancy/antiquarian/issues/8). The same three atoms rendered identically across three candidate stacks from the same real input, so Tom can experience each option side-by-side and decide which (if any) earns a real implementation.

This is **not** a finished product. It is throwaway scaffolding whose job is to be looked at, compared, and discarded once a choice is made.

## What's here

```
viz-playground/
├── Makefile                # `make all PROJECT=<name>` builds everything for that project
├── data/extract.py         # Python — reads cache.db + per-file stories, emits JSON atoms
├── observable/build.py     # Stack 1 — Observable Plot via CDN, markdown-vibe authoring
├── vega-lite-static/build.py  # Stack 2 — Python emits Vega-Lite specs, vega-embed renders
├── hand-svg/build.py       # Stack 3 — pure-Python SVG strings, zero chart library
├── output/<project>/       # Rendered artifacts per project per stack
│   ├── data/               # JSON contract — shared across stacks
│   ├── observable/index.html
│   ├── vega-lite-static/index.html (+ specs/*.vl.json)
│   └── hand-svg/index.html
└── README.md
```

Both projects ship with real cached data and at least one real `antiquarian story` output. No stub TODOs. No invented commits.

## Quick start

```bash
# Build everything for itguy (Tom's homelab deployment tool — bot-authored, no TODOs)
make all PROJECT=itguy

# Build everything for comictagger (10+ years old, 3 contributors, 9 real TODOs, big lossy gap)
make all PROJECT=comictagger REPO=/tmp/comictagger

# Serve and inspect
make serve PROJECT=itguy
# → http://localhost:8765/observable/, /vega-lite-static/, /hand-svg/
```

`make all` accepts any project name as long as `REPO=<path>` points to a directory that has `.antiquarian/cache.db` (and, ideally, `.antiquarian/stories/*.md`). Defaults to `/Users/tom/Documents/work/itguy` for `PROJECT=itguy` and `/tmp/comictagger` for `PROJECT=comictagger`.

## Why three projects' worth of stories matter

The playground deliberately uses two projects with different shapes so the visual differences between stacks actually surface:

- **itguy** — recent (April-May 2026), bot-authored, three files in cache, **eleven** named arcs, **zero** TODOs. Stresses the multi-file legend, the arc-band density, and the "empty atom" message in the TODO strip.
- **comictagger** — decade-old OSS, three contributors, one file in cache, five arcs, **nine** real TODOs across three commit cohorts, with a **seven-year gap** between contributor eras. Stresses the lossy-region atom (hand-svg renders it as diagonal hatching across the gap) and the TODO age-bucket colorization.

If you want to add a third project: run `antiquarian story <file>` against it first to seed at least one story, then `make all PROJECT=<name> REPO=<path>`.

## How to compare these

Open all six pages in tabs and scroll through them with both projects:

1. **Does the TODO strip read at a glance?** No drill-down needed — the eye should land on the oldest admissions immediately. Comictagger's three cohorts (1473d, 1455d, 274d) should pop visually.
2. **Does the swimlane communicate the channel quality?** Hand-svg adds a diagonal-hatch overlay for the biggest commit gap (the seven-year silence in comictagger). The other two stacks just show the empty space. Which feels more honest?
3. **Does the arc band feel like a single answer, or a "click around to find it" puzzle?** Per Tom's anti-Bubble-Dashboard criterion.
4. **Does the source code feel like something you'd want to maintain?** Observable embeds JS-in-markdown templates inside Python; Vega-Lite is pure JSON dicts; hand-svg is f-strings of literal SVG. Each has a different cognitive shape when you go to add the next atom.

## Decision log — trade-offs ran into while standing these up

### Observable Framework (`observable/`)
- **What it actually is here:** Static HTML with Observable Plot loaded from a CDN and the data embedded inline, rendered into `<div>` targets on page load. The playground brief excluded "static HTML + Python build only," so a full Framework project (Node + npm + `npm run build`) was out of scope. The Plot calls themselves are written the way an `auth.py.md` Framework page would write them — narrative paragraphs interleaved with `Plot.plot({...})` blocks — so the *authoring feel* is preserved even if the *build pipeline* isn't.
- **What feels good:** The Plot grammar is genuinely terse. The TODO bar chart is ~25 lines of Plot config; legends and tooltips are one-liners. Interleaving prose with charts in the same file reads the way technical writing wants to read — narrative-first, charts as evidence.
- **What hurt:** Embedding JS expressions inside a Python f-string is its own special hell — `${...}` template literals collide with Python's `{...}` placeholders, so the JS bodies live in module-level constants with `${{...}}`-style escaping. Real Observable Framework wouldn't have this pain because the markdown source is JS-native. If we picked this stack, the right move is the proper Framework setup and accept the Node dependency.
- **Bubble Dashboard risk:** Low. Plot doesn't give you a free "drag here to explore all dimensions" surface; you have to pick what to encode in each call.

### Vega-Lite static (`vega-lite-static/`)
- **What it actually is here:** Python emits three `*.vl.json` specs into `output/<project>/vega-lite-static/specs/`, plus a tiny `index.html` harness that loads them via `vega-embed`. The specs are the deliverable; the harness is incidental.
- **What feels good:** Atom = value, not component. The specs round-trip cleanly through `vega-lite.compile()` for validation (every spec compiles with zero warnings in this build). When the data layer changes shape, ALL three specs regenerate from one Python script — derive-don't-duplicate is a real thing here, not a slogan. Each spec is also independently readable/diffable as JSON.
- **What hurt:** Vega-Lite has opinions about chart shape that occasionally fight the data: an arc with a single decisive commit collapses to a zero-width band (visible in the comictagger arc-band; arcs 1, 3, 5 are commit-count=1 so they only show as a single tick, not a band). The fix is per-spec polish (force a minimum-width inset, draw a tick at the band position when count=1) which is doable but is "polish a library default" not "design the visual atom."
- **Bubble Dashboard risk:** Low. Like Plot, the grammar forces you to commit to a visual encoding per chart.

### Hand-rolled SVG (`hand-svg/`)
- **What it actually is here:** Python emits SVG strings directly into a single HTML page. Zero JS, zero chart library, zero CDN. The visual vocabulary — colors, type sizes, the diagonal-hatch lossy-region pattern, the per-arc color palette — is project-defined in a `PALETTE` dict and an `ARC_COLORS` list at the top of the file.
- **What feels good:** Everything is exactly what you wrote. The diagonal-hatch overlay on the seven-year comictagger gap is a *project-controlled* visual signal, not a library affordance. There is no chart library defaulting to "tag soup" pastels. This is also where the uncertainty / lossy-region atom Tom called out in issue #4 *should* live long term — even if the other two stacks render the swimlane prettier, neither can speak the project's own visual language for "the channel went dark here."
- **What hurt:** Manual axes. Manual layout math. Manual tooltip-via-`<title>` (no rich tooltips without adding JS). It took ~3x as much code as either library variant to produce a comparable swimlane. For *the canonical uncertainty atom* this is fine; for general-purpose chart rendering, the maintenance burden compounds fast.
- **Bubble Dashboard risk:** Zero. You can't accidentally turn a hand-rolled SVG into a faceted explorer.

## My honest recommendation as a developer who just lived through this

(For the PR body — keeping it brief here.)

**The layered answer from the issue #4 second pass holds up.** The three stacks turn out not to be alternatives — they are answers to different questions:

- **Vega-Lite for the bulk of atoms.** The "atom = JSON spec, Python owns the truth" promise is real and ergonomic. Six specs compile cleanly in this build; the data shape change for multi-file arcs only required updating `data/extract.py` and one small label tweak in `vega-lite-static/build.py`.
- **Observable Plot for the *narrative pages*.** If we want a viewer that reads as narrative-with-evidence (the original "auth.py.md" vision), Plot inline in markdown is the right authoring ergonomic. But we should commit to actual Observable Framework with npm — the JS-in-Python-f-string version here is a feel-test approximation, not a production pattern.
- **Hand-rolled SVG for the uncertainty / lossy-region atom and any other atom that needs to look intentional.** Per Tom's issue #4 reply: "the channel is too lossy here" needs project-controlled visual language. The diagonal hatching in `hand-svg/` is the canonical version; the other two stacks should *consume* it as a reusable atom rather than reinvent it.

**Anti-pattern guard:** All three pass the Bubble-Dashboard test. None of them give a "drill down through interactive nodes" surface. All three deliver the answer at first glance.

**Practical caveat:** the playground deliberately tested only three atoms. The real load-bearing question — "how do these feel when you're trying to render the *seventh* atom into the same page" — won't show up until we wire one of these into a real `antiquarian narrative` output. So this comparison ranks the stacks for what they look like; the real test is what they look like at week three.

## Re-running everything

The Makefile is idempotent. Re-extract data after running `antiquarian story` against new files:

```bash
make data PROJECT=<name>
# Then any of:
make observable PROJECT=<name>
make vega-lite PROJECT=<name>
make svg PROJECT=<name>
make all PROJECT=<name>          # all three
```

To clean a project's output:

```bash
make clean PROJECT=<name>
```
