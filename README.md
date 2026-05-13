# Antiquarian

> Software development is a forward Telephone game: requirements → conversations → specs → tickets → PRs → commits → code. Each hop loses signal. Antiquarian runs Telephone backwards.

Given the surviving artifacts of a codebase — commits, PR descriptions, code, TODOs, co-change patterns — Antiquarian reconstructs as much of the original signal as it can, and is honest about the parts that are gone forever.

The point isn't another git-history visualizer. The point is the **why**: why was this written, why did it survive a decade of churn, why is the `# TODO` from 2014 still there. The forward dev process compresses *why* out of the artifacts that persist. Antiquarian decompresses.

## Status

Early. The MVP `antiquarian story <file>` and `antiquarian survey` commands are shipping per-file and multi-file narratives that pass eyeball-tests on three repos (`itguy`, `BetterBlue`, `comictagger`). The multi-pass codebase examination ("Parliament of Owls") and the hand-rolled SVG render-out are roadmap.

Local-first by design — narrative synthesis goes through `claude -p` rather than burning API credits while the idea is still proving itself out.

## Getting started

```bash
uv sync --all-groups
uv run pre-commit install
uv run pre-commit install --hook-type pre-push

uv run antiquarian story path/to/some/file.py
uv run antiquarian survey
uv run pytest
```

## Docs

| File | What it covers |
|------|----------------|
| [`docs/ethos.md`](docs/ethos.md) | Telephone-in-reverse, every-layer-is-approximation, voice rules — the lens every decision passes through. |
| [`docs/architecture.md`](docs/architecture.md) | File map, multi-pass design (Parliament of Owls), survey output structure. |
| [`docs/prior-art.md`](docs/prior-art.md) | Research findings on Mining Software Repositories, local LLM viability, and the Repowise evaluation that landed us on "build from scratch, informed by Repowise." |
| [`docs/notes.md`](docs/notes.md) | Warnings about AI-written corpora, future-idea backlog, candidate signals. |
| [`CLAUDE.md`](CLAUDE.md) | Agent-facing guide. Conventions, current Dispatch-bot status, what not to do. |

Working notes and the running session log live in Obsidian — these `docs/` files are the canon.

## License

AGPL-3.0. The reasoning is in `docs/ethos.md`.
