"""Pytest configuration — register Hypothesis profiles and shared fixtures.

Profiles:
- ``dev`` — 30 examples per test. Default for fast local iteration.
- ``ci`` — 100 examples per test. What CI runs by default.
- ``fuzz`` — 1,000 examples per test. For local hunt-for-new-failures sessions.
- ``nightly`` — 10,000 examples per test, no deadline. For overnight runs against
  a fully-built test suite when looking for rare edge cases.

Pick one of three ways:

1. Set the env var:    ``HYPOTHESIS_PROFILE=fuzz uv run pytest tests/test_prop_*.py``
2. Pytest flag:        ``uv run pytest --hypothesis-profile=fuzz tests/test_prop_*.py``
3. Default (``ci``)   for CI runs, where no override is needed.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

hypothesis_settings.register_profile("dev", max_examples=30)
hypothesis_settings.register_profile("ci", max_examples=100)
hypothesis_settings.register_profile("fuzz", max_examples=1_000)
hypothesis_settings.register_profile(
    "nightly",
    max_examples=10_000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


@pytest.fixture(autouse=True)
def _scrub_git_env(monkeypatch):
    """Scrub ``GIT_*`` env vars before every test.

    When pytest runs under a git hook (the ``pre-push`` pre-commit stage),
    git exports ``GIT_DIR`` / ``GIT_INDEX_FILE`` / etc. into the hook's
    environment. Tests that ``subprocess.run(["git", ...])`` inside an
    isolated tmp-repo fixture would otherwise see those vars and operate
    against the *host* repo (or fail outright with "fatal: not a git
    repository" once the hook's worktree is gone).

    Scrubbing every variable starting with ``GIT_`` keeps both `git` and
    `jj` (which respects the same envs) honest to the per-test working
    directory. Pure-Python tests are unaffected.
    """
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


def _seed_cache_db(repo: Path) -> None:
    """Seed a minimal .antiquarian/cache.db with two commits over two files.

    Schema matches antiquarian/cache.py — kept inline because we want the
    tests to break loudly when the schema drifts, not to silently re-create it.
    """
    db_path = repo / ".antiquarian" / "cache.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE commit_features (
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
            is_revert INTEGER NOT NULL DEFAULT 0,
            commit_binge_window_minutes INTEGER,
            PRIMARY KEY (sha, file_path)
        );
        """
    )
    rows = [
        (
            "aaa11111",
            "src/a.py",
            "id-a",
            None,
            None,
            "Alice",
            "alice@example.com",
            "2026-01-15T10:30:00+00:00",
            10,
            3,
            "Initial commit",
            '["src/a.py"]',
            12,
            0,
            None,
            None,
        ),
        (
            "bbb22222",
            "src/b.py",
            "id-b",
            None,
            None,
            "Bob",
            "bob@example.com",
            "2026-03-20T14:15:00+00:00",
            14,
            4,
            "Second commit",
            '["src/b.py", "src/a.py"]',
            30,
            5,
            None,
            None,
        ),
    ]
    conn.executemany(
        "INSERT INTO commit_features ("
        "sha, file_path, id, jj_change_id, jj_commit_id, author, author_email,"
        " timestamp, hour_of_day, day_of_week, message, files_changed,"
        " additions, deletions, pr_number, pr_body"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded_repo(tmp_path: Path) -> Path:
    """A tmp git-like dir with a populated .antiquarian/cache.db."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "src" / "b.py").write_text("y = 2\n")
    _seed_cache_db(tmp_path)
    return tmp_path
