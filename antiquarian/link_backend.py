"""Resolve textual references in story prose to URLs (#113).

Story narratives reference commits ("the 7af3c1b refactor", "in 41ccaa9…")
and GitHub issues/PRs ("see #95", "blocked by #117"). The prose is what the
LLM writes, so the references are textual — they aren't models, they're
words. This module turns them into clickable links *at render time*, without
hard-coding any host.

The seam is a small Protocol — ``LinkBackend`` — with one concrete shipping
backend (``GitHubBackend``) and a graceful no-op fallback for repos whose
remote isn't on github.com. A GitLab/Gitea/Bitbucket backend can slot in
later by implementing the same three methods.

A backend can return ``None`` for any reference. That is the "I don't know
how to link that" signal — the renderer leaves the text intact. Never emit
a broken link; degrade to plain text instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from antiquarian.prs import detect_github_repo


@runtime_checkable
class LinkBackend(Protocol):
    """Resolves textual references in story prose to URLs.

    Each method returns the URL string or ``None`` when the backend can't
    or won't link the reference. Implementations must never raise on
    well-formed input — the contract is "answer or pass".
    """

    def commit_url(self, sha: str) -> str | None: ...
    def pr_url(self, number: int) -> str | None: ...
    def issue_url(self, number: int) -> str | None: ...


@dataclass(frozen=True)
class GitHubBackend:
    """Maps commit SHAs and ``#N`` references to GitHub URLs.

    GitHub uses one number space for issues and PRs — `/issues/N` redirects
    to `/pull/N` when N is a PR, and vice versa. The renderer can't tell
    from prose which kind of artifact a ``#N`` is, so it asks
    ``issue_url`` and lets GitHub do the routing. ``pr_url`` is kept for
    callers that *do* know (e.g. PR-enrichment data), so the URL is direct.
    """

    owner: str
    repo: str
    host: str = "github.com"

    def commit_url(self, sha: str) -> str | None:
        return f"https://{self.host}/{self.owner}/{self.repo}/commit/{sha}"

    def pr_url(self, number: int) -> str | None:
        return f"https://{self.host}/{self.owner}/{self.repo}/pull/{number}"

    def issue_url(self, number: int) -> str | None:
        return f"https://{self.host}/{self.owner}/{self.repo}/issues/{number}"


class NoopLinkBackend:
    """No host detected, or non-GitHub host — leave references as plain text.

    The renderer treats a ``None`` return as "no link" and emits the raw
    reference, so this is the silent, graceful-degradation default.
    """

    def commit_url(self, sha: str) -> str | None:
        return None

    def pr_url(self, number: int) -> str | None:
        return None

    def issue_url(self, number: int) -> str | None:
        return None


def detect_link_backend(repo_path: str | Path) -> LinkBackend:
    """Pick a link backend for the repo at ``repo_path``.

    Reads the ``origin`` remote via :func:`antiquarian.prs.detect_github_repo`.
    Returns :class:`GitHubBackend` if the remote parses as GitHub, otherwise
    :class:`NoopLinkBackend`. Never raises — an unreadable repo is the same
    as "no host known".
    """
    gh = detect_github_repo(repo_path)
    if gh is None:
        return NoopLinkBackend()
    owner, repo = gh
    return GitHubBackend(owner=owner, repo=repo)


# Tokens we must NOT linkify inside (in match order — first match wins):
#   - fenced code blocks (```...```)
#   - inline code spans (`...`)
#   - existing markdown links ([text](url))
#   - angle-bracket auto-links (<url>)
#   - bare http(s) URLs (might already contain a SHA-looking path segment)
#
# The two targets we DO want:
#   - PR/issue refs: ``#N`` where N is 1-7 digits and the # isn't preceded
#     by a word char (so ``foo#123`` is skipped — that's some-other-syntax).
#   - Commit SHAs: 7-40 hex chars on word boundaries. 7 is git's default
#     short-SHA minimum, which is also long enough to dodge most English
#     hex-looking words ("decade" is only 6).
_TOKEN = re.compile(
    r"""
    (
        ```.*?```                              # fenced code block
        | `[^`\n]+`                            # inline code span
        | \[[^\]]*\]\([^)]*\)                  # existing [text](url) link
        | <[^<>\s]+>                           # <url> auto-link or HTML tag
        | https?://[^\s<>()\[\]]+              # bare URL
        | (?<![\w/])\#(?P<num>\d{1,7})(?!\w)   # #N — PR or issue ref
        | \b(?P<sha>[0-9a-f]{7,40})\b          # commit SHA
    )
    """,
    re.DOTALL | re.VERBOSE,
)


# A code span whose ENTIRE content is a lone ref — ``#123`` or a bare SHA. The
# narrative LLM habitually writes references as inline code (`#1522`, `7af3c1b`)
# because they read as identifiers; those are meant as links, so we linkify them
# while keeping the code styling. A code span with a ref *among other text* (a
# real snippet like ``git show 7af3c1b``) is left alone — see ``linkify_markdown``.
_LONE_HASH_REF = re.compile(r"#(\d{1,7})")
_LONE_SHA_REF = re.compile(r"[0-9a-f]{7,40}")


def linkify_markdown(md: str, backend: LinkBackend) -> str:
    """Rewrite ``#N`` and commit SHA references in ``md`` as Markdown links.

    Operates on the Markdown source before HTML conversion so the result is
    still valid Markdown — Python-Markdown then renders the links as normal.
    Fenced blocks, existing links, and bare URLs are left intact, so a
    SHA-looking path inside a URL isn't double-linked and a snippet in a fenced
    block stays literal.

    Inline code spans are linked only when their entire content is a lone ref
    (```` `#113` ```` or a bare SHA) — the LLM's habitual identifier styling —
    and left untouched when they carry a ref among other text (genuine code).

    When ``backend`` returns ``None`` for a reference, the original text is
    emitted unchanged — the renderer never produces a broken link.
    """

    def repl(m: re.Match[str]) -> str:
        text = m.group(0)
        num = m.group("num")
        sha = m.group("sha")
        if num is not None:
            url = backend.issue_url(int(num))
            return f"[#{num}]({url})" if url else text
        if sha is not None:
            url = backend.commit_url(sha)
            return f"[`{sha[:7]}`]({url})" if url else text
        # Inline code span (single backticks, not a ``` fenced block, which the
        # regex matched first) whose whole content is a lone ref → link it,
        # keeping the code styling. Anything else opaque passes through.
        if text.startswith("`") and not text.startswith("```") and text.endswith("`"):
            inner = text[1:-1].strip()
            hash_ref = _LONE_HASH_REF.fullmatch(inner)
            if hash_ref:
                url = backend.issue_url(int(hash_ref.group(1)))
                if url:
                    return f"[`#{hash_ref.group(1)}`]({url})"
            if _LONE_SHA_REF.fullmatch(inner):
                url = backend.commit_url(inner)
                if url:
                    return f"[`{inner[:7]}`]({url})"
        return text

    return _TOKEN.sub(repl, md)
