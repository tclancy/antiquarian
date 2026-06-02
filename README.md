# Antiquarian

> Software development is a forward Telephone game: requirements → conversations → specs → tickets → PRs → commits → code. Each hop loses signal. Antiquarian runs Telephone backwards.

Given the surviving artifacts of a codebase — commits, PR descriptions, code, TODOs, co-change patterns — Antiquarian reconstructs as much of the original signal as it can, and is honest about the parts that are gone forever.

The point isn't another git-history visualizer. The point is the **why**: why was this written, why did it survive a decade of churn, why is the `# TODO` from 2014 still there. The forward dev process compresses *why* out of the artifacts that persist. Antiquarian decompresses.

## Status

Early. The MVP `antiquarian story <file>`, `antiquarian survey`, and `antiquarian render` commands are shipping per-file and multi-file narratives plus a hand-rolled SVG broadsheet, passing eyeball-tests on three repos (`itguy`, `BetterBlue`, `comictagger`). The multi-pass codebase examination ("Parliament of Owls") is in progress.

Local-first by design — narrative synthesis goes through `claude -p` rather than burning API credits while the idea is still proving itself out.

## Getting started

### Use it against your own repos

`uv tool install` puts the `antiquarian` CLI on your PATH so it works from any directory. Use `--editable` while the project is still moving so a `git pull` here lights up in every checkout you run it against:

```bash
uv tool install --editable /path/to/this/checkout
```

Then, from any repo:

```bash
cd /path/to/some/other/repo

antiquarian story src/main.py        # per-file narrative
antiquarian survey                   # multi-file synthesis
antiquarian render                   # broadsheet HTML
```

Output lands under `<that-repo>/.antiquarian/`. After a `git pull` here, `uv tool upgrade antiquarian` if entry-point shims got stale (rarely needed for editable installs).

### Build a gallery of broadsheets

A *gallery* is a precomputed, self-contained site of broadsheets for several repos — the free, no-auth artifact a curious visitor sees before running anything (the #86 "Option B" adoption surface). It is driven by a `gallery.toml` manifest (see [`examples/gallery.toml`](examples/gallery.toml)):

```bash
# Survey + render every repo in the manifest into its render_dir.
# Clones each repo (full history — antiquarian mines it), then prints a cost
# estimate and asks before spending any tokens. Idempotent: already-rendered
# repos are skipped unless --force.
antiquarian gallery generate -m gallery.toml          # interactive confirm
antiquarian gallery generate -m gallery.toml --yes    # headless (CI)

# Assemble the rendered broadsheets into one illuminated Pages site.
antiquarian gallery build -m gallery.toml -o gallery/
```

`generate` is the expensive, API-key half (one `claude -p` call per file per repo); `build` is free and idempotent. Splitting them keeps the cheap assembly testable and the one-time generation cost something you run deliberately, not on every push.

### Or work on Antiquarian itself

```bash
uv sync --all-groups
uv run pre-commit install
uv run pre-commit install --hook-type pre-push

uv run pytest
uv run antiquarian story path/to/some/file.py    # run against the repo you're in
```

`uv run` resolves against the *current directory's* venv — so `uv run antiquarian survey` only works from inside an antiquarian checkout that has the package installed in its venv. Use the `uv tool install` path above for anywhere else.

## Docs

| File | What it covers |
|------|----------------|
| [`docs/ethos.md`](docs/ethos.md) | Telephone-in-reverse, every-layer-is-approximation, voice rules — the lens every decision passes through. |
| [`docs/architecture.md`](docs/architecture.md) | File map, multi-pass design (Parliament of Owls), survey output structure, render pipeline. |
| [`docs/prior-art.md`](docs/prior-art.md) | Research findings on Mining Software Repositories, local LLM viability, and the Repowise evaluation that landed us on "build from scratch, informed by Repowise." |
| [`docs/visual-vocabulary.md`](docs/visual-vocabulary.md) | The commitments baked into the broadsheet renderer — lossy hatching, dual-axis timeline, palette, typography. |
| [`docs/notes.md`](docs/notes.md) | Warnings about AI-written corpora, future-idea backlog, candidate signals. |
| [`CLAUDE.md`](CLAUDE.md) | Agent-facing guide. Conventions, current Dispatch-bot status, what not to do. |
| [`examples/`](examples/) | Template snippets for automating Antiquarian against your repo — pre-push hook, GitHub Actions workflow. |

Working notes and the running session log live in Obsidian — these `docs/` files are the canon.

## License

AGPL-3.0. The reasoning is in `docs/ethos.md`.
