"""Tests for antiquarian.todos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from antiquarian.todos import extract_todos


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """A tmp git repo with one text file and one binary file committed at HEAD."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    (tmp_path / "app.py").write_text("x = 1  # TODO: wire this up\n")
    img = tmp_path / "logo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01")

    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_binary_file_yields_no_todos(tmp_git_repo: Path) -> None:
    """A binary file must yield no annotations rather than crashing the batch.

    `git show HEAD:logo.png` succeeds (exit 0) but returns bytes that are not
    valid UTF-8; the extractor should treat that as "no readable text", not
    propagate a UnicodeDecodeError that aborts a whole survey (#B).
    """
    assert list(extract_todos(tmp_git_repo, "logo.png")) == []


def test_text_file_todo_extracted(tmp_git_repo: Path) -> None:
    """A normal text TODO is still extracted (the fix must not break the happy path)."""
    todos = list(extract_todos(tmp_git_repo, "app.py"))
    assert len(todos) == 1
    assert todos[0].kind == "TODO"
    assert todos[0].text == "wire this up"
