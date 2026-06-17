"""``.mailmap`` identity canonicalization (#118).

Contributors commit under several emails over a project's life (personal ↔
work, GitHub's ``noreply`` privacy address, employer changes — see #120), and
the swimlane groups lanes by email, so one person fragments into several
lanes. Git's canonical answer is the repository ``.mailmap`` file; when a repo
ships one we honour it before building the atoms.

This is deliberately conservative and non-destructive: it only rewrites
identities the maintainers themselves declared equivalent in ``.mailmap``. It
never guesses (display-name equality is unsafe — see #120's ``Joe`` ×3); softer
heuristics are the separate, display-only concern of #127.

Format reference: gitmailmap(5). Four line forms are supported::

    Proper Name <proper@email>
    <proper@email> <commit@email>
    Proper Name <proper@email> <commit@email>
    Proper Name <proper@email> Commit Name <commit@email>
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `[name] <email>` twice; the second pair (the commit-side match) is optional.
_LINE_RE = re.compile(
    r"^\s*(?P<pname>.*?)\s*<(?P<pemail>[^>]+)>"
    r"(?:\s*(?P<cname>.*?)\s*<(?P<cemail>[^>]+)>)?\s*$"
)


@dataclass(frozen=True)
class _Entry:
    proper_name: str | None
    proper_email: str
    match_name: str | None
    match_email: str  # lower-cased for case-insensitive comparison


class Mailmap:
    """Resolves a commit ``(name, email)`` to its canonical identity."""

    def __init__(self, entries: list[_Entry]) -> None:
        self._entries = entries

    def resolve(self, name: str, email: str) -> tuple[str, str]:
        """Return the canonical ``(name, email)`` for a commit identity.

        Among the rules matching the commit email (case-insensitive), a rule
        that also pins the commit *name* wins for that name; otherwise the
        email-only rule applies. Unmatched identities pass through unchanged.
        """
        email_key = email.lower()
        candidates = [e for e in self._entries if e.match_email == email_key]
        chosen = next(
            (e for e in candidates if e.match_name == name),
            next((e for e in candidates if e.match_name is None), None),
        )
        if chosen is None:
            return name, email
        return (chosen.proper_name or name, chosen.proper_email)


def parse_mailmap(text: str) -> Mailmap:
    """Parse ``.mailmap`` text into a :class:`Mailmap`. Bad lines are skipped."""
    entries: list[_Entry] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        proper_name = m.group("pname") or None
        proper_email = m.group("pemail").strip()
        if m.group("cemail") is not None:
            match_name = m.group("cname") or None
            match_email = m.group("cemail").strip().lower()
        else:
            # No commit-side address: the rule matches by the proper email.
            match_name = None
            match_email = proper_email.lower()
        entries.append(
            _Entry(
                proper_name=proper_name,
                proper_email=proper_email,
                match_name=match_name,
                match_email=match_email,
            )
        )
    return Mailmap(entries)
