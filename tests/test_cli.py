"""CLI behavior tests — focused on warnings and stderr output.

Deeper survey/story behavior is covered by tests/test_pipeline.py;
this file owns the parts that only exist in the CLI layer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from antiquarian.cli import app
from antiquarian.generate import CostEstimate, GenerationError, GenerationReport

runner = CliRunner()


def _fake_survey(*_args, **_kwargs):
    return ("# survey\n", None)


def _fake_select(*_args, **kwargs):
    if kwargs.get("only"):
        return list(kwargs["only"])
    return [f"file_{i}.py" for i in range(25)]


class TestSurveyLargeSelectionWarning:
    """Issue #29 — warn when an --include / default candidate set is large."""

    def test_warns_above_threshold(self, tmp_path):
        with (
            patch("antiquarian.cli.select_files", side_effect=_fake_select),
            patch("antiquarian.cli.generate_codebase_survey", side_effect=_fake_survey),
        ):
            result = runner.invoke(app, ["survey", "--repo", str(tmp_path)])
        assert result.exit_code == 0
        assert "WARNING" in result.stderr
        assert "--only" in result.stderr
        assert "25 file" in result.stderr or "25 files" in result.stderr

    def test_no_warning_with_only(self, tmp_path):
        with (
            patch("antiquarian.cli.select_files", side_effect=_fake_select),
            patch("antiquarian.cli.generate_codebase_survey", side_effect=_fake_survey),
        ):
            result = runner.invoke(
                app,
                [
                    "survey",
                    "--repo",
                    str(tmp_path),
                    "--only",
                    "a.py",
                    "--only",
                    "b.py",
                ],
            )
        assert result.exit_code == 0
        assert "WARNING" not in result.stderr

    def test_no_warning_below_threshold(self, tmp_path):
        def small_select(*_args, **_kwargs):
            return ["a.py", "b.py", "c.py"]

        with (
            patch("antiquarian.cli.select_files", side_effect=small_select),
            patch("antiquarian.cli.generate_codebase_survey", side_effect=_fake_survey),
        ):
            result = runner.invoke(app, ["survey", "--repo", str(tmp_path)])
        assert result.exit_code == 0
        assert "WARNING" not in result.stderr


class TestHelpTextDistinguishesFilters:
    """Help text must contrast --include (additive) vs --only (replacing)."""

    def test_survey_include_help_says_add(self):
        result = runner.invoke(app, ["survey", "--help"])
        # Combined output covers both stdout and any rich-formatted text
        out = result.stdout
        assert "ADD" in out
        assert "REPLACE" in out


class TestGhpublish:
    """Issue #73 — `antiquarian ghpublish` builds + force-pushes gh-pages."""

    def test_errors_when_no_render_output(self, tmp_path: Path):
        """No `.antiquarian/render/index.html` → exit 1 with helpful message."""
        result = runner.invoke(app, ["ghpublish", "--repo", str(tmp_path)])
        assert result.exit_code == 1
        assert "render" in result.stderr.lower()

    def _seed_render(self, tmp_path: Path) -> None:
        render_dir = tmp_path / ".antiquarian" / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / "index.html").write_text(
            "<!doctype html><title>broadsheet</title>"
        )
        stories_dir = render_dir / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "src__a.py.html").write_text(
            "<!doctype html><title>story</title>"
        )

    def _fake_git_runner(self, remote_url: str = "git@github.com:owner/repo.git"):
        """Return a callable that mocks `_run_git` for the ghpublish path.

        - `git remote get-url <name>` returns the stub remote URL.
        - everything else returns a no-op success.
        """

        def side_effect(args: list[str], **kwargs):
            if args[:3] == ["remote", "get-url", "origin"]:
                return subprocess.CompletedProcess(
                    args=["git", *args],
                    returncode=0,
                    stdout=remote_url + "\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=0, stdout="", stderr=""
            )

        return side_effect

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli._run_git")
    def test_happy_path_pushes_to_gh_pages(
        self, mock_git: MagicMock, mock_gh: MagicMock, tmp_path: Path
    ):
        self._seed_render(tmp_path)
        mock_git.side_effect = self._fake_git_runner()

        result = runner.invoke(app, ["ghpublish", "--repo", str(tmp_path)])

        assert result.exit_code == 0, result.output + result.stderr
        # init + add + commit + push were all invoked
        git_calls = [c.args[0] for c in mock_git.call_args_list]
        assert any(args[0] == "init" for args in git_calls)
        assert any(args[0] == "add" for args in git_calls)
        assert any(args[0] == "commit" for args in git_calls)
        # The push call uses --force and targets HEAD:gh-pages
        push_calls = [args for args in git_calls if args[0] == "push"]
        assert push_calls
        push = push_calls[0]
        assert "--force" in push
        assert "HEAD:gh-pages" in push

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli._run_git")
    def test_prints_settings_url_and_pages_url(
        self, mock_git: MagicMock, mock_gh: MagicMock, tmp_path: Path
    ):
        """Tom's ask: 'just provide the info every time with the command.'"""
        self._seed_render(tmp_path)
        mock_git.side_effect = self._fake_git_runner()

        result = runner.invoke(app, ["ghpublish", "--repo", str(tmp_path)])
        assert result.exit_code == 0
        assert "https://github.com/owner/repo/settings/pages" in result.output
        assert "https://owner.github.io/repo/" in result.output

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli._run_git")
    def test_remote_flag_overrides_origin(
        self, mock_git: MagicMock, mock_gh: MagicMock, tmp_path: Path
    ):
        self._seed_render(tmp_path)
        mock_git.side_effect = self._fake_git_runner()

        result = runner.invoke(
            app, ["ghpublish", "--repo", str(tmp_path), "--remote", "upstream"]
        )
        assert result.exit_code == 0
        # The first `git remote get-url` call uses the user's --remote
        first_remote_call = next(
            (
                c.args[0]
                for c in mock_git.call_args_list
                if c.args[0][:2] == ["remote", "get-url"]
            ),
            None,
        )
        assert first_remote_call == ["remote", "get-url", "upstream"]


_GALLERY_MANIFEST = """\
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
"""


class TestGalleryGenerate:
    """CLI wiring for `gallery generate` — the cost gate and flag plumbing."""

    def _manifest(self, tmp_path: Path) -> Path:
        path = tmp_path / "gallery.toml"
        path.write_text(_GALLERY_MANIFEST, encoding="utf-8")
        return path

    def test_yes_prints_estimate_and_proceeds_without_prompt(self, tmp_path: Path):
        """--yes shows the cost estimate but does not block on a prompt."""

        def fake_run(manifest, manifest_dir, *, confirm, **kwargs):
            # The CLI's confirm callback should auto-approve under --yes.
            assert confirm(CostEstimate(repo_count=1, total_files=3, ceiling_usd=0.06))
            return GenerationReport(generated=[], failed=[])

        with patch("antiquarian.cli.run_generation", side_effect=fake_run):
            result = runner.invoke(
                app,
                ["gallery", "generate", "-m", str(self._manifest(tmp_path)), "--yes"],
            )
        assert result.exit_code == 0
        assert "$0.06" in result.stderr
        assert "--yes given" in result.stderr

    def test_interactive_decline_aborts(self, tmp_path: Path):
        """Answering 'no' at the prompt makes the gate return False."""
        decisions: list[bool] = []

        def fake_run(manifest, manifest_dir, *, confirm, **kwargs):
            decisions.append(
                confirm(CostEstimate(repo_count=1, total_files=3, ceiling_usd=0.06))
            )
            return GenerationReport(generated=[], failed=[])

        with patch("antiquarian.cli.run_generation", side_effect=fake_run):
            result = runner.invoke(
                app,
                ["gallery", "generate", "-m", str(self._manifest(tmp_path))],
                input="n\n",
            )
        assert result.exit_code == 0
        assert decisions == [False]

    def test_force_flag_is_passed_through(self, tmp_path: Path):
        captured: dict = {}

        def fake_run(manifest, manifest_dir, *, force, confirm, **kwargs):
            captured["force"] = force
            return GenerationReport(generated=[], failed=[])

        with patch("antiquarian.cli.run_generation", side_effect=fake_run):
            result = runner.invoke(
                app,
                [
                    "gallery",
                    "generate",
                    "-m",
                    str(self._manifest(tmp_path)),
                    "--yes",
                    "--force",
                ],
            )
        assert result.exit_code == 0
        assert captured["force"] is True

    def test_generation_error_exits_nonzero(self, tmp_path: Path):
        def fake_run(*args, **kwargs):
            raise GenerationError("git clone failed for some-repo")

        with patch("antiquarian.cli.run_generation", side_effect=fake_run):
            result = runner.invoke(
                app,
                ["gallery", "generate", "-m", str(self._manifest(tmp_path)), "--yes"],
            )
        assert result.exit_code == 1
        assert "git clone failed" in result.stderr

    def test_failed_repos_exit_nonzero_but_report_them(self, tmp_path: Path):
        """A partial failure exits non-zero and names the repo that failed."""

        def fake_run(*args, **kwargs):
            return GenerationReport(generated=[], failed=[("flask", "boom")])

        with patch("antiquarian.cli.run_generation", side_effect=fake_run):
            result = runner.invoke(
                app,
                ["gallery", "generate", "-m", str(self._manifest(tmp_path)), "--yes"],
            )
        assert result.exit_code == 1
        assert "FAILED flask: boom" in result.stderr
