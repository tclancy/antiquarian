"""Unit tests for `antiquarian.prs` URL parsing helpers."""

from __future__ import annotations

from antiquarian.prs import parse_github_repo_url


class TestParseGithubRepoUrl:
    """`parse_github_repo_url` powers both `detect_github_repo` (origin) and
    the ghpublish `--remote` path (#114), so it has to handle the spellings
    git ships in `remote get-url`."""

    def test_ssh_style(self):
        assert parse_github_repo_url("git@github.com:tclancy/httpx.git") == (
            "tclancy",
            "httpx",
        )

    def test_https_style(self):
        assert parse_github_repo_url("https://github.com/tclancy/antiquarian.git") == (
            "tclancy",
            "antiquarian",
        )

    def test_https_no_dot_git(self):
        assert parse_github_repo_url("https://github.com/tclancy/antiquarian") == (
            "tclancy",
            "antiquarian",
        )

    def test_https_trailing_slash(self):
        assert parse_github_repo_url("https://github.com/tclancy/antiquarian/") == (
            "tclancy",
            "antiquarian",
        )

    def test_ssh_no_dot_git(self):
        assert parse_github_repo_url("git@github.com:tclancy/httpx") == (
            "tclancy",
            "httpx",
        )

    def test_non_github_returns_none(self):
        assert parse_github_repo_url("git@gitlab.com:tclancy/somewhere.git") is None

    def test_empty_returns_none(self):
        assert parse_github_repo_url("") is None
