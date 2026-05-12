"""Antiquarian CLI entry point."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from antiquarian.cache import (
    cache_path_for_repo,
    get_commit,
    open_cache,
    put_commit,
)
from antiquarian.mining import historical_shas, mine_file_history
from antiquarian.narrative import synthesize_narrative
from antiquarian.prs import detect_github_repo, enrich_with_pr
from antiquarian.todos import extract_todos

app = typer.Typer(
    name="antiquarian",
    help="Reconstruct code history narratives from git — Telephone in reverse.",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """Reconstruct code history narratives from git — Telephone in reverse."""


@app.command()
def story(
    file: str = typer.Argument(..., help="Path to the file whose story to tell."),
    repo: str = typer.Option(".", help="Path to the git repository."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the SQLite cache."),
    no_prs: bool = typer.Option(False, "--no-prs", help="Skip PR description fetching via gh."),
) -> None:
    """Tell the story of a file's evolution through git history."""
    repo_path = Path(repo).resolve()

    file_path_abs = Path(file)
    if file_path_abs.is_absolute():
        try:
            file_path_rel = str(file_path_abs.relative_to(repo_path))
        except ValueError:
            typer.echo(f"Error: {file} is not inside {repo_path}", err=True)
            raise typer.Exit(code=1)
    else:
        file_path_rel = file

    full_file_path = repo_path / file_path_rel
    if not full_file_path.exists():
        typer.echo(f"Error: file not found at {full_file_path}", err=True)
        raise typer.Exit(code=1)

    gh = detect_github_repo(repo_path) if not no_prs else None
    repo_name = f"{gh[0]}/{gh[1]}" if gh else repo_path.name

    typer.echo(f"[mining] {file_path_rel} in {repo_name}", err=True)

    db_path = cache_path_for_repo(repo_path)
    commits = []

    with open_cache(db_path) as conn:
        shas = historical_shas(repo_path, file_path_rel)
        typer.echo(f"[mining] {len(shas)} commits in history", err=True)

        cached_shas: set[str] = set()
        if not no_cache:
            for sha in shas:
                cached = get_commit(conn, sha, file_path_rel)
                if cached is not None:
                    commits.append(cached)
                    cached_shas.add(sha)

        remaining = [s for s in shas if s not in cached_shas]
        if remaining:
            typer.echo(f"[mining] processing {len(remaining)} new commits", err=True)
            for cf in mine_file_history(repo_path, file_path_rel):
                if cf.git_sha in cached_shas:
                    continue
                if gh:
                    cf = enrich_with_pr(cf, *gh)
                put_commit(conn, cf, file_path_rel)
                commits.append(cf)
        else:
            typer.echo("[mining] all commits already cached", err=True)

    commits.sort(key=lambda c: c.timestamp)

    typer.echo("[todos] extracting from current HEAD", err=True)
    todos = list(extract_todos(repo_path, file_path_rel))
    typer.echo(f"[todos] found {len(todos)} annotation(s)", err=True)

    typer.echo("[narrative] sending to claude -p (this may take a minute)...", err=True)
    try:
        narrative = synthesize_narrative(
            file_path=file_path_rel,
            repo_name=repo_name,
            commits=commits,
            todos=todos,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"Error: claude -p failed (exit {e.returncode})", err=True)
        if e.stderr:
            typer.echo(e.stderr, err=True)
        raise typer.Exit(code=1)
    except subprocess.TimeoutExpired:
        typer.echo("Error: claude -p timed out", err=True)
        raise typer.Exit(code=1)

    typer.echo(narrative)

    stories_dir = repo_path / ".antiquarian" / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path_rel.replace("/", "__") + ".md"
    story_file = stories_dir / safe_name
    story_file.write_text(narrative + "\n", encoding="utf-8")
    typer.echo(f"[wrote] {story_file}", err=True)


if __name__ == "__main__":
    app()
