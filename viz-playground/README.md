# Antiquarian viz playground

Feel-testing infrastructure for issue [#8](https://github.com/tclancy/antiquarian/issues/8). Three candidate stacks render the same three atoms from the same real input — but in **three deliberately different visual idioms** so Tom can compare what each one actually feels like, not just what it can technically draw.

This is **not** a finished product. It is scaffolding whose job is to be looked at, compared, and discarded once a choice is made.

## What's here

```
viz-playground/
├── Makefile                       # `make all PROJECT=<name>` builds everything
├── data/extract.py                # Python — cache.db + stories → JSON atoms (+ timeline + lifespans)
├── observable/                    # Stack 1 — real Observable Framework (Node + npm)
│   ├── package.json               #     `npm run dev` for live-reload preview
│   ├── observablehq.config.js
│   ├── src/index.md               #     narrative essay with charts inline
│   ├── src/style.css              #     story-page typography (serif body)
│   └── src/components/*.js        #     four atoms + the dual-axis time helper
├── vega-lite-static/build.py      # Stack 2 — Python emits Vega-Lite specs, vega-embed renders
├── hand-svg/build.py              # Stack 3 — pure-Python SVG strings, project-controlled vocabulary
├── output/<project>/              # Rendered artifacts per project per stack
│   ├── data/                      #   JSON contract — shared across all three stacks
│   ├── observable/index.html      #   compiled Framework output
│   ├── vega-lite-static/index.html  #   + specs/*.vl.json
│   └── hand-svg/index.html
└── README.md
```

## Quick start

```bash
# Build everything for itguy (bot-authored, 0 TODOs — empty-atom test case)
make all PROJECT=itguy

# Build everything for comictagger (6 files, 22 arcs, 7-year dormancy)
make all PROJECT=comictagger

# Or point at any other repo that's been `antiquarian story`d
make all PROJECT=BetterBlue REPO=/path/to/BetterBlue
make all PROJECT=courtlistener REPO=/path/to/courtlistener

# Serve and inspect
make serve PROJECT=comictagger
# → http://localhost:8765/observable/, /vega-lite-static/, /hand-svg/
```

`make all` accepts any project name. Built-in defaults exist for `itguy`, `comictagger`, `BetterBlue`, and `courtlistener`. For anything else, pass `REPO=<path>` pointing at a directory that has `.antiquarian/cache.db` (and, ideally, `.antiquarian/stories/*.md` and `.antiquarian/surveys/*.md`).

## Observable Framework dev loop

The Observable variant is now a real npm-based Framework project, not a static-HTML approximation. The dev loop:

```bash
cd viz-playground/observable
nvm use                        # honors .nvmrc (Node ≥ 20)
npm install                    # first time only — produces package-lock.json
npm run dev                    # http://localhost:3000 with live reload
```

Re-pointing the dev preview at a different project requires running `make observable PROJECT=<name>` first, which copies that project's JSON into `src/data/` (the Framework reads it via `FileAttachment`). The `dev` server picks up the new data automatically.

The orchestrator `observable/build.py` does the full production build:

1. Copies per-project JSON from `output/<project>/data/` → `observable/src/data/`
2. Writes `active-project.json` (project name, files, story paths)
3. Generates a per-project Framework config (`observablehq.config.<project>.js`) that overrides just the `output` key so two `make` runs don't collide
4. Invokes `npx observable build` → `dist-<project>/`
5. Copies `dist-<project>/` → `output/<project>/observable/`

## Round 2 highlights — what changed from the first pass

Tom's PR #11 review asked for four things and surfaced one bigger problem ("the stacks look too similar at a glance"). This round addresses each:

### 1. Stacks now feel visually distinct

- **observable/** — long-form essay typography. Serif body, single ~720px column, charts as evidence cited inline between paragraphs. Reads like a New Yorker piece with charts. Real Observable Framework via npm.
- **vega-lite-static/** — instrument-panel density. Black header strip, monospace typography, hex-numbered cell labels (00, 01, 02, 03), each atom paired with an inline JSON spec inspector. Reads like a technical reference page.
- **hand-svg/** — antiquarian broadsheet. Parchment-yellow paper, large serif masthead, dateline in small caps, drop cap on the lede paragraph, double-rule borders, italic "the silence — N days" labels across the lossy hatching. Reads like a 19th-century broadsheet.

Same data, three completely different presentations. If they still look interchangeable, something has gone wrong.

### 2. Dual-axis timeline + active-window compression

Comictagger's record runs across 3,558 days (Feb 2013 → Nov 2022) with a 2-year gap and then a 7-year gap. A naive time axis renders 99% blank space. This round implements a **piecewise pixel-space scale**:

- Every atom has a **reference strip** atop it showing the full project lifespan (2013–2022 for comictagger) with active commit windows in accent and dormancies hatched. Year ticks below.
- The main chart's X-axis is **compressed to only the active windows**. Gap segments between windows are drawn explicitly with hatching and an italic "X.Xy gap" label. The 7-year silence is still visible — as 80px of diagonal hatching, not as 89% empty plot.
- Per-window date labels ("Feb 2013 · 2.0y gap · Feb 2015 · 7.1y gap · Apr–Nov 2022") sit beneath each chart.

The dual-axis logic lives in a tiny Python helper (`build_active_scale()`) duplicated across all three stacks. It's small enough that the duplication is honest — the alternative was a JS+Python interop dance the playground shouldn't need.

### 3. Real Observable Framework via npm

Replaces the static-HTML CDN approximation from round 1. `node >= 20` (pinned via `.nvmrc`), `npm run dev` for live reload, `observable build` produces a static dist that the orchestrator copies into `output/<project>/observable/`. The narrative page (`src/index.md`) reads as markdown with inline JS code blocks that import from `src/components/*.js` — exactly the authoring ergonomic the round-1 stand-in only approximated.

### 4. "Diff size (LoC)" legend label

All three stacks now spell out the diff-size dimension as **lines of code (LoC)** in the swimlane legend, so a reader doesn't have to infer that the mark size is a code metric:

- observable: hand-rolled size legend with three sample circles + LoC values
- vega-lite: native size legend with `title: "Diff size (LoC)"`
- hand-svg: hand-set legend block with sample circles + LoC values + italic "decisive commit (named in story) / supporting commit" color legend

### Bonus — rename-truncation honesty

The comictagger survey noted `cli.py` shows only 1 commit because `git log --follow` lost the rename chain at the 2013 SVN→Git boundary. The data layer flags this (`likely_rename_truncated` in `file_lifespans.json`) and:

- observable shows an aside that names the affected files and explains the cause
- hand-svg adds a margin note: `2 file(s): "--follow" lost the chain.`
- vega-lite leaves the dot in place (the user can see the isolation in the swimlane)

This is a known limitation of the mining layer, not a viz bug — but the playground surfaces it rather than papering over.

## The richer comictagger dataset

This round runs against a 6-file comictagger survey (up from 1):

| File | Commits | Era | Notes |
|------|---------|-----|-------|
| `comictaggerlib/cli.py` | 1 | 2013 | SVN-import boundary; history truncated at rename |
| `comictaggerlib/taggerwindow.py` | 1 | 2013 | Same — but TODO evidence proves later edits exist |
| `comicapi/comicarchive.py` | 7 | 2015 + 2022 | Born in the package-split commit, modernized 2022 |
| `comicapi/filenameparser.py` | 9 | 2015 + 2022 | Carries 9 archaeological TODOs |
| `comicapi/genericmetadata.py` | 7 | 2015 + 2022 | Carries 1 TODO |
| `comictalker/talkers/comicvine.py` | 6 | 2022 (Oct-Nov) | Pluggable-talker arc, separate author |

The survey synthesis identifies five cross-file arcs (the 2013 SVN boundary, the 2015 `comicapi` extraction, the fcanc PEP 8 campaign, the 2022 Welch modernization, and the pluggable-talker arc). The hand-svg variant pulls one paragraph from the survey synthesis into the masthead as a pull-quote.

## Honest recommendation (from the dev who just rebuilt these)

**The layered answer from issue #4's second pass holds up, now with more conviction.** The three stacks aren't alternatives — they answer different questions about *what kind of document* this is:

- **Observable Framework for narrative pages.** Real npm build, Plot grammar in markdown, charts as evidence cited inline next to the prose that explains them. If the canonical `antiquarian narrative` output reads as long-form code-archaeology essay, this is its stack.
- **Vega-Lite for instrument-panel atoms.** "Atom = JSON spec, Python pipeline owns the truth" — all five specs compile cleanly via `vega-lite.compile()` with zero warnings; the JSON is inspectable; the multi-file label change required updating exactly one Python builder. Best for compact dashboards and reusable chart components.
- **Hand-SVG for branded / canonical atoms.** The lossy hatching with "the silence — 2596 days" labels is a project-controlled signal no library default can express. The broadsheet typography (serif, drop cap, double rule, small-caps dateline) is also project-controlled. Best for atoms that need to look intentional rather than chart-library-default.

**Anti-pattern guard:** All three still pass the Bubble-Dashboard test. None of them give a "drill down through interactive nodes" surface. All three deliver the answer at first glance.

**Practical caveat:** the playground tested three atoms. The seventh-atom test is still ahead.

## Re-running everything

The Makefile is idempotent. Re-extract data after running `antiquarian story` against new files:

```bash
make data PROJECT=<name>
make observable PROJECT=<name>
make vega-lite PROJECT=<name>
make svg PROJECT=<name>
make all PROJECT=<name>          # all three
make clean PROJECT=<name>        # remove output/<project>/
```
