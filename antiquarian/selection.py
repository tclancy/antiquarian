"""File selection for multi-file Antiquarian commands.

Default behavior: walk the repo via ``git ls-files`` (respects ``.gitignore``)
and hard-skip only ``.git/`` and ``.antiquarian/`` (tool plumbing / own output).
Everything else in the tracked set is trusted — the project's ``.gitignore`` is
the authority on what matters.

A soft-warn list emits a one-time stderr warning when unusual directories
(``node_modules/``, ``__pycache__/``, etc.) appear in the candidate set, but
does **not** filter them.

Non-git directories are refused — Antiquarian's value comes from version history.
"""

from __future__ import annotations

import os
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

_HARD_SKIP_DIRS = frozenset({".git", ".antiquarian"})

_SOFT_WARN_DIRS = frozenset(
    {
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
        "target",
    }
)

_SOFT_WARN_GLOBS = frozenset(
    {
        "*.egg-info",
    }
)


def _path_in_dir_set(path: str, dirs: frozenset[str]) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in dirs for part in parts)


def _path_matches_soft_warn(path: str) -> str | None:
    """Return the triggering directory name if path matches a soft-warn pattern, else None."""
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in _SOFT_WARN_DIRS:
            return part
        if any(fnmatch(part, g) for g in _SOFT_WARN_GLOBS):
            return part
    return None


def _matches_glob(path: str, pattern: str) -> bool:
    """Match against the full path *or* the basename."""
    return fnmatch(path, pattern) or fnmatch(os.path.basename(path), pattern)


def _matches_any_glob(path: str, patterns: list[str]) -> bool:
    return any(_matches_glob(path, p) for p in patterns)


def _git_tracked_files(repo_path: str | Path) -> list[str]:
    """Return repo-relative paths of files tracked by git at HEAD."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.split("\n") if line]


def _is_binary_blob(repo_path: str | Path, file_path: str) -> bool:
    """True if the file's content at HEAD looks binary (contains a NUL byte).

    Mirrors git's own text/binary heuristic: a NUL byte in the first 8000
    bytes means binary. Narrating a binary blob (e.g. a tracked ``docs/img``
    image) is meaningless and crashes the text-oriented pipeline, so such
    files are dropped from selection rather than surveyed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "show", f"HEAD:{file_path}"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        # Not readable at HEAD (e.g. staged-but-uncommitted) — let the text
        # pipeline's own guards handle it rather than dropping it here.
        return False
    return b"\x00" in result.stdout[:8000]


def _emit_soft_warnings(candidates: list[str]) -> None:
    """Emit one stderr warning per unusual directory found in the candidate set."""
    warned: set[str] = set()
    for path in candidates:
        trigger = _path_matches_soft_warn(path)
        if trigger and trigger not in warned:
            warned.add(trigger)
            print(
                f"warning: '{trigger}/' appears to be tracked in this repo's history.\n"
                f"         That's unusual — including it will cloud the codebase narrative.\n"
                f"         To filter: --exclude '{trigger}/*'  (or add to .gitignore)",
                file=sys.stderr,
            )


def select_files(
    repo_path: str | Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    only: list[str] | None = None,
    respect_gitignore: bool = True,
) -> list[str]:
    """Return repo-relative file paths to analyze.

    Requires a git repository. Raises ``SystemExit`` for non-git directories.

    - ``only`` (non-empty): return exactly those paths, bypassing all filters.
    - Otherwise, candidates come from ``git ls-files``.
    - Hard-skip: ``.git/``, ``.antiquarian/`` (always excluded).
    - Soft-warn: unusual tracked directories get a stderr warning but are included.
    - ``exclude`` patterns subtract from the candidate set.
    - ``include`` patterns add back even if excluded.
    """
    repo = Path(repo_path).resolve()

    if only:
        result = []
        for p in only:
            full = repo / p
            if full.exists():
                result.append(p)
        return sorted(set(result))

    if not (repo / ".git").exists():
        print(
            f"error: '{repo}' is not a git repository.\n"
            "       antiquarian requires git history to work — "
            "run 'git init' first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    candidates = _git_tracked_files(repo)
    _emit_soft_warnings(candidates)
    candidates = [c for c in candidates if not _is_binary_blob(repo, c)]

    exclude = exclude or []
    include = include or []

    selected: list[str] = []
    for path in candidates:
        if _path_in_dir_set(path, _HARD_SKIP_DIRS):
            if _matches_any_glob(path, include):
                selected.append(path)
            continue
        if _matches_any_glob(path, exclude):
            if _matches_any_glob(path, include):
                selected.append(path)
            continue
        selected.append(path)

    if include:
        all_seen = set(selected)
        for path in candidates:
            if path in all_seen:
                continue
            if _matches_any_glob(path, include):
                selected.append(path)

    return sorted(set(selected))
