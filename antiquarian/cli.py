"""Antiquarian CLI entry point."""

from __future__ import annotations

import typer

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
    typer.echo(f"[stub] story for {file} in {repo} (no_cache={no_cache}, no_prs={no_prs})")


if __name__ == "__main__":
    app()
