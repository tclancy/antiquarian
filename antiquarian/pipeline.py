"""Orchestration — from selected files to per-file stories and codebase synthesis.

The CLI wraps these functions for I/O; the survey command composes
``generate_file_story`` per file and feeds the markdown into
``synthesize_survey``.
"""

from __future__ import annotations

import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

from antiquarian.cache import (
    cache_path_for_repo,
    get_commit,
    open_cache,
    put_commit,
)
from antiquarian.identity import coalesce_by_email
from antiquarian.mining import historical_shas, mine_file_history
from antiquarian.models import CommitFeatures, TodoAnnotation
from antiquarian.narrative import synthesize_narrative, synthesize_survey
from antiquarian.profile import build_author_baselines, build_co_changes, build_regions
from antiquarian.prs import detect_github_repo, enrich_with_pr
from antiquarian.render import (
    _story_md_to_html_name,
    render_broadsheet,
    render_story_page,
    render_survey_page,
)
from antiquarian.render_data import extract_render_data
from antiquarian.todos import extract_todos

if TYPE_CHECKING:
    from antiquarian.backends import NarrativeBackend

# Inline marker prepended to every persisted story. Lets us detect a
# stale cached story without sidecar files. Lives in an HTML comment so
# Markdown renderers ignore it.
_DIGEST_MARKER_PREFIX = "<!-- antiquarian-cache-digest: "
_DIGEST_MARKER_SUFFIX = " -->"


def _coalesce_authors_by_email(commits: list[CommitFeatures]) -> list[CommitFeatures]:
    """Rewrite ``author`` to the canonical name per shared email (#147).

    Same-email is treated as a hard identity signal (see #120) — without this,
    one human committing under two names (e.g. spouse's IDE config slipped on
    a handful of commits) fragments into separate per-author baselines and
    duplicated entries in the Dramatis Personae. Leaves the email untouched —
    we're picking a display name, not changing identity. Repos with a
    ``.mailmap`` already get the maintainer-declared canonical via
    ``render_data._apply_mailmap``; this is the no-mailmap safety net.
    """
    mapping = coalesce_by_email((c.author, c.author_email) for c in commits)
    if not mapping:
        return commits
    return [
        replace(c, author=mapping[c.author_email.lower()])
        if c.author_email.lower() in mapping
        else c
        for c in commits
    ]


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


@dataclass(frozen=True)
class _MiningResult:
    """Output of the git-mining phase for one file.

    Carries everything ``_synthesize_story_from_mining`` needs to produce a
    narrative without re-touching the git repo. Separating the phases lets the
    survey pipeline mine all files serially (PyDriller is not safe for
    concurrent ``Repository`` opens on the same clone — see issue #104) and
    then parallelize the expensive, repo-free ``claude -p`` calls.

    Sequence fields are tuples (not lists) so the dataclass is genuinely
    immutable — each instance is handed to exactly one synthesis thread.
    """

    file_path: str
    repo_name: str
    commits: tuple[CommitFeatures, ...]
    todos: tuple[TodoAnnotation, ...]
    story_file: Path
    digest: str


def _mine_file_for_story(
    repo_path: Path,
    file_path: str,
    *,
    use_cache: bool = True,
    fetch_prs: bool = True,
    log: Callable[[str], None] = _noop,
) -> _MiningResult:
    """Phase 1: git mining + TODO extraction + cache I/O for one file.

    Touches PyDriller and the SQLite cache; **must run single-threaded per
    repo** (issue #104). Cheap enough to run inline before the parallel
    narrative phase.
    """
    full_file_path = repo_path / file_path
    if not full_file_path.exists():
        raise FileNotFoundError(f"file not found at {full_file_path}")

    gh = detect_github_repo(repo_path) if fetch_prs else None
    repo_name = f"{gh[0]}/{gh[1]}" if gh else repo_path.name

    log(f"[mining] {file_path} in {repo_name}")

    db_path = cache_path_for_repo(repo_path)
    commits: list[CommitFeatures] = []

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

    return _MiningResult(
        file_path=file_path,
        repo_name=repo_name,
        commits=tuple(commits),
        todos=tuple(todos),
        story_file=story_file,
        digest=_story_digest(commits, todos),
    )


def _synthesize_story_from_mining(
    mining: _MiningResult,
    *,
    use_cache: bool = True,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> tuple[str, Path]:
    """Phase 2: read cached story or run ``synthesize_narrative``; persist.

    Pure repo-free work (the ``claude -p`` call dominates). Safe to call from
    multiple threads — each invocation touches a distinct ``story_file``.
    """
    if use_cache:
        cached = _read_cached_story(mining.story_file)
        if cached is not None and cached[0] == mining.digest:
            log(f"[narrative] reusing cached story at {mining.story_file}")
            return cached[1], mining.story_file

    log("[narrative] sending to claude -p (this may take a minute)...")
    narrative = synthesize_narrative(
        file_path=mining.file_path,
        repo_name=mining.repo_name,
        commits=mining.commits,
        todos=mining.todos,
        log=log,
        backend=backend,
    )

    mining.story_file.write_text(
        _format_story_with_marker(narrative, mining.digest), encoding="utf-8"
    )
    log(f"[wrote] {mining.story_file}")

    return narrative, mining.story_file


def generate_file_story(
    repo_path: Path,
    file_path: str,
    *,
    use_cache: bool = True,
    fetch_prs: bool = True,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> tuple[str, Path]:
    """Mine + cache + extract TODOs + synthesize a per-file narrative.

    Returns ``(narrative_markdown, path_to_persisted_story)``. The story is
    persisted under ``<repo>/.antiquarian/stories/`` so re-runs and downstream
    commands (e.g. ``survey``) can re-use it.
    """
    mining = _mine_file_for_story(
        repo_path,
        file_path,
        use_cache=use_cache,
        fetch_prs=fetch_prs,
        log=log,
    )
    return _synthesize_story_from_mining(
        mining, use_cache=use_cache, log=log, backend=backend
    )


def _stub_narrative_for_skipped(file_path: str, reason: str) -> str:
    """Voice-rule-compliant stub for a file the narrative engine couldn't process.

    The survey synthesizer already has a "Where the channel went dark" section
    in its system prompt; a stub that frames the gap in those terms gets
    naturally absorbed into that section. We avoid persisting these stubs to
    disk — see ``generate_codebase_survey`` — so a subsequent run gets a
    fresh attempt rather than caching the failure.
    """
    return (
        "## Origin\n"
        "The narrative engine could not reconstruct this file's history "
        f"within the session's budget. The channel went dark here.\n\n"
        "## Major arcs\n"
        "The rationale for this file's evolution is unrecoverable from the "
        f"surviving artifacts within the current session's compute budget. "
        f"Reason: {reason}.\n\n"
        "## TODO/FIXME aging\n"
        "Unrecoverable in this session.\n\n"
        "## People & ownership\n"
        "Unrecoverable in this session.\n"
    )


def _threadsafe_log(
    lock: threading.Lock, log: Callable[[str], None]
) -> Callable[[str], None]:
    """Wrap a log callback so concurrent threads don't interleave lines."""

    def _locked(msg: str) -> None:
        with lock:
            log(msg)

    return _locked


def _synthesize_for_survey(
    mining: _MiningResult,
    *,
    use_cache: bool,
    log: Callable[[str], None],
    backend: NarrativeBackend | None,
) -> tuple[str, str, str | None]:
    """Run the narrative phase with survey-level error handling.

    Returns ``(file_path, narrative_or_stub, skip_reason_or_none)``.
    """
    fp = mining.file_path
    try:
        narrative, _ = _synthesize_story_from_mining(
            mining,
            use_cache=use_cache,
            log=lambda m: log(f"  {m}"),
            backend=backend,
        )
        return fp, narrative, None
    except subprocess.TimeoutExpired:
        reason = "claude -p timed out after all retry attempts"
        log(f"[survey] {fp} — {reason}; stubbing and continuing (#34)")
        return fp, _stub_narrative_for_skipped(fp, reason), "timeout"
    except subprocess.CalledProcessError as e:
        reason = f"claude -p exited {e.returncode} after all retry attempts"
        log(f"[survey] {fp} — {reason}; stubbing and continuing (#34)")
        return fp, _stub_narrative_for_skipped(fp, reason), f"exit-{e.returncode}"


def generate_codebase_survey(
    repo_path: Path,
    file_paths: Sequence[str],
    *,
    use_cache: bool = True,
    fetch_prs: bool = True,
    max_workers: int = 1,
    log: Callable[[str], None] = _noop,
    backend: NarrativeBackend | None = None,
) -> tuple[str, Path]:
    """For each file, ensure its story exists, then synthesize a codebase narrative.

    Returns ``(survey_markdown, path_to_persisted_survey)``. The synthesis input
    is the per-file markdown stories — prose-intermediate composition per the
    issue #7 design.

    Per issue #104, the parallelism boundary is drawn around the
    ``claude -p`` narrative call only — git mining (PyDriller's ``Repository``
    open writes ``.git/config`` on every instantiation) runs serially for every
    file first. Concurrent PyDriller opens on the same clone race on
    ``.git/config.lock``; the narrative call is the expensive, I/O-bound part
    that benefits from a pool. When *max_workers* > 1, mining still proceeds
    serially; only the per-file ``synthesize_narrative`` calls run in the pool.
    File ordering in the synthesis input is preserved regardless of completion
    order.

    Per #34, if a single file's narrative synthesis hangs or errors past the
    retry budget, the survey does NOT tank — it substitutes a "channel went
    dark" stub for that file and continues. The stub is in-memory only (not
    persisted), so subsequent runs get a fresh attempt. The stub is voice-
    rule-compliant so the survey synthesis can absorb it into its
    "Where the channel went dark" section without confabulation.

    Single-file ``generate_file_story`` calls still propagate the exception —
    that path is for interactive debugging and should fail loudly.
    """
    if not file_paths:
        raise ValueError("survey requires at least one file path")

    gh = detect_github_repo(repo_path) if fetch_prs else None
    repo_name = f"{gh[0]}/{gh[1]}" if gh else repo_path.name

    effective_workers = min(max_workers, len(file_paths))
    if effective_workers > 1:
        log(
            f"[survey] {repo_name}: {len(file_paths)} file(s), {effective_workers} workers"
        )
    else:
        log(f"[survey] {repo_name}: {len(file_paths)} file(s)")

    log_lock = threading.Lock()
    safe_log = _threadsafe_log(log_lock, log) if effective_workers > 1 else log

    # Phase 1: serial git mining for every file. PyDriller's `Repository` open
    # writes `.git/config`, so concurrent opens on the same clone race on
    # `.git/config.lock` — keep this loop single-threaded (#104). The plain
    # `log` (not `safe_log`) is fine here precisely because this loop is
    # serial; if anyone parallelizes mining later, switch both call sites to
    # `safe_log`.
    mining_results: list[_MiningResult] = []
    for i, fp in enumerate(file_paths, start=1):
        log(f"[survey] ({i}/{len(file_paths)}) mining {fp}")
        mining_results.append(
            _mine_file_for_story(
                repo_path,
                fp,
                use_cache=use_cache,
                fetch_prs=fetch_prs,
                log=lambda m: log(f"  {m}"),
            )
        )

    file_stories: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    # Phase 2: synthesize narratives. Parallel when workers > 1 — these calls
    # are repo-free; the only shared mutable state is `log`, which we wrap in
    # `safe_log`.
    if effective_workers <= 1:
        for i, mining in enumerate(mining_results, start=1):
            safe_log(f"[survey] ({i}/{len(file_paths)}) {mining.file_path}")
            fp, narrative, skip_reason = _synthesize_for_survey(
                mining,
                use_cache=use_cache,
                log=safe_log,
                backend=backend,
            )
            if skip_reason:
                skipped.append((fp, skip_reason))
            file_stories.append((fp, narrative))
    else:
        results: dict[str, tuple[str, str | None]] = {}
        completed = 0
        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            futures = {
                pool.submit(
                    _synthesize_for_survey,
                    mining,
                    use_cache=use_cache,
                    log=safe_log,
                    backend=backend,
                ): mining.file_path
                for mining in mining_results
            }
            for future in as_completed(futures):
                fp, narrative, skip_reason = future.result()
                results[fp] = (narrative, skip_reason)
                completed += 1
                if skip_reason:
                    safe_log(
                        f"[survey] ({completed}/{len(file_paths)}) {fp} — stubbed ({skip_reason})"
                    )
                else:
                    safe_log(f"[survey] ({completed}/{len(file_paths)}) {fp} — done")

        for fp in file_paths:
            narrative, skip_reason = results[fp]
            if skip_reason:
                skipped.append((fp, skip_reason))
            file_stories.append((fp, narrative))

    if skipped:
        log(
            f"[survey] {len(skipped)} of {len(file_paths)} file(s) stubbed "
            f"due to claude -p failures: " + ", ".join(f"{p} ({r})" for p, r in skipped)
        )

    log("[survey] building structural signals (authors, regions, co-changes)...")
    db_path = cache_path_for_repo(repo_path)
    all_commits: list[CommitFeatures] = []
    seen_shas: set[str] = set()
    with open_cache(db_path) as conn:
        for fp in file_paths:
            shas = historical_shas(repo_path, fp)
            for sha in shas:
                if sha in seen_shas:
                    continue
                cached = get_commit(conn, sha, fp)
                if cached is not None:
                    all_commits.append(cached)
                    seen_shas.add(sha)
    all_commits = _coalesce_authors_by_email(all_commits)
    author_baselines = build_author_baselines(all_commits)
    regions = build_regions(all_commits)
    co_changes = build_co_changes(all_commits)
    log(
        f"[survey] {len(author_baselines)} author baseline(s), "
        f"{len(regions)} region(s), {len(co_changes)} co-change pair(s)"
    )

    log(f"[survey] synthesizing codebase narrative from {len(file_stories)} stories...")
    survey = synthesize_survey(
        repo_name=repo_name,
        file_stories=file_stories,
        author_baselines=author_baselines,
        regions=regions,
        co_changes=co_changes,
        log=log,
        backend=backend,
    )

    surveys_dir = repo_path / ".antiquarian" / "surveys"
    surveys_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1("|".join(sorted(file_paths)).encode()).hexdigest()[:12]
    survey_file = surveys_dir / f"survey-{h}.md"
    survey_file.write_text(survey + "\n", encoding="utf-8")
    log(f"[wrote] {survey_file}")

    return survey, survey_file


# --------------------------------------------------------------------------
# Broadsheet rendering (from already-surveyed repo to a self-contained tree)
# --------------------------------------------------------------------------


def _render_story_pages(
    repo_path: Path,
    data: dict,
    pages_dir: Path,
    *,
    workers: int,
    log: Callable[[str], None],
) -> set[str]:
    """Render one HTML page per persisted story; return the names rendered.

    The broadsheet index only links stories that actually got a page, so the
    returned set feeds ``render_broadsheet(stories_with_pages=...)``.
    """
    stories_dir = repo_path / ".antiquarian" / "stories"
    if not stories_dir.exists():
        return set()

    pages_dir.mkdir(parents=True, exist_ok=True)
    candidates = [n for n in data.get("stories", []) if (stories_dir / n).exists()]

    # Pre-compute the sidebar inputs once: all surveyed files and the full set
    # of candidates (all have story pages, by definition of this function).
    all_files: list[str] = data.get("files", [])
    all_candidates: set[str] = set(candidates)

    # Detect the link backend once per render — pure config, no per-file
    # cost. A non-GitHub remote degrades to NoopLinkBackend, leaving refs
    # as plain text (#113).
    from antiquarian.link_backend import detect_link_backend

    link_backend = detect_link_backend(repo_path)

    def _render_one(story_md_name: str) -> str:
        file_path = story_md_name.replace("__", "/").removesuffix(".md")
        story_md = (stories_dir / story_md_name).read_text(encoding="utf-8")
        story_html = render_story_page(
            file_path,
            story_md,
            data["project"],
            all_files=all_files,
            files_with_stories=all_candidates,
            link_backend=link_backend,
        )
        (pages_dir / _story_md_to_html_name(story_md_name)).write_text(
            story_html, encoding="utf-8"
        )
        return story_md_name

    rendered: set[str] = set()
    effective = min(workers, len(candidates)) if candidates else 1
    if effective > 1:
        with ThreadPoolExecutor(max_workers=effective) as pool:
            rendered.update(pool.map(_render_one, candidates))
    else:
        for name in candidates:
            rendered.add(_render_one(name))
    log(f"[render] {len(rendered)} story page(s) → {pages_dir}")
    return rendered


def _render_survey_page(
    repo_path: Path,
    data: dict,
    output_dir: Path,
    *,
    log: Callable[[str], None],
) -> bool:
    """Render the latest survey alongside the index; return whether one existed."""
    surveys_dir = repo_path / ".antiquarian" / "surveys"
    if not surveys_dir.exists():
        return False
    survey_files = sorted(surveys_dir.glob("*.md"))
    if not survey_files:
        return False

    survey_md = survey_files[-1].read_text(encoding="utf-8")
    survey_html = render_survey_page(survey_md, data["project"], len(data["files"]))
    survey_out = output_dir / "survey.html"
    survey_out.write_text(survey_html, encoding="utf-8")
    log(f"[render] survey page → {survey_out}")
    return True


def render_broadsheet_site(
    repo_path: Path,
    output_path: Path,
    *,
    workers: int = 4,
    log: Callable[[str], None] = _noop,
) -> Path:
    """Render a self-contained broadsheet tree for an already-surveyed repo.

    Reads the per-file stories, survey, and cache that ``story``/``survey``
    runs persisted under ``<repo>/.antiquarian/`` and writes ``index.html``
    plus a ``stories/`` directory (and an optional ``survey.html``) rooted at
    *output_path*'s parent. Makes no ``claude -p`` calls — it only composes
    what earlier passes produced. Returns the written index path.

    Raises :class:`FileNotFoundError` if the repo has no antiquarian cache
    yet (i.e. ``story``/``survey`` has never run against it).
    """
    cache_db = repo_path / ".antiquarian" / "cache.db"
    if not cache_db.exists():
        raise FileNotFoundError(
            f"no antiquarian cache at {cache_db}. "
            "Run `antiquarian story` or `antiquarian survey` first."
        )

    log(f"[render] extracting data from {repo_path}")
    data = extract_render_data(repo_path)
    log(
        f"[render] {len(data['files'])} file(s), {len(data['commits'])} commit(s), "
        f"{len(data['arcs'])} arc(s), {len(data['todos'])} todo(s)"
    )

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_stories = _render_story_pages(
        repo_path, data, output_dir / "stories", workers=workers, log=log
    )
    has_survey = _render_survey_page(repo_path, data, output_dir, log=log)

    html = render_broadsheet(
        data, stories_with_pages=rendered_stories, has_survey=has_survey
    )
    output_path.write_text(html, encoding="utf-8")
    log(f"[render] wrote {output_path}")
    return output_path
