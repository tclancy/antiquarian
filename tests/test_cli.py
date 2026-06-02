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

    def _seed_gallery(self, tmp_path: Path) -> Path:
        """Assemble a minimal multi-page gallery tree; return its root."""
        gallery_dir = tmp_path / "gallery"
        (gallery_dir / "requests").mkdir(parents=True, exist_ok=True)
        (gallery_dir / "index.html").write_text("<!doctype html><title>gallery</title>")
        (gallery_dir / "requests" / "index.html").write_text(
            "<!doctype html><title>requests broadsheet</title>"
        )
        return gallery_dir

    def test_source_missing_index_errors(self, tmp_path: Path):
        """`--source` pointing at a dir with no index.html → exit 1."""
        empty = tmp_path / "nope"
        empty.mkdir()
        result = runner.invoke(
            app, ["ghpublish", "--repo", str(tmp_path), "--source", str(empty)]
        )
        assert result.exit_code == 1
        assert "index.html" in result.stderr

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli.shutil.copytree")
    @patch("antiquarian.cli._run_git")
    def test_source_publishes_gallery_tree(
        self,
        mock_git: MagicMock,
        mock_copytree: MagicMock,
        mock_gh: MagicMock,
        tmp_path: Path,
    ):
        """`--source gallery/` publishes the multi-page tree, not the render dir."""
        gallery_dir = self._seed_gallery(tmp_path)
        mock_git.side_effect = self._fake_git_runner()

        result = runner.invoke(
            app,
            ["ghpublish", "--repo", str(tmp_path), "--source", str(gallery_dir)],
        )

        assert result.exit_code == 0, result.output + result.stderr
        # The gallery tree (not .antiquarian/render) is what gets staged.
        copied_src = Path(mock_copytree.call_args.args[0])
        assert copied_src == gallery_dir.resolve()
        # Still a force-push to gh-pages, and the URL hint is printed.
        git_calls = [c.args[0] for c in mock_git.call_args_list]
        push = next(args for args in git_calls if args[0] == "push")
        assert "--force" in push and "HEAD:gh-pages" in push
        assert "https://owner.github.io/repo/" in result.output

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli.shutil.copytree")
    @patch("antiquarian.cli._run_git")
    def test_source_works_without_render_dir(
        self,
        mock_git: MagicMock,
        mock_copytree: MagicMock,
        mock_gh: MagicMock,
        tmp_path: Path,
    ):
        """`--source` does not require a `.antiquarian/render/` to exist."""
        gallery_dir = self._seed_gallery(tmp_path)
        assert not (tmp_path / ".antiquarian" / "render").exists()
        mock_git.side_effect = self._fake_git_runner()

        result = runner.invoke(
            app,
            ["ghpublish", "--repo", str(tmp_path), "--source", str(gallery_dir)],
        )
        assert result.exit_code == 0, result.output + result.stderr

    @patch("antiquarian.cli.detect_github_repo", return_value=("owner", "repo"))
    @patch("antiquarian.cli._run_git")
    def test_source_payload_contains_multipage_tree(
        self, mock_git: MagicMock, mock_gh: MagicMock, tmp_path: Path
    ):
        """Real copytree: the staged payload has the full subtree + `.nojekyll`.

        This is the deliverable of #94 — a *multi-page* site, not just a
        landing page. Only `_run_git` is mocked; `shutil.copytree` runs for
        real, and we snapshot the tempdir at `git add` time to prove the
        per-repo page survived and `.nojekyll` was added.
        """
        gallery_dir = self._seed_gallery(tmp_path)
        staged: list[str] = []

        def recording_git(args: list[str], **kwargs):
            if args[:2] == ["add", "."]:
                staging = Path(kwargs["cwd"])
                staged.extend(
                    sorted(
                        str(p.relative_to(staging))
                        for p in staging.rglob("*")
                        if p.is_file()
                    )
                )
            return self._fake_git_runner()(args, **kwargs)

        mock_git.side_effect = recording_git

        result = runner.invoke(
            app,
            ["ghpublish", "--repo", str(tmp_path), "--source", str(gallery_dir)],
        )

        assert result.exit_code == 0, result.output + result.stderr
        assert "index.html" in staged
        assert "requests/index.html" in staged  # the multi-page subtree
        assert ".nojekyll" in staged

class TestBackendSelection:
    """Issue #91 — --backend flag wiring at the CLI layer."""

    def test_unknown_backend_exits_cleanly(self, tmp_path):
        result = runner.invoke(
            app, ["survey", "--repo", str(tmp_path), "--backend", "gpt-9000"]
        )
        assert result.exit_code == 1
        assert "gpt-9000" in result.stderr
        # Names the available options instead of dumping a traceback.
        assert "claude-p" in result.stderr

    def test_story_threads_resolved_backend_into_pipeline(self, tmp_path):
        target = tmp_path / "x.py"
        target.write_text("print('hi')\n")
        captured = {}

        def _fake_story(*_args, **kwargs):
            captured["backend"] = kwargs.get("backend")
            return ("the story", None)

        # Stub preflight so the test doesn't require a running Ollama server;
        # we're verifying resolution + threading, not connectivity.
        with (
            patch("antiquarian.cli.generate_file_story", side_effect=_fake_story),
            patch("antiquarian.backends.OllamaBackend.preflight", lambda self: None),
        ):
            result = runner.invoke(
                app,
                ["story", str(target), "--repo", str(tmp_path), "--backend", "ollama"],
            )
        assert result.exit_code == 0
        # The CLI resolved "ollama" to a concrete backend and passed it down.
        from antiquarian.backends import OllamaBackend

        assert isinstance(captured["backend"], OllamaBackend)
