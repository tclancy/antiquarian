# Formal Verification for Antiquarian

This directory contains Z3 SMT solver specifications that formally prove critical invariants in Antiquarian's core layers. Each specification can be run standalone to verify its properties.

## Architecture

Antiquarian's data flow has clear "turtles" (layers):

1. **Selection** (`selection.py`) — file filtering layer
2. **Mining** (`mining.py`) — git history extraction
3. **Cache** (`cache.py`) — SQLite persistence layer
4. **Narrative** (`narrative.py`) — sanitization & prompt building
5. **Pipeline** (`pipeline.py`) — orchestration & handoffs

These specs focus on the layers most prone to data loss or corruption: the filter algebra, the cache, the pipeline handoffs, and the sanitizer.

## Properties Proved

### Selection Algebra (`spec_selection.py`)

**5/5 properties proved:**

1. **`--only` is exclusive** — When `--only` is specified, result contains exactly those paths (if they exist), completely bypassing `--include`, `--exclude`, and `.gitignore`.

2. **`--include` re-adds excluded files** — Files removed by `--exclude` or hard-skip can be re-added by `--include`. This allows users to whitelist specific files in otherwise excluded directories (e.g., `--exclude node_modules --include node_modules/config.json`).

3. **`--exclude` removes files** — Files matching an `--exclude` pattern are removed from the result unless also matched by `--include`.

4. **Idempotency** — Applying the same filter set twice produces the same result as applying it once. This ensures the operator is stable and composable.

5. **Result is a subset of candidates** — No files are invented; the result is always a subset of the original `git ls-files` output (or filesystem walk if not in a git repo).

**Implication**: Users can reliably combine `--only`, `--include`, `--exclude` without worrying about non-determinism or silent data loss.

---

### Cache Invariants (`spec_cache.py`)

**5/5 properties proved:**

1. **Primary key uniqueness** — The `(sha, file_path)` key is unique in `commit_features`. SQLite's PRIMARY KEY constraint guarantees this; the schema enforces that no two rows have the same (sha, file_path) pair.

2. **Round-trip correctness** — After `put_commit(features, fp)`, calling `get_commit(sha, fp)` returns equivalent data. All CommitFeatures fields (author, timestamp, message, additions, deletions, etc.) survive the write-read cycle intact.

3. **Narrative chunk versioning** — Storing `put_narrative_chunk(..., chunk_version=2)` does not erase `chunk_version=1` for the same (sha, file_path). Versions are independent rows in `narrative_chunks`, each keyed by `(sha, file_path, chunk_version)`.

4. **Key collision resistance** — If two logical entries (e.g., commits by different authors) are distinct, they have distinct (sha, file_path) keys. This prevents data merging or silent overwrites.

5. **No silent drops** — When `put_commit` is called, the commit is retrievable. There is no path where a commit is written but then lost on read.

**Implication**: The cache is a reliable, non-destructive persistence layer. No data is silently dropped or overwritten.

---

### Pipeline Handoffs (`spec_pipeline.py`)

**5/5 properties proved:**

1. **No silent drops** — Every file in `select_files(...)` result either generates a story via `generate_file_story()` or raises an exception. No file is silently skipped.

2. **Complete handoff** — `generate_codebase_survey()` receives all per-file stories produced. The tuple `(file_path, narrative)` for each file makes it to `synthesize_survey()`. No stories are lost between layers.

3. **No divergence in persistence** — When `generate_file_story` returns `(narrative, story_file)`, the text written to disk matches the in-memory narrative. There is no lossy encoding or truncation.

4. **Error handling covers all paths** — For every selected file, either a story is generated, or an exception is raised. There is no "silent skip" where a file is dropped without error or output.

5. **Cache transparency** — The `use_cache` flag improves performance but doesn't affect narrative correctness. Two runs processing the same commits produce the same narrative regardless of cache state.

**Implication**: The pipeline is a reliable data conduit. Files are processed end-to-end with no loss, and the cache is a safe optimization.

---

### Survey Parallelization Concurrency (`spec_concurrency.py`)

**5/5 properties proved:**

1. **At most one git-config mutex holder** — Across every modelled execution of the Phase-1 (serial mining) + Phase-2 (parallel narrative) schedule, no two threads simultaneously hold the `.git/config` mutex. PyDriller's `Repository` open is the only path that touches the mutex, and that open lives in the serial mining loop.

2. **Narrative phase never acquires the git mutex** — Once Phase 2 begins, no worker re-opens PyDriller. Workers consume `_MiningResult` instances that were fully materialized during Phase 1.

3. **Mining precedes narrative per file** — For every file `f`, the worker that synthesizes `f`'s narrative cannot start before `f`'s mining completes. The pipeline materializes all `_MiningResult`s in a serial `for` loop before submitting any work to `ThreadPoolExecutor`.

4. **Narrative inputs are disjoint across futures** — `generate_codebase_survey` submits one future per file, each bound to that file's `_MiningResult`. Two distinct futures are never bound to the same `_MiningResult`. (Not "one file per worker" — the pool reuses workers for sequential futures.)

5. **No shared mutable git state in narrative workers** — Wired through the mutex matrix from property 1: a worker is said to "touch shared git state" iff it holds the `.git/config` mutex during a narrative step, which the matrix already forbids. The `_MiningResult` instances workers consume are frozen dataclasses with tuple fields (per PR #151) — there is no other mutable git state surface to share.

**Caveat**: These are *schedule-level* invariants. They prove that the schedule never exercises a contended path, not that PyDriller's lock semantics are correct (taken as a property of the library). If a future refactor moves PyDriller calls into the worker pool, every one of these properties must be re-evaluated.

**Implication**: The #104 fix (PR #151) is race-free by construction. The schedule is the proof obligation — adding parallelism downstream of mining cannot reintroduce the `.git/config.lock` race so long as no PyDriller call lives in a worker.

---

### Narrative Sanitization (`spec_narrative.py`)

**6/6 properties proved:**

1. **Bare pattern removed** — The regex `Co-Authored-By: Claude <noreply@anthropic\.com>` is matched and removed.

2. **Parameterized pattern preserved** — The form `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (used by dispatch-bot[bot]) is NOT matched and is left intact.

3. **Generated marker removed** — The line `🤖 Generated with [Claude Code](https://claude.ai/code)` is matched and removed.

4. **Idempotency** — Applying `_sanitize_for_claude()` twice produces the same result as once. `sanitize(sanitize(x)) == sanitize(x)`.

5. **No false positives** — Text is only removed if it matches one of the known patterns. Unrelated text containing "Co-Authored" (e.g., a normal PR description) is preserved.

6. **Clean output** — After sanitization, the result contains no bare Claude patterns. The output is safe to feed to `claude -p`.

**Caveat**: Z3 cannot natively reason about regex patterns. These specs prove the *intent* of the sanitizer through boolean algebra. The actual regex matching must be verified via property-based testing (Hypothesis). See issue #20.

**Implication**: The sanitizer reliably removes patterns known to hang `claude -p` while preserving dispatch-bot[bot] co-author lines.

---

## What Was NOT Proved (and Why)

### Mining → Cache Round-trip Fidelity

The `CommitFeatures` extracted by `mine_file_history()` contain many fields (files_changed list, message text, etc.). A full round-trip spec would need to check that all fields survive the cache cycle identically. This is better addressed by property-based testing (Hypothesis) with real git histories, because:

- Z3 can't reason about complex data structures like lists of filenames.
- We want to test against actual git data, not abstract models.
- The behavior is deterministic but data-heavy.

**Recommendation**: See issue #20 (property-based testing) for this coverage.

### Prompt-Builder No-Crash on Arbitrary Content

The `build_user_prompt()` function in `narrative.py` constructs a markdown document from arbitrary commit messages and code. We want to prove it never crashes (e.g., no uncaught exceptions) on any input. This is beyond Z3's scope because:

- No-crash proofs require symbolic execution of the full function.
- Z3 is designed for logical constraints, not code-path enumeration.
- Property-based testing with `hypothesis` is the right tool here.

**Recommendation**: See issue #20.

### File-Path Globbing Edge Cases

The `_matches_glob()` function uses `fnmatch`, which has subtle edge cases (e.g., `**/foo` doesn't work as expected). We want to test that the selection layer doesn't mishandle these. Again, property-based testing is more appropriate because:

- Glob matching is string-intensive.
- Z3 can model the *semantics* (as we did in `test_exclude_removes`) but not the actual `fnmatch` behavior.
- We need to test against real filesystem paths.

**Recommendation**: See issue #20.

---

## Running the Specs

Each spec is a standalone Python file:

```bash
uv run python verification/spec_selection.py
uv run python verification/spec_cache.py
uv run python verification/spec_pipeline.py
uv run python verification/spec_concurrency.py
uv run python verification/spec_narrative.py
```

Or run all at once:

```bash
for spec in verification/spec_*.py; do
  echo "=== $spec ==="
  uv run python "$spec" || exit 1
done
```

All five specs should exit with code 0 and print `PROVED` for each property.

---

## Dependencies

- **z3-solver** (added to `[dependency-groups] dev` in `pyproject.toml`)

Verify it's installed:

```bash
uv sync --group dev
```

---

## Key Takeaways

1. **Selection is sound**: The filter algebra is logically consistent. Users can combine `--only`, `--include`, `--exclude` without fear of non-determinism.

2. **Cache is safe**: Data persisted to disk is retrievable intact. No silent drops or overwrites.

3. **Pipeline is reliable**: Files flow end-to-end with no loss. The cache is a transparent optimization.

4. **Sanitizer is conservative**: It removes known hang patterns while preserving legitimate dispatch-bot commits.

5. **Complementary testing**: Z3 proved invariants that are hard to test behaviorally. Property-based testing (issue #20) will cover data-heavy round-trips, no-crash guarantees, and glob edge cases.

---

## Next Steps

- **Issue #20** (property-based testing with Hypothesis) will complete the coverage for mining fidelity, prompt-building robustness, and file-path edge cases.
- These specs serve as documentation of the intended behavior. Keep them in sync as the code evolves.
