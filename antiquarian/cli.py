"""Antiquarian CLI entry point."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import typer

from antiquarian.gallery import GalleryError, build_gallery, load_manifest
from antiquarian.generate import CostEstimate, GenerationError, run_generation
from antiquarian.pipeline import (
    generate_codebase_survey,
    generate_file_story,
    render_broadsheet_site,
)
from antiquarian.prs import detect_github_repo
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
    workers: int = typer.Option(
        4,
        "--workers",
        min=1,
        max=16,
        help="Number of parallel workers for per-file story generation.",
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
            max_workers=workers,
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
    workers: int = typer.Option(
        4,
        "--workers",
        min=1,
        max=16,
        help="Number of parallel workers for story page rendering.",
    ),
) -> None:
    """Render the antiquarian broadsheet — a self-contained HTML page (#40).

    Pulls the per-file stories and cache.db rows that already exist under
    ``<repo>/.antiquarian/`` and emits a hand-set SVG broadsheet alongside
    them. Does not call ``claude -p``; only reads what previous ``story`` /
    ``survey`` runs already produced.
    """
    repo_path = Path(repo).resolve()
    output_path = (
        Path(output).resolve()
        if output
        else repo_path / ".antiquarian" / "render" / "index.html"
    )

    try:
        written = render_broadsheet_site(
            repo_path, output_path, workers=workers, log=_stderr
        )
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    typer.echo(str(written))


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Thin wrapper for `git` subprocess calls used by `ghpublish`."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
    )


@app.command()
def ghpublish(
    repo: str = typer.Option(".", help="Path to the git repository."),
    remote: str = typer.Option(
        "origin", help="Git remote to push the gh-pages branch to."
    ),
) -> None:
    """Publish the latest broadsheet render to the `gh-pages` branch (#73).

    Prototype scope: takes whatever's already in ``.antiquarian/render/``,
    constructs a fresh single-commit branch in a tempdir, and force-pushes
    it to ``<remote>:gh-pages``. Does not touch your working tree, does
    not preserve previous gh-pages history, does not check for an existing
    gh-pages set up by another tool — explicitly punted per #73.

    Run ``antiquarian render`` first (this command does not synthesize).

    After the first publish, GitHub Pages still needs to be enabled in the
    repo's Settings → Pages, with the source set to the ``gh-pages``
    branch. The command prints the exact URL to visit afterward.
    """
    import shutil
    import tempfile

    repo_path = Path(repo).resolve()
    render_dir = repo_path / ".antiquarian" / "render"
    index_html = render_dir / "index.html"
    if not index_html.exists():
        typer.echo(
            f"Error: no rendered broadsheet at {index_html}. "
            "Run `antiquarian render` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Read the remote URL from the user's repo
    try:
        remote_url = _run_git(
            ["remote", "get-url", remote], cwd=repo_path
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        typer.echo(
            f"Error: couldn't read remote `{remote}` URL from {repo_path}: "
            f"{e.stderr.strip()}",
            err=True,
        )
        raise typer.Exit(code=1)

    gh = detect_github_repo(repo_path)
    if not gh:
        typer.echo(
            "Warning: couldn't detect GitHub owner/repo — Pages URL hint "
            "below may be wrong.",
            err=True,
        )
        owner, repo_name = "<owner>", "<repo>"
    else:
        owner, repo_name = gh

    # Build the publish payload in a tempdir so we never touch the user's
    # working tree. Force-push a fresh single-commit branch — gh-pages
    # history isn't load-bearing for a "wow-factor" surface.
    with tempfile.TemporaryDirectory(prefix="antiquarian-ghpublish-") as tmp:
        tmp_path = Path(tmp)
        _stderr(f"[ghpublish] staging in {tmp_path}")

        # Copy the rendered output. `dirs_exist_ok` so we land directly in tmp.
        shutil.copytree(render_dir, tmp_path, dirs_exist_ok=True)
        # `.nojekyll` so GitHub Pages serves dotfiles + skips Jekyll
        # processing entirely. Cheap insurance, recommended by GitHub.
        (tmp_path / ".nojekyll").touch()

        _run_git(["init", "-b", "gh-pages"], cwd=tmp_path)
        _run_git(["add", "."], cwd=tmp_path)
        commit_msg = (
            f"antiquarian broadsheet @ "
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
        )
        _run_git(["commit", "-m", commit_msg], cwd=tmp_path)
        _stderr(f"[ghpublish] pushing to {remote_url} (branch: gh-pages)")
        try:
            _run_git(
                ["push", "--force", remote_url, "HEAD:gh-pages"],
                cwd=tmp_path,
            )
        except subprocess.CalledProcessError as e:
            typer.echo(
                f"Error: push failed.\n{e.stderr.strip()}",
                err=True,
            )
            raise typer.Exit(code=1)

    pages_url = f"https://{owner}.github.io/{repo_name}/"
    settings_url = f"https://github.com/{owner}/{repo_name}/settings/pages"
    typer.echo("")
    typer.echo("✓ Pushed broadsheet to the `gh-pages` branch.")
    typer.echo("")
    typer.echo("First-time setup (skip if already done):")
    typer.echo(f"  1. Visit:  {settings_url}")
    typer.echo("  2. Source: 'Deploy from a branch'")
    typer.echo("  3. Branch: gh-pages  /  Folder: / (root)")
    typer.echo("  4. Click 'Save'")
    typer.echo("")
    typer.echo(f"Your broadsheet will be live at:  {pages_url}")
    typer.echo("(GitHub Pages may take a minute or two to deploy after Save.)")


gallery_app = typer.Typer(
    name="gallery",
    help="Assemble and publish a precomputed broadsheet gallery (#86 Option B).",
    no_args_is_help=True,
)
app.add_typer(gallery_app)


@gallery_app.command("build")
def gallery_build(
    manifest: str = typer.Option(
        "gallery.toml",
        "--manifest",
        "-m",
        help="Path to the gallery manifest (TOML).",
    ),
    output: str = typer.Option(
        "gallery",
        "--output",
        "-o",
        help="Directory to assemble the gallery site into.",
    ),
) -> None:
    """Assemble a gallery site from already-rendered broadsheets (#92).

    Reads a manifest of repos (each pointing at a ``render_dir`` produced by
    ``antiquarian render``), copies every broadsheet under ``<output>/<slug>/``,
    and writes an illuminated landing page linking them — with a "do it on
    yours" call-to-action. Makes no network or ``claude -p`` calls.
    """
    manifest_path = Path(manifest).resolve()
    try:
        parsed = load_manifest(manifest_path)
        index_path = build_gallery(parsed, manifest_path.parent, Path(output).resolve())
    except GalleryError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    _stderr(
        f"[gallery] assembled {len(parsed.repos)} broadsheet(s) → {index_path.parent}"
    )
    typer.echo(str(index_path))


def _make_confirm(assume_yes: bool) -> Callable[[CostEstimate], bool]:
    """Build the cost-gate callback for ``gallery generate``.

    The estimate is *always* printed (the issue requires it). With ``--yes``
    we proceed without prompting; otherwise we ask interactively and treat any
    non-affirmative answer as abort.
    """

    def _confirm(estimate: CostEstimate) -> bool:
        _stderr(
            f"[gallery] {estimate.repo_count} repo(s), {estimate.total_files} file(s) "
            f"to generate. Estimated cost ceiling: ${estimate.ceiling_usd:.2f} "
            f"(upper bound; actual is typically lower)."
        )
        if assume_yes:
            _stderr("[gallery] --yes given; proceeding.")
            return True
        return typer.confirm("Proceed with generation (this spends API tokens)?")

    return _confirm


@gallery_app.command("generate")
def gallery_generate(
    manifest: str = typer.Option(
        "gallery.toml",
        "--manifest",
        "-m",
        help="Path to the gallery manifest (TOML).",
    ),
    assume_yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the interactive confirm (the cost estimate is still printed).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate every repo, even ones whose render_dir is already populated.",
    ),
) -> None:
    """Populate a manifest's render dirs by surveying + rendering each repo (#93).

    The expensive, API-key half of the gallery: clones each repo (full
    history — antiquarian mines it), runs ``survey`` + ``render``, and writes
    the broadsheet into the manifest's ``render_dir``. Prints a cost estimate
    and requires confirmation before spending any tokens; idempotent — skips
    repos that already have a broadsheet unless ``--force``.
    """
    manifest_path = Path(manifest).resolve()
    try:
        parsed = load_manifest(manifest_path)
        generated = run_generation(
            parsed,
            manifest_path.parent,
            force=force,
            confirm=_make_confirm(assume_yes),
            log=_stderr,
        )
    except (GalleryError, GenerationError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    _stderr(f"[gallery] generated {len(generated)} broadsheet(s).")
    for plan in generated:
        typer.echo(str(plan.render_path))


if __name__ == "__main__":
    app()
