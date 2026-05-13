# Prior Art and the Repowise Evaluation

## The landscape

The space is more developed than expected. None of the existing tools quite do what Antiquarian wants — but several do parts of it well enough to learn from.

### Closest match: Repowise

[Repowise](https://github.com/repowise-dev/repowise) (AGPL-3.0) is an open-source codebase-intelligence platform: graph analysis, git intelligence, documentation intelligence, decision intelligence. Exposes MCP tools (`get_overview`, `get_context`, `get_risk`, `get_why`, `search_codebase`). Benchmarks claim 36% cost reduction and 89% fewer file reads when augmenting Claude Code.

This is close to what Antiquarian wants to be. The biggest difference: Repowise is a dev-tool augmentation layer, not a historian narrative.

### Other notable tools

- **[Code Archeologist](https://github.com/MS-Teja/code-archeologist)** — builds a "genetic tree" of codebase ancestry, vector-embedded semantic analysis, answers natural-language questions about codebase history.
- **Hercules** (Go) — fast burndown stats, developer insights, file coupling, temporal patterns.
- **git-of-theseus** — code churn visualization over time.
- **PyDriller** (Python) — programmatic git mining library, purpose-built for research. (We use this.)

### The academic field

Mining Software Repositories (MSR) has been a conference since 2005. Active research areas: co-change analysis, design rationale extraction, commit message generation, refactoring detection. Key finding from the literature: **automated end-to-end design rationale extraction is "emerging but insufficient"** — the gap Tom identified is real and unsolved.

## Local LLM viability

Concretely viable on a 2026-era Mac.

| Model | Size (quantized) | Quality | Speed (CPU) | Speed (GPU) |
|-------|-----------------|---------|-------------|-------------|
| DeepSeek Coder 6.7B Q4 | ~4GB | Good for diff summarization | 12-18 tok/s | 30-50 tok/s |
| DeepSeek Coder V2 (MoE) | Larger | Near GPT-4 on code | Slower | Fast w/ VRAM |
| Qwen 2.5 Coder 32B | ~18GB | Excellent | Slow on CPU | Needs 16GB VRAM |
| Phi 3 Mini | ~2.7GB | Reasonable | Fastest | Fast |

For a 200-line diff summarization: 5-15 seconds per commit on CPU, 2-6 seconds on GPU. For a 1k-commit repo: ~1-2 hours on CPU first run, then incremental.

The realized pragmatic choice: shell out to `claude -p` rather than run a local model. Cheaper than the API; richer than a 7B local. Reconsider when the Ollama path becomes a clear win.

## The Repowise evaluation (2026-05-12)

We installed Repowise 0.8.0 and ran it against `itguy` (733 Python files, 208 commits, 2 contributors). Two modes: `--index-only` (no LLM cost) and `--test-run --provider mock` (structure only).

### What Repowise does well

**Graph analysis ("What Are We?"):**
- 1,028 nodes, 2,552 edges from 46 source files in 9 seconds.
- PageRank + betweenness centrality identifies critical files.
- Leiden community detection found 15 code communities with cohesion scores.

**Git intelligence (partial "Where Do We Come From?"):**
- Hotspot detection at 97th-percentile churn for the right file.
- Co-change analysis: surfaced real coupling.
- Ownership: accurate bus-factor of 1-2.
- Significant-commit extraction, commit categorization, temporal patterns.

**Dead-code detection:**
- 21 unused exports, ~729 deletable lines.
- Caveat: false positives on dynamically registered CLI subcommands (Click decorators that Repowise can't see).

**MCP integration:**
- 7 well-designed tools.
- Auto-generates `CLAUDE.md` with hotspots and tech stack.

### What Repowise does *not* do (the Antiquarian gaps)

1. **No temporal narrative.** Repowise answers "what does this code do now?" not "how did this code get here and why?" Has commit lists, no synthesis.
2. **Decision archaeology is weak in practice.** `get_why()` returned **0 decisions** on `itguy` — only detects inline `# WHY:` / `# DECISION:` markers (nobody writes these), README/doc files (static), and "significant" commits (stores messages, doesn't reconstruct reasoning). Doesn't mine GitHub at all.
3. **No drift detection.** Can't tell how a function's purpose changed over time.
4. **No TODO/FIXME aging.**
5. **No author knowledge graphs.** Has ownership percentages but not "when did knowledge leave the team."
6. **LLM-dependent for useful output.** Without an API key or Ollama, the most valuable features produce nothing.
7. **Aggressive global modifications on init.** Touches `~/.claude/settings.json`, Claude Desktop config, and project `.claude/CLAUDE.md` with no opt-out. We cleaned these up after evaluation.

### Gauguin-question coverage

| Question | Repowise coverage | Antiquarian gap |
|----------|-------------------|-----------------|
| **Where Do We Come From?** | Commit lists, co-change stats, ownership over time | **No narrative synthesis, no drift detection, no external signal mining** |
| **What Are We?** | Graph structure, current-state docs, dead code | **Decision records only from inline markers — misses 99% of real decisions** |
| **Where Are We Going?** | Dead-code hints, ungoverned-hotspot warnings | **No convention extraction, no pattern enforcement, no Chesterton's Fence** |

## Build from scratch, informed by Repowise

Three options on the table:

| Option | Approach | Pro | Con |
|--------|----------|-----|-----|
| **A: Fork Repowise** | Add temporal features to Repowise codebase | Saves rebuilding graph layer | Fights the architecture; 117 dependencies; AGPL viral |
| **B: Layer on Repowise** | Use Repowise for structure, build narrative engine separately | Clean separation; leverage what works | Two tools to maintain |
| **C: Build from scratch** | PyDriller + tree-sitter + Ollama/`claude -p` + SQLite | Purpose-built for temporal narrative | Rebuilds some graph analysis |

**Decision: Option C, informed by Repowise.**

The features Antiquarian needs most — narrative synthesis, decision archaeology from PRs/issues, drift detection — require fundamentally different data pipelines, not incremental additions. The graph analysis Repowise does well (PageRank, community detection) replicates in ~200 lines of `networkx` if and when we need it.

### What to steal from Repowise

1. Co-change detection algorithm — time-windowed commit overlap with decay.
2. Hotspot formula — churn × complexity with temporal weighting.
3. Community detection via Leiden algorithm on the dependency graph.
4. The MCP tool API design — 7 focused tools is a good interface.

### Significant Commit heuristics — the deeper version

Tom's insight on top of Repowise's "significant commit" idea: significance is **relative to a repo's messaging baseline**. A 1,000-word commit message is significant where the norm is two-line summaries; in a codebase where every commit gets a 1,000-word self-justification, a *terse* two-line message is significant. This is the per-repo messaging-pattern detector (#2 — broken into discrete implementation issues).

And significance varies *within* a repo: by author (different baselines), by region (different ownership), and by time period (different teams). This is why the multi-pass architecture matters — the same SC detector needs to score against per-author, per-region, and per-period baselines, not just repo-wide.

### File paths in commit messages

Mostly ignore them when scoring significance. A 100-word commit message in a codebase that normally writes two-line summaries is significant — but not if 90 of those words are file paths. References to files that *aren't* in the commit, on the other hand, are highly valuable (cross-file context is hard to find).
