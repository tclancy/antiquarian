"""Pytest configuration — register Hypothesis profiles.

Profiles:
- ``dev`` — 30 examples per test. Default for fast local iteration.
- ``ci`` — 100 examples per test. What CI runs by default.
- ``fuzz`` — 1,000 examples per test. For local hunt-for-new-failures sessions.
- ``nightly`` — 10,000 examples per test, no deadline. For overnight runs against
  a fully-built test suite when looking for rare edge cases.

Pick one of three ways:

1. Set the env var:    ``HYPOTHESIS_PROFILE=fuzz uv run pytest tests/test_prop_*.py``
2. Pytest flag:        ``uv run pytest --hypothesis-profile=fuzz tests/test_prop_*.py``
3. Default (``ci``)   for CI runs, where no override is needed.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

hypothesis_settings.register_profile("dev", max_examples=30)
hypothesis_settings.register_profile("ci", max_examples=100)
hypothesis_settings.register_profile("fuzz", max_examples=1_000)
hypothesis_settings.register_profile(
    "nightly",
    max_examples=10_000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
