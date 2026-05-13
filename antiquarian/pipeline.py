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
from antiquarian.models import CommitFeatures, TodoAnnotation
from antiquarian.narrative import synthesize_narrative, synthesize_survey
from antiquarian.prs import detect_github_repo, enrich_with_pr
from antiquarian.todos import extract_todos

# Inline marker prepended to every persisted story. Lets us detect a
# stale cached story without sidecar files. Lives in an HTML comment so
# Markdown renderers ignore it.
_DIGEST_MARKER_PREFIX = "<!-- antiquarian-cache-digest: "
_DIGEST_MARKER_SUFFIX = " -->"


def _noop(_msg: str) -> None:
    pass


def _story_digest(
    commits: Sequence[CommitFeatures], todos: Sequence[TodoAnnotation]
) -> str:
    """SHA1 over the inputs that determine a story's content.

    Two stories with the same digest were produced from the same commit
    set and the same TODO set, so the cached version remains valid.
    """
    h = hashlib.sha1()
    for c in commits:
        h.update((c.git_sha or c.id).encode())
        h.update(b"\0")
    h.update(b"||todos||")
    for t in todos:
        h.update(t.kind.encode())
        h.update(b"\0")
        h.update(str(t.line_number).encode())
        h.update(b"\0")
        h.update(t.text.encode())
        h.update(b"\0")
        h.update(t.introduced_commit.encode())
        h.update(b"\0")
    return h.hexdigest()


def _read_cached_story(story_file: Path) -> tuple[str, str] | None:
    """Return ``(digest, narrative)`` from a persisted story, or ``None``.

    ``narrative`` is the file content with the digest marker line stripped,
    matching what ``synthesize_narrative`` would have produced.
    """
    if not story_file.exists():
        return None
    try:
        text = story_file.read_text(encoding="utf-8")
    except OSError:
        return None
    first, _, rest = text.partition("\n")
    if not (
        first.startswith(_DIGEST_MARKER_PREFIX)
        and first.endswith(_DIGEST_MARKER_SUFFIX)
    ):
        return None
    digest = first[len(_DIGEST_MARKER_PREFIX) : -len(_DIGEST_MARKER_SUFFIX)].strip()
    return digest, rest.rstrip("\n")


def _format_story_with_marker(narrative: str, digest: str) -> str:
    return f"{_DIGEST_MARKER_PREFIX}{digest}{_DIGEST_MARKER_SUFFIX}\n{narrative}\n"


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

    stories_dir = repo_path / ".antiquarian" / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path.replace("/", "__") + ".md"
    story_file = stories_dir / safe_name

    current_digest = _story_digest(commits, todos)

    if use_cache:
        cached = _read_cached_story(story_file)
        if cached is not None and cached[0] == current_digest:
            log(f"[narrative] reusing cached story at {story_file}")
            return cached[1], story_file

    log("[narrative] sending to claude -p (this may take a minute)...")
    narrative = synthesize_narrative(
        file_path=file_path,
        repo_name=repo_name,
        commits=commits,
        todos=todos,
        log=log,
    )

    story_file.write_text(
        _format_story_with_marker(narrative, current_digest), encoding="utf-8"
    )
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
        log=log,
    )

    surveys_dir = repo_path / ".antiquarian" / "surveys"
    surveys_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1("|".join(sorted(file_paths)).encode()).hexdigest()[:12]
    survey_file = surveys_dir / f"survey-{h}.md"
    survey_file.write_text(survey + "\n", encoding="utf-8")
    log(f"[wrote] {survey_file}")

    return survey, survey_file
