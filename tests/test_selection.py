"""Tests for antiquarian.selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from antiquarian.selection import (
    _matches_built_in_skip,
    _matches_glob,
    select_files,
)


class TestBuiltInSkip:
    @pytest.mark.parametrize(
        "path",
        [
            ".git/config",
            "src/.git/hooks/pre-commit",
            "node_modules/foo/index.js",
            "deep/node_modules/foo.js",
            "src/__pycache__/cli.cpython-313.pyc",
            ".venv/lib/python3.13/site-packages/foo.py",
            "dist/wheel.whl",
            "build/lib/antiquarian/cli.py",
            "antiquarian.egg-info/PKG-INFO",
            ".pytest_cache/v/cache/lastfailed",
        ],
    )
    def test_skipped_paths(self, path: str) -> None:
        assert _matches_built_in_skip(path)

    @pytest.mark.parametrize(
        "path",
        [
            "antiquarian/cli.py",
            "src/itguy/deploy.py",
            "README.md",
            "tests/test_selection.py",
            "docs/architecture.md",
        ],
    )
    def test_non_skipped_paths(self, path: str) -> None:
        assert not _matches_built_in_skip(path)

    def test_compiled_python_files_skipped(self) -> None:
        assert _matches_built_in_skip("foo/bar.pyc")
        assert _matches_built_in_skip("foo.pyo")


class TestGlobMatching:
    def test_basename_match(self) -> None:
        assert _matches_glob("a/b/c.pyc", "*.pyc")
        assert _matches_glob("foo/.DS_Store", ".DS_Store")

    def test_full_path_match(self) -> None:
        assert _matches_glob("tests/test_foo.py", "tests/*")

    def test_no_match(self) -> None:
        assert not _matches_glob("antiquarian/cli.py", "*.pyc")
        assert not _matches_glob("docs/intro.md", "tests/*")


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A tmp directory initialized as a git repo with a small fixture file tree."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    files = {
        "README.md": "hello",
        "src/app.py": "print('hi')",
        "src/util.py": "def f(): pass",
        "tests/test_app.py": "def test_x(): pass",
        ".gitignore": ".venv/\n__pycache__/\n*.pyc\n",
    }
    for rel, content in files.items():
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    # Files that should be ignored
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("ignored")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "app.cpython-313.pyc").write_text("bytecode")

    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


class TestSelectFiles:
    def test_default_returns_tracked_files_only(self, tmp_git_repo: Path) -> None:
        selected = select_files(tmp_git_repo)
        assert "README.md" in selected
        assert "src/app.py" in selected
        assert "src/util.py" in selected
        assert "tests/test_app.py" in selected
        # gitignored
        assert not any(".venv" in p for p in selected)
        assert not any("__pycache__" in p for p in selected)

    def test_only_returns_exact_paths(self, tmp_git_repo: Path) -> None:
        selected = select_files(tmp_git_repo, only=["src/app.py", "src/util.py"])
        assert selected == ["src/app.py", "src/util.py"]

    def test_only_drops_nonexistent_paths(self, tmp_git_repo: Path) -> None:
        selected = select_files(
            tmp_git_repo, only=["src/app.py", "src/never_existed.py"]
        )
        assert selected == ["src/app.py"]

    def test_only_bypasses_other_filters(self, tmp_git_repo: Path) -> None:
        # Even though we exclude '*', the only paths come through
        selected = select_files(
            tmp_git_repo,
            only=["src/app.py"],
            exclude=["*"],
        )
        assert selected == ["src/app.py"]

    def test_exclude_subtracts(self, tmp_git_repo: Path) -> None:
        selected = select_files(tmp_git_repo, exclude=["tests/*"])
        assert "src/app.py" in selected
        assert not any(p.startswith("tests/") for p in selected)

    def test_include_re_adds_excluded(self, tmp_git_repo: Path) -> None:
        selected = select_files(
            tmp_git_repo,
            exclude=["tests/*"],
            include=["tests/test_app.py"],
        )
        assert "tests/test_app.py" in selected

    def test_no_respect_gitignore_falls_back_to_filesystem(
        self, tmp_git_repo: Path
    ) -> None:
        # Without git, .venv would normally show up — but the built-in skiplist
        # still excludes it. So this test just verifies the codepath runs.
        selected = select_files(tmp_git_repo, respect_gitignore=False)
        assert "README.md" in selected
        assert not any(".venv" in p for p in selected)  # still skipped by built-in

    def test_non_git_directory_walks_filesystem(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hi")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("hi")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "c.pyc").write_text("x")

        selected = select_files(tmp_path)
        assert "a.txt" in selected
        assert "sub/b.txt" in selected
        assert not any("__pycache__" in p for p in selected)
