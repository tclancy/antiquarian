"""Synthesize narrative output via `claude -p` with the Antiquarian system prompt."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Sequence

from antiquarian.models import CommitFeatures, TodoAnnotation


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
            pr_section += f"\n```\n{c.pr_body}\n```"
    files_summary = ", ".join(c.files_changed[:6])
    if len(c.files_changed) > 6:
        files_summary += f", ... ({len(c.files_changed)} files total)"
    sha = c.git_sha or c.id
    return (
        f"### [{index}] {sha[:8]} — {c.timestamp.date().isoformat()} — {c.author}\n"
        f"+{c.additions}/-{c.deletions} across: {files_summary}\n\n"
        f"**Message:**\n```\n{c.message}\n```{pr_section}"
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
) -> str:
    """Send the source data to ``claude -p`` and return the narrative markdown."""
    user_prompt = build_user_prompt(file_path, repo_name, commits, todos)
    result = subprocess.run(
        ["claude", "-p", "--system-prompt", SYSTEM_PROMPT],
        input=user_prompt,
        text=True,
        capture_output=True,
        check=True,
        timeout=timeout_seconds,
    )
    return result.stdout.strip()
