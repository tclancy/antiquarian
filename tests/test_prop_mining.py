"""Property tests for the mining layer (issue #20).

Specifically extends the rename-tracking regression test from PR #14
(``tests/test_mining.py``) to arbitrary chain depths. The bug being
defended against is the ``git log --follow --reverse`` toxic combination
from issue #13, which silently truncated history to ≤1 commit for any
renamed file.

Z3 can't model git's behavior so this lives in property-testing rather
than ``verification/``. See PR #22 review for the design discussion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from antiquarian.mining import historical_shas


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)


def _build_rename_chain(repo: Path, names: list[str]) -> str:
    """Create a file at ``names[0]``, then rename through each subsequent name.

    Returns the final filename. The number of commits produced equals ``len(names)``:
    one create + ``len(names) - 1`` renames.
    """
    assert names, "need at least one name"
    initial = names[0]
    (repo / initial).write_text("initial\n")
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", f"create {initial}"], cwd=repo)

    current = initial
    for next_name in names[1:]:
        _run(["git", "mv", current, next_name], cwd=repo)
        _run(["git", "commit", "-q", "-m", f"rename {current} -> {next_name}"], cwd=repo)
        current = next_name
    return current


# A name-segment strategy: short ASCII letters, no collisions with git internals.
_name_seg = st.text(alphabet="abcdefghijklmnop", min_size=2, max_size=10)


@st.composite
def _unique_name_chain(draw: st.DrawFn) -> list[str]:
    """A non-empty list of distinct ``.py`` filenames forming a rename chain."""
    n_renames = draw(st.integers(min_value=0, max_value=4))
    segs = draw(
        st.lists(
            _name_seg,
            min_size=n_renames + 1,
            max_size=n_renames + 1,
            unique=True,
        )
    )
    return [f"{s}.py" for s in segs]


class TestRenameChainPreserved:
    """The fix for issue #13 should hold for arbitrary chain depth."""

    @given(names=_unique_name_chain())
    @settings(
        max_examples=15,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_historical_shas_returns_full_chain(
        self, names: list[str], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        repo = tmp_path_factory.mktemp("rename-chain-repo")
        _init_repo(repo)
        current = _build_rename_chain(repo, names)

        shas = historical_shas(repo, current)
        assert len(shas) == len(names), (
            f"expected {len(names)} commits for chain {names!r}, "
            f"got {len(shas)}: {shas}"
        )

    @given(names=_unique_name_chain())
    @settings(
        max_examples=15,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_oldest_first_order_preserved(
        self, names: list[str], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        repo = tmp_path_factory.mktemp("rename-order-repo")
        _init_repo(repo)
        current = _build_rename_chain(repo, names)

        shas = historical_shas(repo, current)

        timestamps = []
        for sha in shas:
            result = subprocess.run(
                ["git", "-C", str(repo), "show", "-s", "--format=%ct", sha],
                capture_output=True,
                text=True,
                check=True,
            )
            timestamps.append(int(result.stdout.strip()))

        assert timestamps == sorted(timestamps), (
            f"chain {names!r} returned out of order; timestamps={timestamps}"
        )
