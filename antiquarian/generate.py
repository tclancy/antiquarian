"""Gallery generation driver (#93) — the expensive, API-key half of Option B.

``antiquarian gallery build`` (#92) only assembles broadsheets that already
exist on disk. This module produces them: for each repo in a ``gallery.toml``
manifest it clones the repo, runs the ``survey`` + ``render`` pipeline, and
copies the resulting broadsheet into the manifest's ``render_dir`` — so one
reproducible command turns a manifest into N populated render dirs ready for
``gallery build``.

Two design choices deserve a note, both answering questions the issue raised:

* **Full clone, not shallow.** The issue text says "shallow-clone", but
  antiquarian's whole job is git archaeology — ``mining.historical_shas``
  walks ``git log --follow`` over a file's entire history. A ``--depth 1``
  clone would hand the narrator 0–1 commits and defeat the tool, so we clone
  full history.
* **A cost gate is mandatory.** This is the path that spends real tokens. The
  driver refuses to run without first printing a token/cost estimate and
  getting an explicit confirmation (``--yes`` or an interactive prompt). It is
  idempotent: a repo whose ``render_dir`` is already populated is skipped
  unless ``--force``.

The clone / survey / render steps are injected (see :func:`run_generation`)
so the orchestration is testable without real git or ``claude -p`` calls.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from antiquarian.gallery import GalleryManifest, RepoEntry
from antiquarian.pipeline import generate_codebase_survey, render_broadsheet_site
from antiquarian.selection import select_files

# Conservative per-file cost ceiling, in USD. The #86 adoption research
# observed $0.83–2.50 for a 500-file run (~$0.0017–0.005/file); we pad to a
# round upper bound so the estimate shown to the operator overstates rather
# than understates. This is a ceiling for the confirm gate, not a forecast.
_COST_CEILING_PER_FILE_USD = 0.02

# How deep to clone. None means full history — required for narrative mining
# (see module docstring). Exposed as a constant so the rationale has one home.
_CLONE_DEPTH: int | None = None


class GenerationError(Exception):
    """Raised when generation cannot proceed (clone failure, bad manifest)."""


def _noop(_msg: str) -> None:
    pass


@dataclass(frozen=True)
class RepoPlan:
    """One repo's place in the generation plan."""

    repo: RepoEntry
    render_path: Path  # absolute, resolved render_dir
    already_done: bool  # render_dir already holds an index.html


@dataclass(frozen=True)
class CostEstimate:
    """Up-front cost ceiling for the repos that will actually be generated."""

    repo_count: int
    total_files: int
    ceiling_usd: float


@dataclass(frozen=True)
class GenerationReport:
    """Outcome of a generation run: what got built and what failed.

    Generation is resilient per-repo — one repo's survey/render blowing up
    does not abort the batch (and the tokens already spent on the repos that
    succeeded are not wasted). The caller inspects ``failed`` to report and
    set a non-zero exit code.
    """

    generated: list[RepoPlan]
    failed: list[tuple[str, str]]  # (slug, error message)


# Injected step signatures — defaults wrap real git / pipeline calls.
CloneFn = Callable[[str, Path], None]
SurveyFn = Callable[[Path], None]
RenderFn = Callable[[Path, Path], None]


# --------------------------------------------------------------------------
# Planning (cheap — no clones, no API)
# --------------------------------------------------------------------------


def plan_repos(
    manifest: GalleryManifest, manifest_dir: Path, *, force: bool
) -> tuple[list[RepoPlan], list[RepoPlan]]:
    """Partition the manifest into (to_generate, skipped).

    A repo is skipped when its ``render_dir`` already contains an
    ``index.html`` and ``force`` is False — that is the idempotency contract:
    re-running only fills the gaps. With ``force`` every repo is regenerated.
    """
    to_generate: list[RepoPlan] = []
    skipped: list[RepoPlan] = []
    for repo in manifest.repos:
        render_path = (manifest_dir / repo.render_dir).resolve()
        done = (render_path / "index.html").exists()
        plan = RepoPlan(repo=repo, render_path=render_path, already_done=done)
        if done and not force:
            skipped.append(plan)
        else:
            to_generate.append(plan)
    return to_generate, skipped


def estimate_cost(total_files: int, repo_count: int) -> CostEstimate:
    """Build the cost ceiling shown before the confirm gate."""
    return CostEstimate(
        repo_count=repo_count,
        total_files=total_files,
        ceiling_usd=round(total_files * _COST_CEILING_PER_FILE_USD, 2),
    )


# --------------------------------------------------------------------------
# Default step implementations (real git + pipeline)
# --------------------------------------------------------------------------


def clone_repo(github_url: str, dest: Path) -> None:
    """Clone *github_url* into *dest* with full history (see module docstring)."""
    cmd = ["git", "clone"]
    if _CLONE_DEPTH is not None:
        cmd += ["--depth", str(_CLONE_DEPTH)]
    cmd += [github_url, str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise GenerationError(
            f"git clone failed for {github_url}: {e.stderr.strip() or e}"
        ) from e


def survey_repo(repo_path: Path, *, workers: int = 4) -> None:
    """Run the full survey pipeline against an already-cloned repo.

    Parallelizes per-file story generation by default (matching the
    interactive ``survey`` command) — gallery targets are large famous repos,
    so serial ``claude -p`` calls would be needlessly slow.
    """
    try:
        files = select_files(repo_path)
    except SystemExit as e:  # select_files exits on a non-git dir
        raise GenerationError(f"{repo_path} is not a git repository") from e
    if not files:
        raise GenerationError(f"no files selected to survey in {repo_path}")
    generate_codebase_survey(repo_path, files, max_workers=workers)


def render_repo(repo_path: Path, render_dir: Path, *, workers: int = 4) -> None:
    """Render the broadsheet tree for a surveyed repo into *render_dir*."""
    render_broadsheet_site(repo_path, render_dir / "index.html", workers=workers)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _count_files(repo_path: Path) -> int:
    """File count used for the cost estimate; 0 if selection fails.

    ``select_files`` raises ``SystemExit`` for a non-git directory, so that is
    caught alongside I/O errors — a bad clone should yield a zero estimate, not
    crash the whole run before the confirm gate.
    """
    try:
        return len(select_files(repo_path))
    except (OSError, subprocess.CalledProcessError, SystemExit):
        return 0


def _generate_one(
    plan: RepoPlan,
    clone_dir: Path,
    *,
    survey_fn: SurveyFn,
    render_fn: RenderFn,
    log: Callable[[str], None],
) -> None:
    """Survey + render one cloned repo into its manifest ``render_dir``.

    On ``--force`` the existing ``render_dir`` is cleared first so a stale
    broadsheet can't survive a regeneration.
    """
    log(f"[generate] {plan.repo.slug}: survey")
    survey_fn(clone_dir)
    log(f"[generate] {plan.repo.slug}: render → {plan.render_path}")
    if plan.render_path.exists():
        shutil.rmtree(plan.render_path)
    plan.render_path.mkdir(parents=True, exist_ok=True)
    render_fn(clone_dir, plan.render_path)


def run_generation(
    manifest: GalleryManifest,
    manifest_dir: Path,
    *,
    force: bool,
    confirm: Callable[[CostEstimate], bool],
    clone_fn: CloneFn = clone_repo,
    survey_fn: SurveyFn = survey_repo,
    render_fn: RenderFn = render_repo,
    count_fn: Callable[[Path], int] = _count_files,
    log: Callable[[str], None] = _noop,
) -> GenerationReport:
    """Clone, survey, and render every to-be-generated repo in the manifest.

    Order of operations is the cost gate's whole reason for existing:
    1. Partition into to-generate vs. already-done (idempotency).
    2. Clone the to-generate repos and count their files (cheap, no API).
    3. Show a cost ceiling and ask *confirm* — abort if it returns False.
    4. Only then run the token-spending survey + render per repo.

    Returns a :class:`GenerationReport`. ``confirm`` receives the
    :class:`CostEstimate` and returns whether to proceed; the CLI wires this
    to ``--yes`` or an interactive prompt.

    The per-repo loop is resilient: a survey/render failure on one repo is
    recorded in ``report.failed`` and the batch continues, so a single bad
    repo can't strand the (already paid-for) broadsheets that succeeded.
    """
    to_generate, skipped = plan_repos(manifest, manifest_dir, force=force)
    for plan in skipped:
        log(f"[generate] skip {plan.repo.slug} — render_dir already populated")

    if not to_generate:
        log("[generate] nothing to do — all render dirs already populated")
        return GenerationReport(generated=[], failed=[])

    with tempfile.TemporaryDirectory(prefix="antiquarian-gallery-") as tmp:
        workdir = Path(tmp)
        clones = _clone_all(to_generate, workdir, clone_fn=clone_fn, log=log)

        total_files = sum(count_fn(clone) for clone in clones.values())
        estimate = estimate_cost(total_files, len(to_generate))
        if not confirm(estimate):
            log("[generate] aborted before any API calls — nothing generated")
            return GenerationReport(generated=[], failed=[])

        return _generate_all(
            to_generate, clones, survey_fn=survey_fn, render_fn=render_fn, log=log
        )


def _generate_all(
    to_generate: list[RepoPlan],
    clones: dict[str, Path],
    *,
    survey_fn: SurveyFn,
    render_fn: RenderFn,
    log: Callable[[str], None],
) -> GenerationReport:
    """Run survey + render for each planned repo, tolerating per-repo failures."""
    generated: list[RepoPlan] = []
    failed: list[tuple[str, str]] = []
    for plan in to_generate:
        try:
            _generate_one(
                plan,
                clones[plan.repo.slug],
                survey_fn=survey_fn,
                render_fn=render_fn,
                log=log,
            )
            generated.append(plan)
        except (
            GenerationError,
            OSError,
            subprocess.SubprocessError,
        ) as e:
            log(f"[generate] FAILED {plan.repo.slug}: {e}")
            failed.append((plan.repo.slug, str(e)))
    return GenerationReport(generated=generated, failed=failed)


def _clone_all(
    plans: list[RepoPlan],
    workdir: Path,
    *,
    clone_fn: CloneFn,
    log: Callable[[str], None],
) -> dict[str, Path]:
    """Clone every planned repo into *workdir*; return slug → clone path."""
    clones: dict[str, Path] = {}
    for plan in plans:
        dest = workdir / plan.repo.slug
        log(f"[generate] clone {plan.repo.slug} ← {plan.repo.github_url}")
        clone_fn(plan.repo.github_url, dest)
        clones[plan.repo.slug] = dest
    return clones
