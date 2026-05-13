"""Antiquarian CLI entry point."""

from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path

import typer

from antiquarian.detect import StatisticalBaselineDetector
from antiquarian.mining import mine_repo_history
from antiquarian.models import AuthorBaseline, SignificantChange, CommitFeatures
from antiquarian.pipeline import generate_codebase_survey, generate_file_story
from antiquarian.profile import build_author_baselines
from antiquarian.selection import select_files


class DetectorType(str, Enum):
    statistical = "statistical"


app = typer.Typer(
    name="antiquarian",
    help="Reconstruct code history narratives from git — Telephone in reverse.",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """Reconstruct code history narratives from git — Telephone in reverse."""


def _stderr(msg: str) -> None:
    typer.echo(msg, err=True)


# Surveys above this size run an unattended `claude -p` call per file. The
# warning emitted at this threshold is calibrated to "you almost certainly
# meant --only here, not --include." See issue #29.
_LARGE_SELECTION_THRESHOLD = 20


def _resolve_file_path(file: str, repo_path: Path) -> str:
    file_path_abs = Path(file)
    if file_path_abs.is_absolute():
        try:
            return str(file_path_abs.relative_to(repo_path))
        except ValueError as e:
            raise typer.BadParameter(f"{file} is not inside {repo_path}") from e
    return file


def _handle_claude_error(e: BaseException) -> None:
    if isinstance(e, subprocess.CalledProcessError):
        typer.echo(f"Error: claude -p failed (exit {e.returncode})", err=True)
        if e.stderr:
            typer.echo(e.stderr, err=True)
    elif isinstance(e, subprocess.TimeoutExpired):
        typer.echo("Error: claude -p timed out", err=True)
    raise typer.Exit(code=1)


@app.command()
def story(
    file: str = typer.Argument(..., help="Path to the file whose story to tell."),
    repo: str = typer.Option(".", help="Path to the git repository."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the SQLite cache."),
    no_prs: bool = typer.Option(
        False, "--no-prs", help="Skip PR description fetching via gh."
    ),
) -> None:
    """Tell the story of a file's evolution through git history."""
    repo_path = Path(repo).resolve()
    file_path_rel = _resolve_file_path(file, repo_path)

    try:
        narrative, _ = generate_file_story(
            repo_path,
            file_path_rel,
            use_cache=not no_cache,
            fetch_prs=not no_prs,
            log=_stderr,
        )
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _handle_claude_error(e)

    typer.echo(narrative)


@app.command()
def survey(
    repo: str = typer.Option(".", help="Path to the git repository."),
    include: list[str] = typer.Option(
        [],
        "--include",
        help=(
            "Glob to ADD to the default candidate set (the repo's tracked files). "
            "Does NOT restrict — pairs with --exclude to subtract or --only to pin. "
            "Repeatable."
        ),
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Glob to SUBTRACT from the candidate set. Repeatable.",
    ),
    only: list[str] = typer.Option(
        [],
        "--only",
        help=(
            "Exact path. When set (repeatable), the candidate set is REPLACED "
            "by these paths — all other filters are ignored. Use this when you "
            "want 'just these N files' rather than 'everything matching X'."
        ),
    ),
    respect_gitignore: bool = typer.Option(
        True,
        "--respect-gitignore/--no-respect-gitignore",
        help="Use `git ls-files` for the candidate set (honors .gitignore).",
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the SQLite cache."),
    no_prs: bool = typer.Option(
        False, "--no-prs", help="Skip PR description fetching via gh."
    ),
) -> None:
    """Synthesize a codebase-level narrative from per-file stories."""
    repo_path = Path(repo).resolve()

    files = select_files(
        repo_path,
        include=include,
        exclude=exclude,
        only=only,
        respect_gitignore=respect_gitignore,
    )

    if not files:
        typer.echo("Error: no files matched the selection criteria.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"[survey] {len(files)} file(s) selected:", err=True)
    for f in files:
        typer.echo(f"  - {f}", err=True)

    if len(files) >= _LARGE_SELECTION_THRESHOLD and not only:
        typer.echo(
            f"[survey] WARNING: {len(files)} files will each take a claude -p call "
            f"(~30–120s plus possible retries). If you meant 'just these N files', "
            f"use --only <path> (repeatable) instead of --include.",
            err=True,
        )

    try:
        narrative, _ = generate_codebase_survey(
            repo_path,
            files,
            use_cache=not no_cache,
            fetch_prs=not no_prs,
            log=_stderr,
        )
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _handle_claude_error(e)

    typer.echo(narrative)


@app.command()
def files(
    repo: str = typer.Option(".", help="Path to the git repository."),
    include: list[str] = typer.Option(
        [],
        "--include",
        help=(
            "Glob to ADD to the default candidate set (the repo's tracked files). "
            "Does NOT restrict — pairs with --exclude to subtract or --only to pin. "
            "Repeatable."
        ),
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Glob to SUBTRACT from the candidate set. Repeatable.",
    ),
    only: list[str] = typer.Option(
        [],
        "--only",
        help=(
            "Exact path. When set (repeatable), the candidate set is REPLACED "
            "by these paths — all other filters are ignored."
        ),
    ),
    respect_gitignore: bool = typer.Option(
        True,
        "--respect-gitignore/--no-respect-gitignore",
        help="Use `git ls-files` for the candidate set (honors .gitignore).",
    ),
) -> None:
    """List files that would be analyzed, after applying selection rules."""
    selected = select_files(
        repo,
        include=include,
        exclude=exclude,
        only=only,
        respect_gitignore=respect_gitignore,
    )
    for path in selected:
        typer.echo(path)
    typer.echo(f"[selected] {len(selected)} file(s)", err=True)


def _format_header(
    detector_name: str,
    num_results: int,
    num_commits: int,
    num_authors: int,
) -> list[str]:
    return [
        f"# Significant Changes ({num_results} of {num_commits} commits)\n",
        f"**Detector:** {detector_name}",
        f"**Authors:** {num_authors}",
        f"**Commits analyzed:** {num_commits}\n",
    ]


def _format_baselines(baselines: dict[str, AuthorBaseline]) -> list[str]:
    lines = ["## Author Baselines\n"]
    for author, bl in sorted(baselines.items(), key=lambda x: -x[1].commit_share):
        lines.append(
            f"- **{author}** — {bl.sample_size} commits ({bl.commit_share:.0%}), "
            f"tenure {bl.tenure_days}d, "
            f"median msg {bl.median_message_len} chars, "
            f"median {bl.median_files_changed} files/commit"
        )
    lines.append("")
    return lines


def _format_significant_change(
    rank: int,
    sc_item: SignificantChange,
    sha_to_commit: dict[str, CommitFeatures],
) -> list[str]:
    sha = sc_item.commits[0] if sc_item.commits else "?"
    commit = sha_to_commit.get(sha)
    subject = commit.message.split("\n")[0][:80] if commit else "?"
    author = commit.author if commit else "?"
    region = sc_item.region or "root"

    lines = [
        f"### {rank}. `{sha[:10]}` (score: {sc_item.score:.2f})",
        f"**Author:** {author} | **Region:** {region}",
        f"**Subject:** {subject}",
        "**Reasons:**",
    ]
    lines.extend(f"  - {reason}" for reason in sc_item.reasons)
    lines.append("")
    return lines


@app.command()
def sc(
    repo: str = typer.Option(".", help="Path to the git repository."),
    detector: DetectorType = typer.Option(
        DetectorType.statistical, help="Detector to use."
    ),
    top: int = typer.Option(20, "--top", help="Number of top significant changes."),
) -> None:
    """Detect significant changes — commits that deviate from author baselines."""
    repo_path = Path(repo).resolve()

    _stderr(f"[sc] Mining repo history from {repo_path} ...")
    commits = mine_repo_history(repo_path)
    if not commits:
        typer.echo("No commits found.", err=True)
        raise typer.Exit(code=1)

    _stderr(f"[sc] {len(commits)} commits found. Building author baselines ...")
    baselines = build_author_baselines(commits)
    _stderr(f"[sc] {len(baselines)} author(s) profiled. Running detector ...")

    det = StatisticalBaselineDetector()
    results = det.detect(commits, baselines, top_n=top, log=_stderr)
    sha_to_commit = {c.git_sha: c for c in commits if c.git_sha}

    output = _format_header(detector.value, len(results), len(commits), len(baselines))
    output.extend(_format_baselines(baselines))
    output.append("## Top Significant Changes\n")
    for i, sc_item in enumerate(results, 1):
        output.extend(_format_significant_change(i, sc_item, sha_to_commit))

    for line in output:
        typer.echo(line)


if __name__ == "__main__":
    app()
