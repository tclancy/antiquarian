"""Tests for antiquarian.selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from antiquarian.selection import (
    _HARD_SKIP_DIRS,
    _matches_glob,
    _path_in_dir_set,
    _path_matches_soft_warn,
    select_files,
)


class TestHardSkip:
    @pytest.mark.parametrize(
        "path",
        [
            ".git/config",
            "src/.git/hooks/pre-commit",
            ".antiquarian/cache.db",
            ".antiquarian/stories/deploy.md",
        ],
    )
    def test_hard_skipped_paths(self, path: str) -> None:
        assert _path_in_dir_set(path, _HARD_SKIP_DIRS)

    @pytest.mark.parametrize(
        "path",
        [
            "antiquarian/cli.py",
            "src/itguy/deploy.py",
            "README.md",
            "node_modules/foo/index.js",
            ".env",
            ".venv/lib/foo.py",
        ],
    )
    def test_not_hard_skipped(self, path: str) -> None:
        assert not _path_in_dir_set(path, _HARD_SKIP_DIRS)


class TestSoftWarn:
    @pytest.mark.parametrize(
        "path,expected_trigger",
        [
            ("node_modules/foo/index.js", "node_modules"),
            ("deep/node_modules/foo.js", "node_modules"),
            ("src/__pycache__/cli.cpython-313.pyc", "__pycache__"),
            (".venv/lib/python3.13/site-packages/foo.py", ".venv"),
            ("dist/wheel.whl", "dist"),
            ("build/lib/antiquarian/cli.py", "build"),
            ("antiquarian.egg-info/PKG-INFO", "antiquarian.egg-info"),
            ("vendor/github.com/foo/bar.go", "vendor"),
            ("target/release/binary", "target"),
        ],
    )
    def test_triggers_warning(self, path: str, expected_trigger: str) -> None:
        assert _path_matches_soft_warn(path) == expected_trigger

    @pytest.mark.parametrize(
        "path",
        [
            "antiquarian/cli.py",
            "src/itguy/deploy.py",
            "README.md",
            "tests/test_selection.py",
            ".env",
            "config/settings.yaml",
        ],
    )
    def test_no_warning(self, path: str) -> None:
        assert _path_matches_soft_warn(path) is None


class TestGlobMatching:
    def test_basename_match(self) -> None:
        assert _matches_glob("a/b/c.pyc", "*.pyc")
        assert _matches_glob("foo/.DS_Store", ".DS_Store")

    def test_full_path_match(self) -> None:
        assert _matches_glob("tests/test_foo.py", "tests/*")

    def test_no_match(self) -> None:
        assert not _matches_glob("antiquarian/cli.py", "*.pyc")
        assert not _matches_glob("docs/intro.md", "tests/*")


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """A tmp directory initialized as a git repo with a small fixture file tree."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
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

    def test_non_git_directory_raises(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hi")
        with pytest.raises(SystemExit):
            select_files(tmp_path)

    def test_tracked_env_file_included(self, tmp_git_repo: Path) -> None:
        """A .env file tracked by git should be included — trust the maintainer."""
        env_file = tmp_git_repo / ".env"
        env_file.write_text("SECRET=foo\n")
        subprocess.run(["git", "add", "-f", ".env"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "add .env"],
            cwd=tmp_git_repo,
            check=True,
        )
        selected = select_files(tmp_git_repo)
        assert ".env" in selected


class TestSoftWarnEmission:
    def test_warns_on_tracked_node_modules(
        self, tmp_git_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """If node_modules is tracked, emit a warning but still include it."""
        nm_dir = tmp_git_repo / "node_modules" / "foo"
        nm_dir.mkdir(parents=True)
        (nm_dir / "index.js").write_text("module.exports = {};")
        subprocess.run(["git", "add", "node_modules/"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "add node_modules"],
            cwd=tmp_git_repo,
            check=True,
        )

        selected = select_files(tmp_git_repo)
        assert "node_modules/foo/index.js" in selected

        captured = capsys.readouterr()
        assert "node_modules/" in captured.err
        assert "warning:" in captured.err

    def test_no_warning_for_clean_repo(
        self, tmp_git_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        select_files(tmp_git_repo)
        captured = capsys.readouterr()
        assert "warning:" not in captured.err
