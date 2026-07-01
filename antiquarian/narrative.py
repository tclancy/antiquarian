"""Synthesize narrative output via `claude -p` with the Antiquarian system prompt."""

from __future__ import annotations

import random
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Sequence

from antiquarian.models import (
    AuthorBaseline,
    CoChange,
    CommitFeatures,
    RegionDefinition,
    TodoAnnotation,
)

if TYPE_CHECKING:
    from antiquarian.backends import NarrativeBackend


def _noop(_msg: str) -> None:
    pass


def _run_claude_p(
    args: Sequence[str],
    user_prompt: str,
    timeout_seconds: int,
    *,
    max_attempts: int = 3,
    max_calledprocess_attempts: int = 2,
    base_backoff_seconds: float = 5.0,
    log: Callable[[str], None] = _noop,
    sleep: Callable[[float], None] = time.sleep,
) -> subprocess.CompletedProcess[str]:
    """Run ``claude -p`` with retry on transient failures.

    Retries both ``subprocess.TimeoutExpired`` (#31) and
    ``subprocess.CalledProcessError`` (#39). The #31 design assumed non-zero
    exits were permanent; real-world evidence on a tkc survey contradicted
    that — the same prompt returned exit 1 once then exit 0 on the next
    invocation — so we retry exit failures too, with a lower attempt cap
    since they're more likely to be permanent than timeouts.

    Backoff is exponential with up to 20% jitter to avoid lockstep retries
    against a momentarily degraded upstream.

    Caps:
    - ``max_attempts`` — total attempts for ``TimeoutExpired`` (default 3)
    - ``max_calledprocess_attempts`` — total attempts for ``CalledProcessError``
      (default 2). Lower because a real permanent failure (bad prompt, auth,
      etc.) shouldn't burn three calls before surfacing.
    """
    timeout_attempt = 0
    cpe_attempt = 0
    while True:
        try:
            return subprocess.run(
                list(args),
                input=user_prompt,
                text=True,
                capture_output=True,
                check=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timeout_attempt += 1
            if timeout_attempt < max_attempts:
                delay = base_backoff_seconds * (3 ** (timeout_attempt - 1))
                wait = delay + random.uniform(0, delay * 0.2)
                log(
                    f"[narrative] claude -p timed out "
                    f"(timeout attempt {timeout_attempt}/{max_attempts}); "
                    f"retrying in {wait:.1f}s"
                )
                sleep(wait)
            else:
                log(
                    f"[narrative] claude -p timed out on all "
                    f"{max_attempts} attempts; giving up"
                )
                raise
        except subprocess.CalledProcessError as e:
            cpe_attempt += 1
            if cpe_attempt < max_calledprocess_attempts:
                delay = base_backoff_seconds * (3 ** (cpe_attempt - 1))
                wait = delay + random.uniform(0, delay * 0.2)
                log(
                    f"[narrative] claude -p exited {e.returncode} "
                    f"(exit attempt {cpe_attempt}/{max_calledprocess_attempts}); "
                    f"retrying in {wait:.1f}s"
                )
                sleep(wait)
            else:
                log(
                    f"[narrative] claude -p exited {e.returncode} on all "
                    f"{max_calledprocess_attempts} attempts; giving up"
                )
                raise


# Two patterns the sanitizer removes from commit messages and PR bodies before
# they enter the prompt. Strip at prompt-build time only — the cache keeps the
# original message intact.
#
# Original framing (#16): "these patterns hang claude -p." Later experimental
# work (#16 wrap-up, 2026-05-12) found this was wrong. A size-matched control
# — same prompt, same position, 103 bytes of innocuous filler instead of the
# trailers — hangs at the same rate as the unsanitized version, while the
# sanitized (smaller) prompt never hangs. The sanitizer's real mechanism is
# byte-count reduction; the trailers were coincidental content in the bytes
# that happened to push Account.swift's prompt over the threshold.
#
# The proper size-aware compressor is now ``build_user_prompt``'s phase-2-onwards
# logic (#36) — that's the load-bearing fix. This sanitizer is kept as cheap
# belt-and-suspenders: the trailers carry zero historian value, so stripping
# them is free byte savings before the compressor even has to think about
# dropping commits. Don't add new patterns here assuming specific content
# triggers anything — file-size is what matters.
_CLAUDE_HANG_PATTERNS = [
    re.compile(r"🤖 Generated with \[Claude Code\]\(https://claude\.ai/code\)\s*"),
    re.compile(r"Co-Authored-By: Claude <noreply@anthropic\.com>\s*"),
]


def _sanitize_for_claude(text: str) -> str:
    """Strip two trailer lines from commit/PR content (legacy of #16).

    Originally believed to fix a content-driven hang in ``claude -p``; later
    shown to work via byte-count reduction (see #16 wrap-up). #36's
    size-aware compressor is now the load-bearing fix; this sanitizer
    survives as cheap belt-and-suspenders — the trailers carry zero
    historian value, so stripping them is free byte savings before the
    compressor has to start dropping commits.

    The parameterized form (``Co-Authored-By: Claude Opus 4.7 (1M context)
    <…>`` used by ``dispatch-bot[bot]`` commits) is intentionally preserved
    — it's distinguishable from the bare form and the experiment in #16
    showed pattern identity isn't load-bearing anyway.
    """
    for pat in _CLAUDE_HANG_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


# First layer of the #36 size-aware compressor. Commit messages longer than
# this cap get truncated to first-paragraph plus a "[…N more chars truncated]"
# tail. The cap is calibrated to "release-notes / squashed-merge body" — the
# threshold where the marginal byte is almost always lower-signal than the
# bytes that come before it. The historian's voice rules already treat the
# first line/paragraph as the most trustworthy part of any commit message;
# this aligns the prompt with that bias.
_COMMIT_MESSAGE_TRUNCATE_AT = 500


def _compress_message(text: str, max_chars: int = _COMMIT_MESSAGE_TRUNCATE_AT) -> str:
    """Truncate a commit/PR message to ``max_chars`` with a visible tail.

    Preserves the first paragraph intact when possible. If even the first
    paragraph exceeds ``max_chars``, hard-truncate at ``max_chars``.
    """
    if len(text) <= max_chars:
        return text
    truncated_bytes = len(text) - max_chars
    first_para, sep, _ = text.partition("\n\n")
    if sep and len(first_para) <= max_chars:
        return f"{first_para}\n\n[…{truncated_bytes} more chars truncated]"
    return f"{text[:max_chars]}\n[…{truncated_bytes} more chars truncated]"


# #36 — second layer. The prompt as a whole gets a byte ceiling. If exceeded,
# we compress in priority order (drop low-info commits → tighten render →
# drop more commits in size order) until under the ceiling. Calibrated from
# the #16 wrap-up empirical data: Account.swift sanitized at 6,754 B succeeds
# 100% of the time; adding 103 B of innocuous content drops success to 20%.
# 6,500 leaves a small margin and is a starting knob — tune empirically as
# the corpus grows.
THRESHOLD_BYTES = 6500


@dataclass(frozen=True)
class _RenderConfig:
    """Per-stage knobs for how individual commits format into the prompt.

    Three tightening levels are defined below. The compressor walks from
    looser to tighter, returning the first variant that fits the byte ceiling.
    """

    message_max_chars: int
    pr_body_max_chars: int
    files_changed_max: int


_DEFAULT_RENDER = _RenderConfig(
    message_max_chars=_COMMIT_MESSAGE_TRUNCATE_AT,
    pr_body_max_chars=_COMMIT_MESSAGE_TRUNCATE_AT,
    files_changed_max=6,
)
_TIGHTER_RENDER = _RenderConfig(
    message_max_chars=200, pr_body_max_chars=200, files_changed_max=3
)
_TIGHTEST_RENDER = _RenderConfig(
    message_max_chars=80, pr_body_max_chars=80, files_changed_max=1
)


def _is_low_info_commit(c: CommitFeatures) -> bool:
    """Cheap heuristic: short message + tiny diff = likely typo / vendor bump / merge noise.

    Commits flagged here are the first to drop when the prompt is too large.
    Threshold values are conservative — false positives here just mean we
    keep a slightly larger prompt than needed; false negatives mean we drop
    a load-bearing commit and lose narrative signal. Prefer false positives.
    """
    return len(c.message.strip()) <= 30 and (c.additions + c.deletions) <= 5


def _commit_size_score(c: CommitFeatures) -> int:
    """Cheap proxy for information content; smaller is lower-information.

    Used in phase 3 to drop commits in size order when low-info dropping and
    tighter render configs aren't enough to fit the prompt under the ceiling.
    """
    return len(c.message) + c.additions + c.deletions


SYSTEM_PROMPT = """\
You are Antiquarian, a software historian.

Your task is to reconstruct the narrative of how a file came to be what it is today, from the surviving artifacts of its git history.

# Output instructions

Do not greet the user. Do not use any persona marker, playful prefix, or sign-off. Do not add any preamble like "Here is the report." Output ONLY the requested markdown document, beginning directly with the first heading.

# Core ethos: Telephone in reverse

Software development is a forward Telephone game — requirements lose signal as they pass through conversations, tickets, PRs, commits, and code. Each hop loses fidelity. You are running that Telephone backwards: given the surviving artifacts, reconstruct as much of the original WHY as you can.

You are NOT a summarizer. You are a historian. Anyone can list commits chronologically — git already does that. Your job is to synthesize a narrative that reveals decisions, evolutions, and rationale that no single artifact contains.

# Voice and stance

- Assume good intentions. The people who wrote this code were working under real constraints — time pressure, partial information, evolving requirements, changing teammates.
- BANNED vocabulary: "blame", "fault", "culprit", "bad code", "wrong choice", "should have", "mistake", "failed to"
- REQUIRED voice: "introduced", "wrote", "chose", "the constraints of the moment", "appears to have", "the evidence suggests"
- Confidence is a first-class output. When inferring intent from thin evidence, say so plainly. "This appears to have been driven by X" beats "This was driven by X" when the evidence is partial.
- When the channel is too lossy to recover the why, SAY SO. "The rationale here is unrecoverable from the surviving artifacts" is a valid and useful narrative element.

# Source reliability

Treat sources as a sliding scale of trust:
- Code that runs today: most trustworthy — it shipped, it works.
- Commit messages: written under pressure, often terse, can mislead.
- PR descriptions: usually richer than commits, still author-edited.
- TODO/FIXME annotations: ADMISSIONS — when present-self admitted future-self would inherit a problem. Often the most honest signal in surrounding code. Weight these accordingly.

Triangulate across sources. Do not treat any single artifact as ground truth.

# Output structure

Produce a markdown document with exactly these top-level sections, in this order:

## Origin
- When the file first appeared, who introduced it, what the file looked like at birth
- The apparent intent (with appropriate epistemic humility)
- 150-300 words

## Major arcs
- Group the file's evolution into 3-6 coherent arcs — NOT a commit list, a NARRATIVE
- For each arc: a short name, the time span, the decisive commits or PRs, what changed, and where recoverable, why
- 400-800 words total

## TODO/FIXME aging
- For each annotation currently in the file: the text, line number, age, who introduced it, the surrounding commit context
- Frame these as admissions from past-self — "messages from a better version of themselves" that may or may not have been kept
- If there are no annotations, OMIT this entire section. Do not produce a `## TODO/FIXME aging` heading or any prose under it. Absence of admissions is fine to leave silent — the reader can see the section is missing.

## People & ownership
- Who has worked on this file, when, how much
- Current bus factor and apparent knowledge distribution
- Any ownership transitions visible in the history
- 150-300 words

# What to avoid

- Don't list commits chronologically. Synthesize.
- Don't editorialize ("a beautiful refactor", "an interesting choice"). State evidence.
- Don't speculate beyond what the data supports.
- Don't pad. Brief and accurate beats long and vague.
"""


def _format_commit(
    c: CommitFeatures, index: int, config: _RenderConfig = _DEFAULT_RENDER
) -> str:
    pr_section = ""
    if c.pr_number is not None:
        pr_section = f"\n\n**PR #{c.pr_number}**"
        if c.pr_body:
            pr_body = _compress_message(
                _sanitize_for_claude(c.pr_body), config.pr_body_max_chars
            )
            pr_section += f"\n```\n{pr_body}\n```"
    files_summary = ", ".join(c.files_changed[: config.files_changed_max])
    if len(c.files_changed) > config.files_changed_max:
        files_summary += f", ... ({len(c.files_changed)} files total)"
    sha = c.git_sha or c.id
    message = _compress_message(
        _sanitize_for_claude(c.message), config.message_max_chars
    )
    return (
        f"### [{index}] {sha[:8]} — {c.timestamp.date().isoformat()} — {c.author}\n"
        f"+{c.additions}/-{c.deletions} across: {files_summary}\n\n"
        f"**Message:**\n```\n{message}\n```{pr_section}"
    )


def _format_todo(t: TodoAnnotation) -> str:
    return (
        f"- **{t.kind}** at line {t.line_number} ({t.age_days}d old) — "
        f"introduced by {t.introduced_by} in commit {t.introduced_commit[:8]}: "
        f"{t.text}"
    )


def _render_prompt(
    file_path: str,
    repo_name: str,
    kept: Sequence[CommitFeatures],
    todos: Sequence[TodoAnnotation],
    dropped_shas: Sequence[str],
    config: _RenderConfig,
    *,
    total_commits: int,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    sections = [
        "# Source data for the historian",
        "",
        f"**File:** `{file_path}`",
        f"**Repository:** {repo_name}",
        f"**Today's date:** {today}",
        f"**Commit count:** {total_commits}",
        f"**TODO/FIXME count currently in file:** {len(todos)}",
        "",
        "## Commit history (oldest first)",
        "",
    ]
    for i, c in enumerate(kept, start=1):
        sections.append(_format_commit(c, i, config))
        sections.append("")

    if dropped_shas:
        trail = ", ".join(s[:8] for s in dropped_shas)
        sections.append(
            f"**Also touched in (compressed for size, {len(dropped_shas)} "
            f"commit(s) elided):** {trail}"
        )
        sections.append("")

    sections.append("## TODO/FIXME annotations currently in the file")
    sections.append("")
    if todos:
        for t in todos:
            sections.append(_format_todo(t))
    else:
        sections.append("(none)")
    sections.append("")
    sections.append("---")
    sections.append("")
    sections.append(
        "Now write the historian's narrative per the structure in the system prompt. "
        "Begin directly with `## Origin` — no preamble."
    )

    return "\n".join(sections)


def build_user_prompt(
    file_path: str,
    repo_name: str,
    commits: Sequence[CommitFeatures],
    todos: Sequence[TodoAnnotation],
    *,
    threshold_bytes: int = THRESHOLD_BYTES,
) -> str:
    """Build a per-file historian prompt, compressing if it exceeds ``threshold_bytes``.

    Compression order (per issue #36):

    1. Default render — full message/PR body up to 500 chars, top 6 files. If
       the prompt fits the ceiling, return as-is.
    2. Drop low-info commits (short message + tiny diff) into an "Also touched"
       trail at the end of the commit history.
    3. Tighten the render config — shorter message/PR body caps, fewer files
       listed. Two stages: 200-char and 80-char.
    4. Drop the lowest-information commits one by one (by message length plus
       diff lines) until the prompt fits.

    Every dropped commit's SHA appears in the trail so traceability is
    preserved. The original ``Commit count`` line counts all commits, not
    just the ones rendered in detail.

    If even zero-commits-plus-trail under the tightest config exceeds the
    ceiling, returns the best-effort result rather than raising — the
    backstop is the retry/backoff in ``_run_claude_p``.
    """
    commits = list(commits)
    total = len(commits)

    # Phase 1: default render — try once before any compression.
    prompt = _render_prompt(
        file_path, repo_name, commits, todos, [], _DEFAULT_RENDER, total_commits=total
    )
    if len(prompt) <= threshold_bytes:
        return prompt

    # Phase 2: drop low-info commits into the trail.
    kept: list[CommitFeatures] = []
    dropped: list[str] = []
    for c in commits:
        if _is_low_info_commit(c):
            dropped.append(c.git_sha or c.id)
        else:
            kept.append(c)
    prompt = _render_prompt(
        file_path, repo_name, kept, todos, dropped, _DEFAULT_RENDER, total_commits=total
    )
    if len(prompt) <= threshold_bytes:
        return prompt

    # Phase 3: tighten the render config.
    for config in (_TIGHTER_RENDER, _TIGHTEST_RENDER):
        prompt = _render_prompt(
            file_path, repo_name, kept, todos, dropped, config, total_commits=total
        )
        if len(prompt) <= threshold_bytes:
            return prompt

    # Phase 4: drop more commits in size order, smallest first. Keep
    # chronological order in the rendered subset.
    dropped_set = set(dropped)
    size_order = sorted(kept, key=_commit_size_score)
    for c in size_order:
        sha_or_id = c.git_sha or c.id
        dropped_set.add(sha_or_id)
        dropped.append(sha_or_id)
        kept_in_order = [k for k in commits if (k.git_sha or k.id) not in dropped_set]
        prompt = _render_prompt(
            file_path,
            repo_name,
            kept_in_order,
            todos,
            dropped,
            _TIGHTEST_RENDER,
            total_commits=total,
        )
        if len(prompt) <= threshold_bytes:
            return prompt

    # Phase 5: even zero commits + trail under tightest config can't fit
    # (pathological: huge file_path / repo_name / todo list). Best-effort.
    return prompt


def synthesize_narrative(
    file_path: str,
    repo_name: str,
    commits: Sequence[CommitFeatures],
    todos: Sequence[TodoAnnotation],
    timeout_seconds: int = 300,
    *,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> str:
    """Build a per-file prompt and return the narrative markdown via ``backend``.

    ``backend`` defaults to ``ClaudePBackend`` (the ``claude -p`` subprocess
    wrapper). Pass a custom backend to use a different LLM provider; see
    ``antiquarian/backends.py``.
    """
    if backend is None:
        from antiquarian.backends import DEFAULT_BACKEND

        backend = DEFAULT_BACKEND
    user_prompt = build_user_prompt(file_path, repo_name, commits, todos)
    return backend.synthesize(
        SYSTEM_PROMPT, user_prompt, timeout_seconds=timeout_seconds, log=log
    )


SURVEY_SYSTEM_PROMPT = """\
You are Antiquarian, a software historian.

You have been given per-file historical narratives for several files from a single codebase. Your task is to write a HIGHER-LEVEL narrative — a codebase-scale story that the per-file narratives, in isolation, cannot tell.

# Output instructions

Do not greet the user. Do not use any persona marker, playful prefix, or sign-off. Do not add any preamble. Output ONLY the requested markdown document, beginning directly with the first heading.

# Core ethos: Telephone in reverse

Same as the per-file historian work: you are running Telephone backwards. Each per-file narrative is itself a triangulation across commits, PRs, and code. Your synthesis is a triangulation across narratives.

# What you are looking for (NOT a summary)

Anyone can read three file stories and concatenate them. Your job is to find:

- **Cross-file arcs** — a refactor, incident, or evolution that touched multiple files, even if each file's individual story tells only part of it
- **Divergences** — files that evolved together for a while then split apart, or files that stayed dormant while others were heavily worked
- **Coupling visible in co-evolution** — files that share dates of significant change, suggesting they are tied together architecturally or socially
- **Where the codebase's "real work" lives** — which files carry the load, which are scaffolding, which are vestigial
- **Lossy regions across the codebase** — places where the channel goes dark across multiple files at once (often signals team change, incident, or pivot)

# Voice and stance

Same discipline as the per-file work:

- Assume good intentions. People work under real constraints.
- BANNED: "blame", "fault", "culprit", "bad code", "wrong choice", "should have", "mistake", "failed to"
- REQUIRED: "introduced", "wrote", "chose", "the constraints of the moment", "appears to have", "the evidence suggests"
- Confidence is a first-class output. Hedge when the evidence is partial.
- When files appear UNRELATED, say so plainly. Do NOT invent a relationship to make the narrative tidier. "These files run on independent evolution tracks" is a valid and important finding.

# Output structure

Produce a markdown document with exactly these top-level sections, in this order:

## Files surveyed
- A compact list, one short line per file (the per-file stories have the detail; here just enough orientation)
- ~50-100 words total

## Cross-file arcs
- Named arcs that span multiple files
- For each: which files participate, time range, what happened, where the evidence is anchored
- If no cross-file arcs exist, say so plainly — and briefly identify what each file appears to be doing in isolation
- ~400-600 words

## Coupling and divergence
- Which files appear coupled in their evolution (co-changed, co-incident, share decisive moments)
- Which appear independent
- What the coupling pattern says about the codebase's architecture
- When **Regions** and **File co-change pairs** are supplied as input data below, use them as EVIDENCE for this section. Name the regions where the work concentrates ("most evolution happens in `accounts/` and `fuels/`"). Name the strongest co-change pairs by file. Don't print the raw pair counts as a table — weave them into prose ("`deploy.py` and `config.py` travel together; they share 12 of `deploy.py`'s 18 commits"). Inputs are evidence; the output is narrative.
- ~200-400 words

## Where the channel went dark
- Time windows where evidence thins out across multiple files at once
- Possible causes (team change, incident, pivot, dormancy) based on what evidence remains
- If the channel held throughout, say so
- ~100-200 words

## Dramatis Personae
- One entry per contributor, formatted as: **`Author Name`** — [apt but kind Hemingway-style descriptor]. [One or two sentences max.]
- The per-author baseline data (tenure, commit share, regions, typical hours/days, message stats) is provided below the per-file stories. Use it as EVIDENCE for the prose, not as output. Don't print "authored 27% of commits across 2014–2021." Say "the survivor who carried the project through three Django upgrades" and let the reader trust there's a metric behind the claim.
- Default to kind. "The survivor who carried the project through three Django upgrades" reads very differently from "the only person willing to touch this." Hemingway, not LinkedIn.
- Tell the truth. Kind ≠ flattering. If the evidence suggests someone was a one-PR-and-vanished onboarding contributor, say so plainly.
- Length cap: 2 sentences per contributor. Anything longer dilutes the format.
- If the repo has a single contributor, still write the section — a solo maintainer is a signal worth naming.
- ~50-200 words depending on contributor count

# What to avoid

- Don't restate the per-file narratives. Reference them, don't recap.
- Don't invent cross-file relationships to fill space.
- Don't editorialize ("a beautiful refactor", "interesting choice"). State evidence.
- Don't print raw author metrics (commit counts, percentages, hours). The Dramatis Personae uses metrics as evidence for prose descriptions, not as tabular output.
- Brevity beats padding.
"""


def _format_baseline(name: str, b: AuthorBaseline) -> str:
    days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    typical_days_str = ", ".join(days_map.get(d, str(d)) for d in b.typical_days)
    regions_str = ", ".join(
        f"{r} ({c})" for r, c in sorted(b.regions_touched.items(), key=lambda x: -x[1])
    )
    return (
        f"- **{name}**: {b.sample_size} commits over {b.tenure_days}d "
        f"({b.commit_share:.0%} share). "
        f"Typical hours {b.typical_hours[0]:02d}–{b.typical_hours[1]:02d}, "
        f"typical days: {typical_days_str}. "
        f"Median msg {b.median_message_len} chars, "
        f"median files/commit {b.median_files_changed}. "
        f"Regions: {regions_str}."
    )


# Cap on how many co-change pairs we include in the survey prompt. Even a
# small repo can produce hundreds; the LLM only needs the strongest signal.
# 20 is calibrated to "enough to spot the structural couplings" without
# pushing the survey prompt over its own size envelope.
_CO_CHANGE_TOP_N = 20


def _format_region(r: RegionDefinition) -> str:
    notable_str = ""
    if r.notable_evolutions:
        notable_count = len(r.notable_evolutions)
        sample = ", ".join(s[:8] for s in r.notable_evolutions[:3])
        notable_str = f" Notable evolutions ({notable_count}): {sample}."
    intro_str = ""
    if r.introduced_in:
        intro_str = f" Introduced in `{r.introduced_in[:8]}`."
    return f"- **{r.name}/** (prefix `{r.path_prefix}`).{intro_str}{notable_str}"


def _format_co_change(cc: CoChange) -> str:
    return (
        f"- `{cc.file_a}` ↔ `{cc.file_b}` — {cc.count} co-changes, "
        f"last on {cc.last_co_changed_at.date().isoformat()}"
    )


def build_survey_prompt(
    repo_name: str,
    file_stories: Sequence[tuple[str, str]],
    author_baselines: dict[str, AuthorBaseline] | None = None,
    regions: Sequence[RegionDefinition] | None = None,
    co_changes: Sequence[CoChange] | None = None,
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    sections = [
        "# Source data for the codebase survey",
        "",
        f"**Repository:** {repo_name}",
        f"**Today's date:** {today}",
        f"**Files surveyed:** {len(file_stories)}",
        "",
        "---",
        "",
    ]
    for i, (path, story) in enumerate(file_stories, start=1):
        sections.append(f"# [{i}] Per-file story: `{path}`")
        sections.append("")
        sections.append(story)
        sections.append("")
        sections.append("---")
        sections.append("")

    if author_baselines:
        sections.append("# Per-author baselines (for Dramatis Personae)")
        sections.append("")
        for name, baseline in sorted(
            author_baselines.items(), key=lambda x: -x[1].sample_size
        ):
            sections.append(_format_baseline(name, baseline))
        sections.append("")
        sections.append("---")
        sections.append("")

    if regions:
        sections.append("# Regions (top-level fiefdoms in this codebase)")
        sections.append("")
        for r in regions:
            sections.append(_format_region(r))
        sections.append("")
        sections.append("---")
        sections.append("")

    if co_changes:
        sections.append(f"# File co-change pairs (top {_CO_CHANGE_TOP_N} by count)")
        sections.append("")
        for cc in list(co_changes)[:_CO_CHANGE_TOP_N]:
            sections.append(_format_co_change(cc))
        sections.append("")
        sections.append("---")
        sections.append("")

    sections.append(
        "Now write the codebase-level synthesis per the structure in the system prompt. "
        "Begin directly with `## Files surveyed` — no preamble."
    )
    return "\n".join(sections)


def synthesize_survey(
    *,
    repo_name: str,
    file_stories: Sequence[tuple[str, str]],
    author_baselines: dict[str, AuthorBaseline] | None = None,
    regions: Sequence[RegionDefinition] | None = None,
    co_changes: Sequence[CoChange] | None = None,
    timeout_seconds: int = 300,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> str:
    """Build a survey prompt and return the codebase-level narrative via ``backend``.

    ``regions`` and ``co_changes`` (the Pass-3 structural signals from #52
    and #48) inform the **Coupling and divergence** section of the output
    when provided. They aren't separate output sections — they color the
    existing one. See ``SURVEY_SYSTEM_PROMPT`` for the prompt-level rules.
    """
    if backend is None:
        from antiquarian.backends import DEFAULT_BACKEND

        backend = DEFAULT_BACKEND
    user_prompt = build_survey_prompt(
        repo_name, file_stories, author_baselines, regions, co_changes
    )
    return backend.synthesize(
        SURVEY_SYSTEM_PROMPT, user_prompt, timeout_seconds=timeout_seconds, log=log
    )


# --- Act naming (#149 phase 2) ----------------------------------------------
# The structural Acts (profile.build_acts) come back nameless. This pass gives
# each an emergent name from the project's own evidence — the Act's span, size,
# the signals that opened it, its member arcs, and the survey for context. One
# claude -p call names the whole set so the names read as a coherent sequence.

ACT_NAMING_SYSTEM_PROMPT = """\
You are Antiquarian, a software historian.

You are given the structural "acts" of a codebase's life — a short, ordered sequence of movements derived from its commit record. Each act carries its date span, its size, the structural signals that opened it, and the named arcs (smaller story threads) that live within it. You may also be given an excerpt from the codebase survey for context.

Your task: name each act.

# What a name is

A SHORT phrase — 2 to 5 words — that captures what the movement WAS: its character, not a label. A name emerges from THIS project's own evidence.

- Do NOT force a fixed lifecycle vocabulary. No rote "Inception / Growth / Maturity / Decline". Two different projects should not receive the same names unless they genuinely earned them.
- Confidence is first-class. If an act's character is genuinely unclear from the evidence given, a plainer, quieter name is more honest than a dramatic invention. Do not confabulate a story the spans do not support.
- Assume good intentions. BANNED: blame, fault, culprit, should have, mistake, failed to. Hemingway, not LinkedIn — no marketing gloss, no exclamation.

# Output

Output ONLY one line per act, in the given order, formatted EXACTLY:

<index>: <name>

No preamble, no commentary, no markdown, no trailing notes. Example:

1: The First Cut
2: The Long Quiet
3: Coming Back to Life
"""


def build_act_naming_prompt(
    acts: Sequence[dict],
    arc_names_by_slug: dict[str, str] | None = None,
    survey_excerpt: str | None = None,
) -> str:
    """Compose the user prompt for :func:`synthesize_act_names`.

    Feeds the model each act's span, size, opening signals, and member-arc
    names (its scenes) — plus the survey excerpt as context when available.
    """
    arc_names_by_slug = arc_names_by_slug or {}
    lines = ["Here are the acts of this codebase's life, in order:\n"]
    for a in acts:
        start = a["start"][:10]
        end = a["end"][:10]
        signals = ", ".join(a.get("signals") or []) or "the opening of the record"
        arcs = [arc_names_by_slug.get(s, s) for s in a.get("arc_slugs") or []]
        arcs_str = "; ".join(arcs) if arcs else "no named arcs"
        lines.append(
            f"Act {a['index']} — {start} to {end} "
            f"({a['commit_count']} commits; opened by {signals}). "
            f"Arcs within: {arcs_str}."
        )
    if survey_excerpt:
        lines.append("\nSurvey context (for character, do not quote):\n")
        lines.append(survey_excerpt.strip())
    lines.append(f"\nName all {len(acts)} act(s), one per line, as `<index>: <name>`.")
    return "\n".join(lines)


# Tolerant of what models actually emit: an optional "Act " prefix (which the
# prompt itself uses, so the model tends to echo it), ) / . / : / dash
# separators, and surrounding markdown emphasis on the name.
_ACT_NAME_LINE_RE = re.compile(
    r"^\s*(?:act\s+)?(\d+)\s*[:.)\-—]\s*(.+?)\s*$", re.IGNORECASE
)


def synthesize_act_names(
    acts: Sequence[dict],
    arc_names_by_slug: dict[str, str] | None = None,
    survey_excerpt: str | None = None,
    *,
    timeout_seconds: int = 300,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> dict[str, str]:
    """Name each Act via ``backend``; return ``{act_signature: name}``.

    Keys are the deterministic Act boundary signature (``profile.act_signature``)
    so the names survive re-render even though Act ids do not. Acts the model
    doesn't return a line for are simply left unnamed (the renderer falls back to
    a roman numeral) — a missing name is honest, not an error.
    """
    from antiquarian.profile import act_signature

    if not acts:
        return {}
    if backend is None:
        from antiquarian.backends import DEFAULT_BACKEND

        backend = DEFAULT_BACKEND

    prompt = build_act_naming_prompt(acts, arc_names_by_slug, survey_excerpt)
    raw = backend.synthesize(
        ACT_NAMING_SYSTEM_PROMPT, prompt, timeout_seconds=timeout_seconds, log=log
    )

    name_by_index: dict[int, str] = {}
    for line in raw.splitlines():
        m = _ACT_NAME_LINE_RE.match(line)
        if m:
            name = m.group(2).strip().strip("*").strip()  # drop **markdown** emphasis
            if name:
                name_by_index[int(m.group(1))] = name

    names: dict[str, str] = {}
    for a in acts:
        name = name_by_index.get(a["index"])
        if name:
            names[act_signature(a["start"], a["end"])] = name
    return names
