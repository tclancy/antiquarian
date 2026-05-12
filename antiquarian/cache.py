"""SQLite cache for commit features and narrative chunks.

The cache lives at ``<target_repo>/.antiquarian/cache.db`` and is keyed by
``(commit_sha, file_path)`` so larger compositions (module / repo / author
biographies) can reuse work done for a per-file story.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from antiquarian.models import CommitFeatures


SCHEMA = """
CREATE TABLE IF NOT EXISTS commit_features (
    sha TEXT NOT NULL,
    file_path TEXT NOT NULL,
    id TEXT NOT NULL,
    jj_change_id TEXT,
    jj_commit_id TEXT,
    author TEXT NOT NULL,
    author_email TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    hour_of_day INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    message TEXT NOT NULL,
    files_changed TEXT NOT NULL,
    additions INTEGER NOT NULL,
    deletions INTEGER NOT NULL,
    pr_number INTEGER,
    pr_body TEXT,
    PRIMARY KEY (sha, file_path)
);

CREATE TABLE IF NOT EXISTS narrative_chunks (
    sha TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_version INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (sha, file_path, chunk_version)
);
"""


def cache_path_for_repo(repo_path: str | Path) -> Path:
    return Path(repo_path) / ".antiquarian" / "cache.db"


@contextmanager
def open_cache(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_commit(
    conn: sqlite3.Connection, sha: str, file_path: str
) -> CommitFeatures | None:
    row = conn.execute(
        "SELECT * FROM commit_features WHERE sha = ? AND file_path = ?",
        (sha, file_path),
    ).fetchone()
    if row is None:
        return None
    return _row_to_features(row)


def put_commit(
    conn: sqlite3.Connection, features: CommitFeatures, file_path: str
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO commit_features (
            sha, file_path, id, jj_change_id, jj_commit_id,
            author, author_email, timestamp, hour_of_day, day_of_week,
            message, files_changed, additions, deletions, pr_number, pr_body
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            features.git_sha,
            file_path,
            features.id,
            features.jj_change_id,
            features.jj_commit_id,
            features.author,
            features.author_email,
            features.timestamp.isoformat(),
            features.hour_of_day,
            features.day_of_week,
            features.message,
            json.dumps(features.files_changed),
            features.additions,
            features.deletions,
            features.pr_number,
            features.pr_body,
        ),
    )


def get_narrative_chunk(
    conn: sqlite3.Connection,
    sha: str,
    file_path: str,
    chunk_version: int,
) -> str | None:
    row = conn.execute(
        """
        SELECT chunk_text FROM narrative_chunks
        WHERE sha = ? AND file_path = ? AND chunk_version = ?
        """,
        (sha, file_path, chunk_version),
    ).fetchone()
    return row["chunk_text"] if row else None


def put_narrative_chunk(
    conn: sqlite3.Connection,
    sha: str,
    file_path: str,
    chunk_version: int,
    chunk_text: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO narrative_chunks (
            sha, file_path, chunk_version, chunk_text, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            sha,
            file_path,
            chunk_version,
            chunk_text,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _row_to_features(row: sqlite3.Row) -> CommitFeatures:
    return CommitFeatures(
        id=row["id"],
        git_sha=row["sha"],
        jj_change_id=row["jj_change_id"],
        jj_commit_id=row["jj_commit_id"],
        author=row["author"],
        author_email=row["author_email"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        hour_of_day=row["hour_of_day"],
        day_of_week=row["day_of_week"],
        message=row["message"],
        files_changed=json.loads(row["files_changed"]),
        additions=row["additions"],
        deletions=row["deletions"],
        pr_number=row["pr_number"],
        pr_body=row["pr_body"],
    )
