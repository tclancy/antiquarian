"""CLI behavior tests — focused on warnings and stderr output.

Deeper survey/story behavior is covered by tests/test_pipeline.py;
this file owns the parts that only exist in the CLI layer.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from antiquarian.cli import app

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


class TestScCommand:
    """SC command — detector output shape and error handling."""

    def test_unknown_detector_exits_with_error(self, tmp_path):
        result = runner.invoke(
            app, ["sc", "--repo", str(tmp_path), "--detector", "nonexistent"]
        )
        assert result.exit_code == 1
        assert "unknown detector" in result.stderr

    def test_sc_help_shows_options(self):
        result = runner.invoke(app, ["sc", "--help"])
        assert "statistical" in result.stdout
        assert "--top" in result.stdout

    def test_sc_runs_on_real_repo(self, tmp_path):
        """Smoke test: sc against a tiny git repo with a few commits."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        for i in range(5):
            (tmp_path / f"file{i}.py").write_text(f"# file {i}\n" * (i + 1))
            subprocess.run(
                ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", f"commit {i}"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )

        result = runner.invoke(app, ["sc", "--repo", str(tmp_path), "--top", "3"])
        assert result.exit_code == 0
        assert "Significant Changes" in result.stdout
        assert "Author Baselines" in result.stdout


class TestHelpTextDistinguishesFilters:
    """Help text must contrast --include (additive) vs --only (replacing)."""

    def test_survey_include_help_says_add(self):
        result = runner.invoke(app, ["survey", "--help"])
        # Combined output covers both stdout and any rich-formatted text
        out = result.stdout
        assert "ADD" in out
        assert "REPLACE" in out
