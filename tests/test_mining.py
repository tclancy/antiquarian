"""Tests for mining module — commit history extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from antiquarian.mining import historical_shas


@pytest.fixture()
def renamed_file_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a git repo where a file is created, renamed, then modified.

    Returns (repo_path, current_file_path_relative).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@t.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@t.com",
    }

    def run(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
            env={**env, "PATH": "/usr/bin:/bin"},
        )

    run("init", "-b", "main")
    run("config", "user.name", "Test")
    run("config", "user.email", "t@t.com")

    old_file = repo / "old_name.py"
    old_file.write_text("# original\n")
    run("add", "old_name.py")
    run("commit", "-m", "create old_name.py")

    run("mv", "old_name.py", "new_name.py")
    run("commit", "-m", "rename to new_name.py")

    new_file = repo / "new_name.py"
    new_file.write_text("# original\n# modified after rename\n")
    run("add", "new_name.py")
    run("commit", "-m", "modify new_name.py")

    return repo, "new_name.py"


def test_historical_shas_follows_renames(renamed_file_repo: tuple[Path, str]) -> None:
    """historical_shas should return all commits including pre-rename history."""
    repo, file_path = renamed_file_repo
    shas = historical_shas(repo, file_path)

    assert len(shas) == 3, (
        f"Expected 3 commits (create + rename + modify), got {len(shas)}"
    )


def test_historical_shas_oldest_first(renamed_file_repo: tuple[Path, str]) -> None:
    """SHAs should be returned in chronological order (oldest first)."""
    repo, file_path = renamed_file_repo
    shas = historical_shas(repo, file_path)

    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--pretty=format:%H", "--reverse"],
        capture_output=True,
        text=True,
        check=True,
    )
    all_shas_oldest_first = result.stdout.strip().split("\n")

    assert shas == all_shas_oldest_first


def test_historical_shas_no_file(tmp_path: Path) -> None:
    """historical_shas on a file with no history returns an empty list."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "init", "-b", "main"],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t.com"],
        capture_output=True,
        text=True,
        check=True,
    )
    dummy = repo / "dummy.txt"
    dummy.write_text("x\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "dummy.txt"],
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True,
        text=True,
        check=True,
    )

    shas = historical_shas(repo, "nonexistent.py")
    assert shas == []
