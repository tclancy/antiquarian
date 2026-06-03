"""Tests for the gallery generation driver (#93).

The driver clones each repo in a manifest, runs survey + render, and copies
the broadsheet into the manifest's ``render_dir``. The clone / survey / render
steps are injected so these tests exercise the *orchestration* — planning,
the skip-existing idempotency contract, and the cost-confirm gate — without
any real git or ``claude -p`` calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import antiquarian.generate as generate_mod
from antiquarian.gallery import load_manifest
from antiquarian.generate import (
    CostEstimate,
    GenerationError,
    clone_repo,
    estimate_cost,
    plan_repos,
    run_generation,
)

_MANIFEST = """\
[gallery]
title = "The Antiquarian Gallery"
subtitle = "Illuminated histories"
action_url = "https://github.com/tclancy/antiquarian"

[[repos]]
slug = "requests"
name = "requests"
tagline = "HTTP for humans."
github_url = "https://github.com/psf/requests"
render_dir = "renders/requests"

[[repos]]
slug = "flask"
name = "Flask"
tagline = "A micro web framework."
github_url = "https://github.com/pallets/flask"
render_dir = "renders/flask"
"""


@pytest.fixture
def manifest_dir(tmp_path: Path) -> Path:
    (tmp_path / "gallery.toml").write_text(_MANIFEST, encoding="utf-8")
    return tmp_path


def _populate(manifest_dir: Path, slug: str) -> None:
    """Mark a repo's render_dir as already generated (has an index.html)."""
    render = manifest_dir / "renders" / slug
    render.mkdir(parents=True, exist_ok=True)
    (render / "index.html").write_text("<html>existing</html>", encoding="utf-8")


class _FakeSteps:
    """Records clone/survey/render calls and writes a fake broadsheet."""

    def __init__(self, files_per_repo: int = 3) -> None:
        self.files_per_repo = files_per_repo
        self.cloned: list[str] = []
        self.surveyed: list[Path] = []
        self.rendered: list[tuple[Path, Path]] = []

    def clone(self, github_url: str, dest: Path) -> None:
        self.cloned.append(github_url)
        dest.mkdir(parents=True, exist_ok=True)

    def survey(self, repo_path: Path) -> None:
        self.surveyed.append(repo_path)

    def render(self, repo_path: Path, render_dir: Path) -> None:
        self.rendered.append((repo_path, render_dir))
        (render_dir / "index.html").write_text("<html>fresh</html>", encoding="utf-8")

    def count(self, repo_path: Path) -> int:
        return self.files_per_repo


def _report(
    manifest_dir: Path, steps: _FakeSteps, *, force=False, confirm=lambda e: True
):
    """Run generation, returning the full GenerationReport."""
    manifest = load_manifest(manifest_dir / "gallery.toml")
    return run_generation(
        manifest,
        manifest_dir,
        force=force,
        confirm=confirm,
        clone_fn=steps.clone,
        survey_fn=steps.survey,
        render_fn=steps.render,
        count_fn=steps.count,
    )


def _run(manifest_dir: Path, steps: _FakeSteps, *, force=False, confirm=lambda e: True):
    """Run generation, returning just the list of generated repos."""
    return _report(manifest_dir, steps, force=force, confirm=confirm).generated


# --------------------------------------------------------------------------
# Planning + cost estimate
# --------------------------------------------------------------------------


def test_plan_all_fresh(manifest_dir: Path):
    manifest = load_manifest(manifest_dir / "gallery.toml")
    to_generate, skipped = plan_repos(manifest, manifest_dir, force=False)
    assert [p.repo.slug for p in to_generate] == ["requests", "flask"]
    assert skipped == []


def test_plan_skips_already_populated(manifest_dir: Path):
    _populate(manifest_dir, "requests")
    manifest = load_manifest(manifest_dir / "gallery.toml")
    to_generate, skipped = plan_repos(manifest, manifest_dir, force=False)
    assert [p.repo.slug for p in to_generate] == ["flask"]
    assert [p.repo.slug for p in skipped] == ["requests"]


def test_plan_force_regenerates_everything(manifest_dir: Path):
    _populate(manifest_dir, "requests")
    _populate(manifest_dir, "flask")
    manifest = load_manifest(manifest_dir / "gallery.toml")
    to_generate, skipped = plan_repos(manifest, manifest_dir, force=True)
    assert [p.repo.slug for p in to_generate] == ["requests", "flask"]
    assert skipped == []


def test_estimate_cost_is_an_upper_bound():
    estimate = estimate_cost(total_files=500, repo_count=3)
    assert estimate.repo_count == 3
    assert estimate.total_files == 500
    # 500 * $0.02 ceiling = $10.00; comfortably above the $0.83–2.50 the #86
    # research observed for 500 files, which is the point of a ceiling.
    assert estimate.ceiling_usd == pytest.approx(10.0)


# --------------------------------------------------------------------------
# Orchestration end to end (mocked steps)
# --------------------------------------------------------------------------


def test_generate_clones_surveys_and_renders_each_repo(manifest_dir: Path):
    steps = _FakeSteps()
    generated = _run(manifest_dir, steps)

    assert [p.repo.slug for p in generated] == ["requests", "flask"]
    assert steps.cloned == [
        "https://github.com/psf/requests",
        "https://github.com/pallets/flask",
    ]
    assert len(steps.surveyed) == 2
    # Each repo's broadsheet landed in its manifest-relative render_dir.
    for slug in ("requests", "flask"):
        assert (manifest_dir / "renders" / slug / "index.html").read_text() == (
            "<html>fresh</html>"
        )


def test_generate_skips_populated_repo(manifest_dir: Path):
    _populate(manifest_dir, "requests")
    steps = _FakeSteps()
    generated = _run(manifest_dir, steps)

    assert [p.repo.slug for p in generated] == ["flask"]
    assert steps.cloned == ["https://github.com/pallets/flask"]
    # The pre-existing broadsheet was left untouched.
    assert (manifest_dir / "renders" / "requests" / "index.html").read_text() == (
        "<html>existing</html>"
    )


def test_generate_force_overwrites_existing(manifest_dir: Path):
    _populate(manifest_dir, "requests")
    steps = _FakeSteps()
    generated = _run(manifest_dir, steps, force=True)

    assert [p.repo.slug for p in generated] == ["requests", "flask"]
    # --force regenerated the previously-populated repo.
    assert (manifest_dir / "renders" / "requests" / "index.html").read_text() == (
        "<html>fresh</html>"
    )


def test_nothing_to_do_when_all_populated(manifest_dir: Path):
    _populate(manifest_dir, "requests")
    _populate(manifest_dir, "flask")
    steps = _FakeSteps()
    generated = _run(manifest_dir, steps)

    assert generated == []
    assert steps.cloned == []
    assert steps.surveyed == []


# --------------------------------------------------------------------------
# The cost-confirm gate
# --------------------------------------------------------------------------


def test_confirm_gate_receives_the_estimate(manifest_dir: Path):
    steps = _FakeSteps(files_per_repo=4)
    seen: list[CostEstimate] = []

    def confirm(estimate: CostEstimate) -> bool:
        seen.append(estimate)
        return True

    _run(manifest_dir, steps, confirm=confirm)

    assert len(seen) == 1
    # Two repos × 4 files each → estimate reflects the work to be done.
    assert seen[0].repo_count == 2
    assert seen[0].total_files == 8
    assert seen[0].ceiling_usd == pytest.approx(0.16)


def test_declining_the_gate_spends_nothing(manifest_dir: Path):
    steps = _FakeSteps()
    generated = _run(manifest_dir, steps, confirm=lambda e: False)

    assert generated == []
    # Repos were cloned (needed to count files for the estimate) but NO
    # survey/render — i.e. no tokens spent — once the operator declined.
    assert steps.cloned  # cloning happened (cheap, pre-estimate)
    assert steps.surveyed == []
    assert steps.rendered == []
    assert not (manifest_dir / "renders" / "requests" / "index.html").exists()


def test_gate_is_asked_before_any_survey(manifest_dir: Path):
    """The confirm callback must fire before the first token-spending call."""
    steps = _FakeSteps()
    order: list[str] = []

    def confirm(estimate: CostEstimate) -> bool:
        order.append("confirm")
        return True

    original_survey = steps.survey

    def tracking_survey(repo_path: Path) -> None:
        order.append("survey")
        original_survey(repo_path)

    steps.survey = tracking_survey  # type: ignore[method-assign]
    _run(manifest_dir, steps, confirm=confirm)

    assert order[0] == "confirm"
    assert "survey" in order


# --------------------------------------------------------------------------
# Failure propagation
# --------------------------------------------------------------------------


def test_one_repo_failure_does_not_abort_the_batch(manifest_dir: Path):
    """A survey/render failure on one repo is recorded, not fatal."""
    steps = _FakeSteps()

    original_survey = steps.survey

    def flaky_survey(repo_path: Path) -> None:
        if repo_path.name == "requests":
            raise GenerationError("no files selected to survey")
        original_survey(repo_path)

    steps.survey = flaky_survey  # type: ignore[method-assign]
    report = _report(manifest_dir, steps)

    # flask still generated; requests recorded as failed.
    assert [p.repo.slug for p in report.generated] == ["flask"]
    assert [slug for slug, _ in report.failed] == ["requests"]
    assert "no files selected" in report.failed[0][1]
    # The succeeded repo's broadsheet is on disk; the failed one's is not.
    assert (manifest_dir / "renders" / "flask" / "index.html").exists()
    assert not (manifest_dir / "renders" / "requests" / "index.html").exists()


def test_clone_uses_full_history_not_shallow(monkeypatch, tmp_path: Path):
    """Antiquarian mines full git history, so the clone must NOT be shallow.

    A ``--depth`` flag here would hand the narrator 0–1 commits and defeat the
    whole tool — this test guards that decision (see generate.py docstring).
    """
    captured: list[list[str]] = []

    class _Result:
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _Result()

    monkeypatch.setattr(generate_mod.subprocess, "run", fake_run)
    clone_repo("https://github.com/psf/requests", tmp_path / "clone")

    assert captured, "git clone was never invoked"
    assert "--depth" not in captured[0]
    assert captured[0][:2] == ["git", "clone"]


def test_clone_failure_raises_generation_error(manifest_dir: Path):
    steps = _FakeSteps()

    def failing_clone(github_url: str, dest: Path) -> None:
        raise GenerationError(f"git clone failed for {github_url}")

    manifest = load_manifest(manifest_dir / "gallery.toml")
    with pytest.raises(GenerationError, match="git clone failed"):
        run_generation(
            manifest,
            manifest_dir,
            force=False,
            confirm=lambda e: True,
            clone_fn=failing_clone,
            survey_fn=steps.survey,
            render_fn=steps.render,
            count_fn=steps.count,
        )
