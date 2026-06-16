"""Extract TODO/FIXME-style annotations and trace each to its introducing commit.

These are what Tom calls "messages from a better version of myself" — admissions
that present-self left a problem for future-self. They're often the most honest
signal in a codebase, so the narrative engine treats them as load-bearing.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from antiquarian.models import TodoAnnotation


_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b\s*:?\s*(.*)")


def _read_file_at_head(repo_path: str | Path, file_path: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"HEAD:{file_path}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _blame_line(
    repo_path: str | Path, file_path: str, line_number: int
) -> tuple[str, str, datetime] | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "blame",
                "--porcelain",
                f"-L{line_number},{line_number}",
                "--",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    lines = result.stdout.splitlines()
    if not lines:
        return None
    sha = lines[0].split()[0]
    author = "unknown"
    ts: datetime | None = None
    for line in lines[1:]:
        if line.startswith("author "):
            author = line[len("author ") :]
        elif line.startswith("author-time "):
            try:
                ts_unix = int(line[len("author-time ") :])
                ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
            except ValueError:
                pass
    if ts is None:
        return None
    return sha, author, ts


def extract_todos(repo_path: str | Path, file_path: str) -> Iterator[TodoAnnotation]:
    """Yield a ``TodoAnnotation`` for each TODO/FIXME-style comment in the file at HEAD."""
    try:
        lines = _read_file_at_head(repo_path, file_path)
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        # A binary blob (e.g. a tracked image) makes `git show` succeed but
        # return non-UTF-8 bytes. Treat it as "no readable text" rather than
        # letting one file abort an entire survey batch.
        return

    now = datetime.now(timezone.utc)
    for line_number, content in enumerate(lines, start=1):
        m = _TODO_RE.search(content)
        if not m:
            continue
        kind = m.group(1).upper()
        text = m.group(2).strip()

        blame = _blame_line(repo_path, file_path, line_number)
        if blame is None:
            continue
        sha, author, introduced_at = blame
        age_days = (now - introduced_at).days

        yield TodoAnnotation(
            kind=kind,  # type: ignore[arg-type]
            line_number=line_number,
            text=text,
            introduced_commit=sha,
            introduced_at=introduced_at,
            introduced_by=author,
            age_days=age_days,
        )
