# Antiquarian — agent guide

The story of a codebase over time. Reconstruct the **why** behind code from the artifacts the forward dev process leaves behind: commits, PR descriptions, TODOs, co-change patterns.

Authoritative docs live at `/Users/tom/Documents/notes/tclancy/Dispatch/Projects/Antiquarian/` (Obsidian). Read those first when planning anything structural — issue **#60** ports them into `/docs` but until that lands, the Obsidian folder is canonical. Most recent state-of-the-world: `CONTINUATION.md` in that folder.

## Project ethos (the lens every decision passes through)

- **Telephone in reverse.** Forward dev compresses requirements → conversations → tickets → PRs → commits → code. Each hop loses signal. Antiquarian decompresses. Some loss is permanent — say so rather than confabulate.
- **Every layer is approximation.** The source signal was already approximate before any compression. `# FIXME` is often the most honest line in the file — an admission, not a note.
- **Confidence is a first-class output.** "Appears to have," "the evidence suggests," "the channel went dark here" — these are valid narrative outputs. Hallucinated certainty is worse than acknowledged ignorance.
- **Triangulation beats single-source.** Commit + PR + co-changed test + nearby TODO is stronger than any one alone.
- **Lossy regions are themselves signal.** Foreground them; don't paper over.
- **Assume good intentions.** Banned vocab in narrative output: `blame / fault / culprit / should have / mistake`. Required voice: `introduced / wrote / chose / appears to have / the evidence suggests`. Hemingway, not LinkedIn.
- **Build from scratch, informed by Repowise.** Don't fork. See `06 - Repowise Evaluation.md` for the why.

## Architecture

```
antiquarian/
├── cli.py          # Typer entry points: story, survey, files
├── pipeline.py     # Orchestration (generate_file_story, generate_codebase_survey)
├── mining.py       # PyDriller — uses `git log --follow` (NO --reverse, see #13)
├── prs.py          # gh CLI integration for PR enrichment
├── narrative.py    # `claude -p` subprocess + sanitizer (_sanitize_for_claude)
├── selection.py    # File selection (allow/block, --include/--exclude/--only)
├── cache.py        # SQLite at <repo>/.antiquarian/cache.db; key=(commit_sha, file_path)
├── profile.py      # build_author_baselines (#49), regions to come (#52)
├── todos.py        # TODO/FIXME extraction via git blame
├── models.py       # CommitFeatures, TodoAnnotation, RepoProfile, AuthorBaseline, …
└── backends.py     # Git backend abstraction

verification/       # Z3 specs — 21 invariants proven (#22)
tests/              # pytest + Hypothesis (profiles: dev=30, ci=100, fuzz=1k, nightly=10k)
viz-playground/     # Visualization spike (#8/#11) — hand-rolled SVG won; #40 promotes it
```

## Survey output structure

Synthesis produces five sections: (1) Files surveyed, (2) Cross-file arcs, (3) Coupling/divergence, (4) Where the channel went dark, (5) Dramatis Personae (#50, PR #56 pending).

## Commands

```bash
uv run antiquarian story <file>           # MVP per-file narrative
uv run antiquarian survey                 # multi-file synthesis
uv run antiquarian files                  # show file selection
uv run pytest                             # default Hypothesis profile=dev
HYPOTHESIS_PROFILE=ci uv run pytest       # CI profile
uv run pre-commit run --all-files         # ruff + standard hooks
```

## Working conventions

- **Python 3.13+, uv only.** Never `pip` / `poetry`. Use `uv add` / `uv run`.
- **Pre-commit + pre-push are enforced.** After clone: `uv run pre-commit install && uv run pre-commit install --hook-type pre-push`. The pre-push hook runs `pytest` — bots and humans must pass tests before pushing (closes #59).
- **Voice rules apply to commits and PR bodies too**, not just narrative output. No "fixed dumb bug" energy.
- **Branch prefix `claude/`** for agent work. Tom uses unprefixed branches.
- **Mint dispatch-bot token before any GitHub op** (`eval "$(dispatch mint-token 2>/dev/null)" || true`) so attribution stays clean.
- **Cache is keyed by `(commit_sha, file_path)`.** Schema changes need migrations — see PR #57 for the pattern.
- **Project-native UIDs alongside backend identifiers** (git SHA, jj change-id) — added day-one, painful to retrofit.

## Dispatch bot status

**On hold for unsupervised PR opening (2026-05-13).** Exception: clean up the two open bot PRs (**#56** Dramatis Personae, **#58** Statistical SC detector). Subagents dispatched inside interactive sessions are still fair game. The project doc's frontmatter (`The Antiquarian or Archivist.md` in Obsidian) is the source of truth on this status.

## Known load-bearing facts

1. **`claude -p` has unknown hang triggers.** PR #17's sanitizer covers known patterns; the real mechanism is **byte-count** (see #36 — supersedes #16). HTTPLog.swift has a separate small-prompt structural trigger (#34) that is not byte-size related.
2. **Sanitizer/compressor split.** `_sanitize_for_claude` strips trailers (cheap belt-and-suspenders); the real fix is a size-aware prompt compressor — that's #36.
3. **Three eyeball-test repos** for empirical validation: `itguy`, `BetterBlue`, `comictagger`. Tom adds `groundenergy` once he digs up the archive.

## What NOT to do

- Don't fork Repowise — see `06 - Repowise Evaluation.md`.
- Don't precompute "divisiveness" or "tone of voice" metrics — let synthesis derive them from prose. Punted deliberately from #2.
- Don't make Pass 2 depend on Pass 3 of the multi-pass design (#54) — they stand alone.
- Don't add interactive features to the broadsheet SVG (#40) — print-first.
- Don't treat any single artifact as ground truth — that's the whole project thesis.
- Don't strip `# TODO` / `# FIXME` from narrative input. They carry disproportionate signal weight.
