"""Orchestration — from selected files to per-file stories and codebase synthesis.

The CLI wraps these functions for I/O; the survey command composes
``generate_file_story`` per file and feeds the markdown into
``synthesize_survey``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Sequence

from antiquarian.cache import (
    cache_path_for_repo,
    get_commit,
    open_cache,
    put_commit,
)
from antiquarian.mining import historical_shas, mine_file_history
from antiquarian.narrative import synthesize_narrative, synthesize_survey
from antiquarian.prs import detect_github_repo, enrich_with_pr
from antiquarian.todos import extract_todos


def _noop(_msg: str) -> None:
    pass


def generate_file_story(
    repo_path: Path,
    file_path: str,
    *,
    use_cache: bool = True,
    fetch_prs: bool = True,
    log: Callable[[str], None] = _noop,
) -> tuple[str, Path]:
    """Mine + cache + extract TODOs + synthesize a per-file narrative.

    Returns ``(narrative_markdown, path_to_persisted_story)``. The story is
    persisted under ``<repo>/.antiquarian/stories/`` so re-runs and downstream
    commands (e.g. ``survey``) can re-use it.
    """
    full_file_path = repo_path / file_path
    if not full_file_path.exists():
        raise FileNotFoundError(f"file not found at {full_file_path}")

    gh = detect_github_repo(repo_path) if fetch_prs else None
    repo_name = f"{gh[0]}/{gh[1]}" if gh else repo_path.name

    log(f"[mining] {file_path} in {repo_name}")

    db_path = cache_path_for_repo(repo_path)
    commits = []

    with open_cache(db_path) as conn:
        shas = historical_shas(repo_path, file_path)
        log(f"[mining] {len(shas)} commits in history")

        cached_shas: set[str] = set()
        if use_cache:
            for sha in shas:
                cached = get_commit(conn, sha, file_path)
                if cached is not None:
                    commits.append(cached)
                    cached_shas.add(sha)

        remaining = [s for s in shas if s not in cached_shas]
        if remaining:
            log(f"[mining] processing {len(remaining)} new commits")
            for cf in mine_file_history(repo_path, file_path):
                if cf.git_sha in cached_shas:
                    continue
                if gh:
                    cf = enrich_with_pr(cf, *gh)
                put_commit(conn, cf, file_path)
                commits.append(cf)
        else:
            log("[mining] all commits already cached")

    commits.sort(key=lambda c: c.timestamp)

    log("[todos] extracting from current HEAD")
    todos = list(extract_todos(repo_path, file_path))
    log(f"[todos] found {len(todos)} annotation(s)")

    log("[narrative] sending to claude -p (this may take a minute)...")
    narrative = synthesize_narrative(
        file_path=file_path,
        repo_name=repo_name,
        commits=commits,
        todos=todos,
    )

    stories_dir = repo_path / ".antiquarian" / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path.replace("/", "__") + ".md"
    story_file = stories_dir / safe_name
    story_file.write_text(narrative + "\n", encoding="utf-8")
    log(f"[wrote] {story_file}")

    return narrative, story_file


def generate_codebase_survey(
    repo_path: Path,
    file_paths: Sequence[str],
    *,
    use_cache: bool = True,
    fetch_prs: bool = True,
    log: Callable[[str], None] = _noop,
) -> tuple[str, Path]:
    """For each file, ensure its story exists, then synthesize a codebase narrative.

    Returns ``(survey_markdown, path_to_persisted_survey)``. The synthesis input
    is the per-file markdown stories — prose-intermediate composition per the
    issue #7 design.
    """
    if not file_paths:
        raise ValueError("survey requires at least one file path")

    gh = detect_github_repo(repo_path) if fetch_prs else None
    repo_name = f"{gh[0]}/{gh[1]}" if gh else repo_path.name

    log(f"[survey] {repo_name}: {len(file_paths)} file(s)")

    file_stories: list[tuple[str, str]] = []
    for i, fp in enumerate(file_paths, start=1):
        log(f"[survey] ({i}/{len(file_paths)}) {fp}")
        narrative, _ = generate_file_story(
            repo_path,
            fp,
            use_cache=use_cache,
            fetch_prs=fetch_prs,
            log=lambda m: log(f"  {m}"),
        )
        file_stories.append((fp, narrative))

    log(f"[survey] synthesizing codebase narrative from {len(file_stories)} stories...")
    survey = synthesize_survey(
        repo_name=repo_name,
        file_stories=file_stories,
    )

    surveys_dir = repo_path / ".antiquarian" / "surveys"
    surveys_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1("|".join(sorted(file_paths)).encode()).hexdigest()[:12]
    survey_file = surveys_dir / f"survey-{h}.md"
    survey_file.write_text(survey + "\n", encoding="utf-8")
    log(f"[wrote] {survey_file}")

    return survey, survey_file
