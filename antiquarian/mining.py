"""Mine commit features from a git repository for a specific file."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

from pydriller import Repository
from ulid import ULID

from antiquarian.models import CommitFeatures


def historical_shas(repo_path: str | Path, file_path: str) -> list[str]:
    """Return SHAs that ever touched ``file_path`` (following renames), oldest first."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            "--follow",
            "--reverse",
            "--pretty=format:%H",
            "--",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [sha for sha in result.stdout.strip().split("\n") if sha]


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
        )
