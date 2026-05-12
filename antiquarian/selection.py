"""File selection for multi-file Antiquarian commands.

Default behavior: walk the repo via ``git ls-files`` (respects ``.gitignore``)
and apply a built-in skiplist for common bloat directories. Users can refine
with ``--include`` / ``--exclude`` globs, or bypass everything with ``--only``
to feed an exact whitelist of paths.
"""

from __future__ import annotations

import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path


# Always skip, even if the user's .gitignore allows them in.
# Dropped from any candidate set unless they appear in --only.
_BUILT_IN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "vendor",
        ".antiquarian",
    }
)

_BUILT_IN_SKIP_GLOBS = frozenset(
    {
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.dylib",
        "*.dll",
        ".DS_Store",
    }
)


def _path_in_skip_dir(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in _BUILT_IN_SKIP_DIRS for part in parts)


def _matches_glob(path: str, pattern: str) -> bool:
    """Match against the full path *or* the basename — catches both `tests/foo.py` and `*.pyc`."""
    return fnmatch(path, pattern) or fnmatch(os.path.basename(path), pattern)


def _matches_any_glob(path: str, patterns: list[str]) -> bool:
    return any(_matches_glob(path, p) for p in patterns)


def _matches_built_in_skip(path: str) -> bool:
    if _path_in_skip_dir(path):
        return True
    if _matches_any_glob(path, list(_BUILT_IN_SKIP_GLOBS)):
        return True
    if any(part.endswith(".egg-info") for part in path.split("/")):
        return True
    return False


def _git_tracked_files(repo_path: str | Path) -> list[str]:
    """Return repo-relative paths of files tracked by git at HEAD."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.split("\n") if line]


def _walk_filesystem(repo_path: str | Path) -> list[str]:
    """Fallback for non-git directories: walk filesystem, applying built-in skips."""
    base = Path(repo_path)
    paths: list[str] = []
    for root, dirs, files in os.walk(base):
        # Prune skip dirs in-place so os.walk doesn't descend
        dirs[:] = [d for d in dirs if d not in _BUILT_IN_SKIP_DIRS]
        for name in files:
            full = Path(root) / name
            rel = str(full.relative_to(base))
            paths.append(rel)
    return paths


def select_files(
    repo_path: str | Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    only: list[str] | None = None,
    respect_gitignore: bool = True,
) -> list[str]:
    """Return repo-relative file paths to analyze.

    Semantics:

    - When ``only`` is non-empty, return exactly those paths (verifying each exists).
      Bypasses defaults, ``.gitignore``, ``include``, and ``exclude``.
    - Otherwise, candidates come from ``git ls-files`` (when ``respect_gitignore``
      is True and the directory is a git repo) or a filesystem walk.
    - Built-in skiplist always applies (``.git/``, ``node_modules/``, ``__pycache__/``, etc.).
    - ``exclude`` patterns are subtracted from the candidate set.
    - ``include`` patterns are additive: matching files are added back even if they
      were skipped by the built-in list or ``exclude``.
    """
    repo = Path(repo_path).resolve()

    if only:
        result = []
        for p in only:
            full = repo / p
            if full.exists():
                result.append(p)
        return sorted(set(result))

    candidates: list[str]
    if respect_gitignore and (repo / ".git").exists():
        try:
            candidates = _git_tracked_files(repo)
        except subprocess.CalledProcessError:
            candidates = _walk_filesystem(repo)
    else:
        candidates = _walk_filesystem(repo)

    exclude = exclude or []
    include = include or []

    selected: list[str] = []
    for path in candidates:
        if _matches_built_in_skip(path):
            if _matches_any_glob(path, include):
                selected.append(path)
            continue
        if _matches_any_glob(path, exclude):
            if _matches_any_glob(path, include):
                selected.append(path)
            continue
        selected.append(path)

    # Includes can also re-add filesystem-walked files that weren't in the original
    # candidate set (rare but possible if exclude=** was set and include=foo/*)
    if include:
        all_seen = set(selected)
        for path in candidates:
            if path in all_seen:
                continue
            if _matches_any_glob(path, include):
                selected.append(path)

    return sorted(set(selected))
