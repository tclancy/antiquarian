"""Tests for the link-resolution backend (#113)."""

from __future__ import annotations

import subprocess

import pytest

from antiquarian.link_backend import (
    GitHubBackend,
    LinkBackend,
    NoopLinkBackend,
    detect_link_backend,
    linkify_markdown,
)


# ---- GitHubBackend ---------------------------------------------------------


def test_github_backend_satisfies_protocol():
    assert isinstance(GitHubBackend("o", "r"), LinkBackend)


def test_noop_backend_satisfies_protocol():
    assert isinstance(NoopLinkBackend(), LinkBackend)


def test_github_backend_urls():
    b = GitHubBackend(owner="tclancy", repo="antiquarian")
    assert b.commit_url("7af3c1b") == (
        "https://github.com/tclancy/antiquarian/commit/7af3c1b"
    )
    assert b.pr_url(130) == "https://github.com/tclancy/antiquarian/pull/130"
    assert b.issue_url(113) == "https://github.com/tclancy/antiquarian/issues/113"


def test_github_backend_host_can_be_overridden():
    b = GitHubBackend(owner="o", repo="r", host="github.example.com")
    assert b.commit_url("abc1234").startswith("https://github.example.com/")


def test_noop_backend_returns_none_for_everything():
    b = NoopLinkBackend()
    assert b.commit_url("7af3c1b") is None
    assert b.pr_url(130) is None
    assert b.issue_url(113) is None


# ---- detect_link_backend ---------------------------------------------------


def test_detect_link_backend_github_origin(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://github.com/tclancy/antiquarian.git",
        ],
        check=True,
    )
    b = detect_link_backend(tmp_path)
    assert isinstance(b, GitHubBackend)
    assert (b.owner, b.repo) == ("tclancy", "antiquarian")


def test_detect_link_backend_no_remote_falls_back_to_noop(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    # No remote added.
    b = detect_link_backend(tmp_path)
    assert isinstance(b, NoopLinkBackend)


def test_detect_link_backend_non_github_remote_falls_back(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://gitlab.com/owner/repo.git",
        ],
        check=True,
    )
    b = detect_link_backend(tmp_path)
    assert isinstance(b, NoopLinkBackend)


def test_detect_link_backend_ssh_url(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "git@github.com:tclancy/recordclub.git",
        ],
        check=True,
    )
    b = detect_link_backend(tmp_path)
    assert isinstance(b, GitHubBackend)
    assert (b.owner, b.repo) == ("tclancy", "recordclub")


def test_detect_link_backend_unreadable_path_returns_noop(tmp_path):
    # No git init at all → detect_github_repo's subprocess raises, returns None.
    assert isinstance(detect_link_backend(tmp_path / "nope"), NoopLinkBackend)


# ---- linkify_markdown ------------------------------------------------------

GH = GitHubBackend(owner="o", repo="r")


def test_linkify_pr_or_issue_reference():
    out = linkify_markdown("see #113 for details", GH)
    assert out == "see [#113](https://github.com/o/r/issues/113) for details"


def test_linkify_commit_sha():
    out = linkify_markdown("introduced in 7af3c1b", GH)
    assert out == ("introduced in [`7af3c1b`](https://github.com/o/r/commit/7af3c1b)")


def test_linkify_handles_full_40_char_sha():
    sha = "7af3c1b1234567890123456789012345678901ab"
    out = linkify_markdown(f"see {sha}", GH)
    # First 7 chars shown in the link text, full SHA in the URL.
    assert f"[`{sha[:7]}`](https://github.com/o/r/commit/{sha})" in out


def test_linkify_skips_inside_inline_code():
    md = "the literal `#113` and `7af3c1b` stay"
    assert linkify_markdown(md, GH) == md


def test_linkify_skips_inside_fenced_block():
    md = "```\nmention #113 and 7af3c1b inside\n```"
    assert linkify_markdown(md, GH) == md


def test_linkify_skips_existing_markdown_link():
    md = "[some-#113-text](https://example.com)"
    assert linkify_markdown(md, GH) == md


def test_linkify_skips_bare_url_with_sha_inside():
    # The SHA-looking segment in the URL must not become a nested link.
    md = "https://github.com/o/r/commit/7af3c1babcdef"
    assert linkify_markdown(md, GH) == md


def test_linkify_skips_when_hash_glued_to_word():
    # ``foo#123`` is some-other-syntax, not a PR/issue ref.
    md = "channel foo#123 reads"
    assert linkify_markdown(md, GH) == md


def test_linkify_noop_backend_passes_through():
    md = "see #113 and 7af3c1b"
    assert linkify_markdown(md, NoopLinkBackend()) == md


def test_linkify_multiple_refs_in_one_paragraph():
    md = "After #100, the 7af3c1b fix landed (see also #200)."
    out = linkify_markdown(md, GH)
    assert "[#100](https://github.com/o/r/issues/100)" in out
    assert "[`7af3c1b`](https://github.com/o/r/commit/7af3c1b)" in out
    assert "[#200](https://github.com/o/r/issues/200)" in out


def test_linkify_word_boundary_protects_short_hex_words():
    # 6-char hex string is below threshold; 7+ would match. Keep "decade"
    # unlinked since the threshold guards against most English hex-words.
    md = "a decade of change"
    assert linkify_markdown(md, GH) == md


@pytest.mark.parametrize(
    "url_form",
    [
        "<https://example.com/x>",
        "https://example.com/path?q=1",
    ],
)
def test_linkify_skips_url_forms(url_form):
    md = f"see {url_form} for more"
    assert linkify_markdown(md, GH) == md
