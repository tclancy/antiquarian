"""Pytest configuration — register Hypothesis profiles."""

from hypothesis import settings as hypothesis_settings

hypothesis_settings.register_profile("ci", max_examples=100)
hypothesis_settings.register_profile("dev", max_examples=30)
hypothesis_settings.load_profile("ci")
