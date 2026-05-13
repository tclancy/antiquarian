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


class TestHelpTextDistinguishesFilters:
    """Help text must contrast --include (additive) vs --only (replacing)."""

    def test_survey_include_help_says_add(self):
        result = runner.invoke(app, ["survey", "--help"])
        # Combined output covers both stdout and any rich-formatted text
        out = result.stdout
        assert "ADD" in out
        assert "REPLACE" in out
