# Architecture

## Stack

- **Python 3.13+, uv for everything.** No pip, no poetry.
- **PyDriller** for git mining (commits, diffs, churn, co-changes).
- **`claude -p` subprocess** for narrative synthesis. Local-first; no API credits while the idea proves itself.
- **SQLite** cache at `<repo>/.antiquarian/cache.db`, keyed by `(commit_sha, file_path)`.
- **Typer** CLI.
- **Hypothesis** for property tests; **Z3** for formal invariants (21 proved as of PR #22).

## File map

```
antiquarian/
├── cli.py          # Typer entry points: story, survey, files, render
├── pipeline.py     # Orchestration (generate_file_story, generate_codebase_survey)
├── mining.py       # PyDriller — uses `git log --follow` (NO --reverse, see #13)
├── prs.py          # gh CLI integration for PR enrichment
├── narrative.py    # `claude -p` subprocess + size-aware compressor (#36)
├── selection.py    # File selection (allow/block, --include/--exclude/--only)
├── cache.py        # SQLite store, schema-migrated
├── profile.py      # build_author_baselines, build_regions, build_co_changes
├── render_data.py  # Pull cache.db + stories into a render-ready dict
├── render.py       # Antiquarian broadsheet — hand-rolled SVG
├── todos.py        # TODO/FIXME extraction via git blame
├── models.py       # CommitFeatures, AuthorBaseline, RegionDefinition, CoChange, …
└── backends.py     # Git backend abstraction

verification/       # Z3 specs — 21 invariants proven
tests/              # pytest + Hypothesis (profiles: dev=30, ci=100, fuzz=1k, nightly=10k)
```

## Survey output structure

`antiquarian survey` produces a five-section synthesis:

1. **Files surveyed** — one line per file.
2. **Cross-file arcs** — named arcs spanning multiple files.
3. **Coupling and divergence** — which files travel together, which run independently.
4. **Where the channel went dark** — time windows with thin evidence.
5. **Dramatis Personae** — who shaped this codebase and how.

The **Coupling and divergence** section is fed structural evidence from two Pass-3 profilers: regions (top-level fiefdoms from `build_regions`) and file co-change pairs (`build_co_changes`). These don't appear as their own output sections — they color the coupling discussion with concrete names and counts.

## Multi-pass codebase examination ("Parliament of Owls")

The umbrella design for how the discrete profilers and detectors compose. Each pass walks around another part of the Blind Men and the Elephant.

| Pass | What we know | What it produces |
|------|--------------|------------------|
| **1** | Just this one file in isolation | Per-file story (`antiquarian story`) — shipped |
| **2** | File + commit history + author baselines + tone + related files | Richer per-file story; "this is part of something larger" emerges |
| **3** | All files clustered into regions; authors mapped to regions | Per-region narrative; cross-file arcs; coupling structure |
| **4** | Full elephant | Codebase-level Hemingway summary (`antiquarian survey`) — shipped |

Passes 1 and 4 are in place. Passes 2 and 3 are where most of the structural work lives.

### How issues feed the passes

| Pass | Issues feeding it |
|------|-------------------|
| **2** — file in context | Free signals on `CommitFeatures` (#53, merged), Person profiler (#49, merged), Related Files (#48) |
| **3** — fiefdom view | Region profiler (#52), Statistical SC detector (#51) per region |
| **2 + 3** — People thread | Dramatis Personae section (#50) — runs through both passes with different jobs |

### People as a thread, not a step

The People work isn't its own pass. It threads through 2 and 3 with different functions:

- **In pass 2:** "Who shaped *this* file? When? What's their voice?" — informs per-file ownership narrative.
- **In pass 3:** "Who owns which fiefdoms across the whole codebase?" — informs Dramatis Personae and the regional ownership picture.

Same data (`AuthorBaseline` from Person profiler), different cut.

### Design constraints for new passes

- **Passes 2 and 3 are independently runnable.** Don't make Pass 2 depend on Pass 3 (or vice versa). Pass 4 composes everything; Passes 2 and 3 stand alone.
- **No precomputed "divisiveness."** Some signals are better left to prose voice than to numbers. Punted deliberately.
- **No precomputed "tone of voice" per author.** Let synthesis derive it from the commit messages already in scope.
- **No over-engineered plugin discovery.** Profilers and detectors are Python module-level classes for now. Plugin entry-points can come if someone outside the repo wants to ship one.
- **Eyeball protocol:** Each profiler / detector lands with empirical validation against three repos already in scope — `itguy`, `BetterBlue`, `comictagger`. Tom rates whether the output captures the commits / authors / regions he'd flag manually.

## Identifiers

We carry **Antiquarian-native UIDs from day one** alongside backend identifiers (git SHA, jj change-id, jj commit-id). Cheap now, painful to retrofit. v2 will add real jj support.

## File selection

`selection.py` runs an allow/block model with three escape hatches: `--include`, `--exclude`, `--only`. Gitignore is trusted by default (soft-warn rather than hard-filter — see #15).

## Caching

SQLite at `<repo>/.antiquarian/cache.db`. Key is `(commit_sha, file_path)`. Schema migrations live alongside the schema definitions in `cache.py` — PR #57 is the reference pattern for adding columns.

## Narrative pipeline

`narrative.py` shells out to `claude -p` with a system prompt that enforces the voice rules from [`ethos.md`](ethos.md). Inputs are sanitized through `_sanitize_for_claude` (strips Claude-attribution trailers — see #16/#17) and will eventually pass through a size-aware prompt compressor (#36, which supersedes #16's mechanism).

Two known load-bearing facts about the pipeline:

1. **`claude -p` has unknown hang triggers.** Sanitizer covers known patterns; real mechanism is byte-count (#36). HTTPLog.swift has a separate small-prompt structural trigger (#34) that's *not* byte-size related — orthogonal.
2. **Sanitizer/compressor split.** `_sanitize_for_claude` strips trailers as cheap belt-and-suspenders; the real fix is the size-aware compressor in #36.

## Visual output

Three viz stacks were prototyped in a now-deleted `viz-playground/` directory (Observable Framework, Vega-Lite, hand-rolled SVG). The **hand-rolled SVG** won the feel-test and was promoted in #40 to `antiquarian/render.py` + `antiquarian/render_data.py`. The other two stacks are gone.

The visual commitments — antiquarian broadsheet idiom, hatched lossy regions, oxide-red printer's-stamp accent, no library defaults, no CDN fonts — are locked in [`docs/visual-vocabulary.md`](visual-vocabulary.md). Update that doc *before* the renderer when changing a committed atom.

The broadsheet is static-complete by design — it says everything with JavaScript off and reads cleanly to assistive tech. Interactivity is additive: search, disclosure, and hover cards are progressive enhancement layered in the HTML wrapper around the static SVG atoms. Literal print-to-paper is a nice-to-have, not a requirement (#40 demoted 2026-07-01).

### How to render

```bash
uv run antiquarian render --repo /path/to/repo
```

Reads what `story` / `survey` already produced under `.antiquarian/` (cache.db + stories/) and writes a self-contained HTML page to `.antiquarian/render/index.html`. Does not call `claude -p` — pure transformation over data on disk.
