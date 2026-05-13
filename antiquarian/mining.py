"""Mine commit features from a git repository for a specific file."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Iterator

from pydriller import Repository
from ulid import ULID

from antiquarian.models import CommitFeatures

_REVERT_PATTERNS = [
    re.compile(r'^Revert "', re.MULTILINE),
    re.compile(r"^revert:\s", re.MULTILINE),
    re.compile(r"Reverts? commit [0-9a-f]{7,}", re.IGNORECASE),
]


def _detect_revert(message: str, additions: int, deletions: int) -> bool:
    for pat in _REVERT_PATTERNS:
        if pat.search(message):
            return True
    if additions >= 5 and deletions >= 5:
        smaller, larger = sorted([additions, deletions])
        if larger / smaller <= 1.1:
            return True
    return False


def historical_shas(repo_path: str | Path, file_path: str) -> list[str]:
    """Return SHAs that ever touched ``file_path`` (following renames), oldest first.

    ``git log --follow --reverse`` is a toxic combination that truncates history
    to 0-1 commits because ``--follow`` runs in git's output layer while
    ``--reverse`` reorders the walker before ``--follow`` sees it. We emit
    chronological-descending via ``--follow`` alone and reverse in Python.
    See issue #13.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            "--follow",
            "--pretty=format:%H",
            "--",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    shas = [sha for sha in result.stdout.strip().split("\n") if sha]
    shas.reverse()
    return shas


def mine_file_history(
    repo_path: str | Path,
    file_path: str,
) -> Iterator[CommitFeatures]:
    """Yield ``CommitFeatures`` for every commit that touched ``file_path``, oldest first."""
    shas = historical_shas(repo_path, file_path)
    if not shas:
        return

    for commit in Repository(str(repo_path), only_commits=shas).traverse_commits():
        ts = commit.committer_date
        files_changed = [m.new_path or m.old_path for m in commit.modified_files]

        yield CommitFeatures(
            id=str(ULID()),
            git_sha=commit.hash,
            jj_change_id=None,
            jj_commit_id=None,
            author=commit.author.name,
            author_email=commit.author.email,
            timestamp=ts,
            hour_of_day=ts.hour,
            day_of_week=ts.weekday(),
            message=commit.msg,
            files_changed=[f for f in files_changed if f is not None],
            additions=commit.insertions,
            deletions=commit.deletions,
            pr_number=None,
            pr_body=None,
            is_revert=_detect_revert(commit.msg, commit.insertions, commit.deletions),
        )


def compute_binge_windows(
    commits: list[CommitFeatures],
) -> list[CommitFeatures]:
    """Enrich commits with nearest same-author neighbor distance in minutes.

    Returns new CommitFeatures instances (frozen dataclass) with
    commit_binge_window_minutes populated.
    """
    if not commits:
        return []

    by_author: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(commits):
        by_author[c.author].append(i)

    result: list[CommitFeatures] = []
    for c in commits:
        indices = by_author[c.author]
        if len(indices) < 2:
            result.append(c)
            continue

        author_commits = [commits[j] for j in indices]
        author_commits.sort(key=lambda x: x.timestamp)
        ts = c.timestamp
        min_delta: int | None = None
        for ac in author_commits:
            if ac is c:
                continue
            delta = abs(int((ts - ac.timestamp).total_seconds())) // 60
            if min_delta is None or delta < min_delta:
                min_delta = delta

        result.append(replace(c, commit_binge_window_minutes=min_delta))

    return result
