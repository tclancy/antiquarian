"""Tests for the central cache.db archive (#139).

Every survey/story/render run copies the per-repo cache.db into a common
archive keyed by project name, so any project can be re-rendered for free
later without its original checkout.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from antiquarian.cache import (
    archive_cache,
    archive_root,
    cache_path_for_repo,
    project_name_for_repo,
)


def _seed_cache(repo: Path) -> Path:
    """Create a minimal cache.db under <repo>/.antiquarian/."""
    db = cache_path_for_repo(repo)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE marker (note TEXT)")
    con.execute("INSERT INTO marker VALUES ('hello')")
    con.commit()
    con.close()
    return db


def test_project_name_is_repo_dir_basename(tmp_path: Path):
    repo = tmp_path / "httpx-repo"
    repo.mkdir()
    assert project_name_for_repo(repo) == "httpx-repo"


def test_archive_root_honors_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTIQUARIAN_CACHE_ARCHIVE", str(tmp_path / "custom"))
    assert archive_root() == tmp_path / "custom"


def test_archive_root_default_under_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTIQUARIAN_CACHE_ARCHIVE", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert archive_root() == tmp_path / ".antiquarian" / "caches"


def test_archive_copies_cache_to_project_named_dir(tmp_path: Path):
    repo = tmp_path / "myproj"
    repo.mkdir()
    _seed_cache(repo)
    root = tmp_path / "archive"

    dest = archive_cache(repo, root=root)

    assert dest == root / "myproj" / "cache.db"
    assert dest.exists()
    # the archived copy is a real, readable cache
    con = sqlite3.connect(dest)
    assert con.execute("SELECT note FROM marker").fetchone()[0] == "hello"
    con.close()


def test_archive_is_idempotent_overwrite(tmp_path: Path):
    repo = tmp_path / "myproj"
    repo.mkdir()
    _seed_cache(repo)
    root = tmp_path / "archive"

    first = archive_cache(repo, root=root)
    second = archive_cache(repo, root=root)  # no error, overwrites

    assert first == second
    assert second.exists()


def test_archive_no_op_when_no_cache(tmp_path: Path):
    repo = tmp_path / "empty"
    repo.mkdir()
    assert archive_cache(repo, root=tmp_path / "archive") is None
