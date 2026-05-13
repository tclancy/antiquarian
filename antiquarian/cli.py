"""Antiquarian CLI entry point."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from antiquarian.pipeline import generate_codebase_survey, generate_file_story
from antiquarian.render import (
    _story_md_to_html_name,
    render_broadsheet,
    render_story_page,
)
from antiquarian.render_data import extract_render_data
from antiquarian.selection import select_files

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


@app.command()
def render(
    repo: str = typer.Option(".", help="Path to the git repository."),
    output: str = typer.Option(
        "",
        "--output",
        "-o",
        help="Output HTML path. Defaults to <repo>/.antiquarian/render/index.html.",
    ),
) -> None:
    """Render the antiquarian broadsheet — a self-contained HTML page (#40).

    Pulls the per-file stories and cache.db rows that already exist under
    ``<repo>/.antiquarian/`` and emits a hand-set SVG broadsheet alongside
    them. Does not call ``claude -p``; only reads what previous ``story`` /
    ``survey`` runs already produced.
    """
    repo_path = Path(repo).resolve()
    cache_db = repo_path / ".antiquarian" / "cache.db"
    if not cache_db.exists():
        typer.echo(
            f"Error: no antiquarian cache at {cache_db}. "
            "Run `antiquarian story` or `antiquarian survey` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    output_path = (
        Path(output).resolve()
        if output
        else repo_path / ".antiquarian" / "render" / "index.html"
    )

    _stderr(f"[render] extracting data from {repo_path}")
    data = extract_render_data(repo_path)
    _stderr(
        f"[render] {len(data['files'])} file(s), {len(data['commits'])} commit(s), "
        f"{len(data['arcs'])} arc(s), {len(data['todos'])} todo(s)"
    )

    # Render per-file story pages alongside the index so the broadsheet's
    # "files surveyed" links resolve (#46). One HTML per story.md in the
    # cache; index links only the ones that actually got rendered.
    stories_dir = repo_path / ".antiquarian" / "stories"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages_dir = output_path.parent / "stories"
    rendered_stories: set[str] = set()
    if stories_dir.exists():
        pages_dir.mkdir(parents=True, exist_ok=True)
        for story_md_name in data.get("stories", []):
            story_md_path = stories_dir / story_md_name
            if not story_md_path.exists():
                continue
            file_path = story_md_name.replace("__", "/").removesuffix(".md")
            story_md = story_md_path.read_text(encoding="utf-8")
            story_html = render_story_page(file_path, story_md, data["project"])
            target = pages_dir / _story_md_to_html_name(story_md_name)
            target.write_text(story_html, encoding="utf-8")
            rendered_stories.add(story_md_name)
        _stderr(f"[render] {len(rendered_stories)} story page(s) → {pages_dir}")

    html = render_broadsheet(data, stories_with_pages=rendered_stories)
    output_path.write_text(html, encoding="utf-8")
    _stderr(f"[render] wrote {output_path}")
    typer.echo(str(output_path))


if __name__ == "__main__":
    app()
