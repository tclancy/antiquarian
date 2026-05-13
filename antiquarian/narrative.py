"""Synthesize narrative output via `claude -p` with the Antiquarian system prompt."""

from __future__ import annotations

import random
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Sequence

from antiquarian.models import CommitFeatures, TodoAnnotation

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
# This sanitizer is kept as-is until #36 lands a proper size-aware compressor
# that targets `len(prompt)` directly. Don't add new patterns here on the
# assumption that specific content triggers anything — file-size is what
# matters. See #36 for the replacement design.
_CLAUDE_HANG_PATTERNS = [
    re.compile(r"🤖 Generated with \[Claude Code\]\(https://claude\.ai/code\)\s*"),
    re.compile(r"Co-Authored-By: Claude <noreply@anthropic\.com>\s*"),
]


def _sanitize_for_claude(text: str) -> str:
    """Strip two trailer lines from commit/PR content (legacy of #16).

    Originally believed to fix a content-driven hang in ``claude -p``; later
    shown to work via byte-count reduction (see #16 wrap-up, superseded by
    #36). Kept until the size-aware compressor lands so we don't regress
    today's working prompt sizes.

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
- If there are no annotations, say: "The file currently carries no TODO/FIXME admissions. That itself is a signal of the maintainers' standards."

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


def _format_commit(c: CommitFeatures, index: int) -> str:
    pr_section = ""
    if c.pr_number is not None:
        pr_section = f"\n\n**PR #{c.pr_number}**"
        if c.pr_body:
            pr_section += (
                f"\n```\n{_compress_message(_sanitize_for_claude(c.pr_body))}\n```"
            )
    files_summary = ", ".join(c.files_changed[:6])
    if len(c.files_changed) > 6:
        files_summary += f", ... ({len(c.files_changed)} files total)"
    sha = c.git_sha or c.id
    message = _compress_message(_sanitize_for_claude(c.message))
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


def build_user_prompt(
    file_path: str,
    repo_name: str,
    commits: Sequence[CommitFeatures],
    todos: Sequence[TodoAnnotation],
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    sections = [
        "# Source data for the historian",
        "",
        f"**File:** `{file_path}`",
        f"**Repository:** {repo_name}",
        f"**Today's date:** {today}",
        f"**Commit count:** {len(commits)}",
        f"**TODO/FIXME count currently in file:** {len(todos)}",
        "",
        "## Commit history (oldest first)",
        "",
    ]
    for i, c in enumerate(commits, start=1):
        sections.append(_format_commit(c, i))
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
- ~200-400 words

## Where the channel went dark
- Time windows where evidence thins out across multiple files at once
- Possible causes (team change, incident, pivot, dormancy) based on what evidence remains
- If the channel held throughout, say so
- ~100-200 words

# What to avoid

- Don't restate the per-file narratives. Reference them, don't recap.
- Don't invent cross-file relationships to fill space.
- Don't editorialize ("a beautiful refactor", "interesting choice"). State evidence.
- Brevity beats padding.
"""


def build_survey_prompt(
    repo_name: str,
    file_stories: Sequence[tuple[str, str]],
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

    sections.append(
        "Now write the codebase-level synthesis per the structure in the system prompt. "
        "Begin directly with `## Files surveyed` — no preamble."
    )
    return "\n".join(sections)


def synthesize_survey(
    *,
    repo_name: str,
    file_stories: Sequence[tuple[str, str]],
    timeout_seconds: int = 300,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> str:
    """Build a survey prompt and return the codebase-level narrative via ``backend``."""
    if backend is None:
        from antiquarian.backends import DEFAULT_BACKEND

        backend = DEFAULT_BACKEND
    user_prompt = build_survey_prompt(repo_name, file_stories)
    return backend.synthesize(
        SURVEY_SYSTEM_PROMPT, user_prompt, timeout_seconds=timeout_seconds, log=log
    )
