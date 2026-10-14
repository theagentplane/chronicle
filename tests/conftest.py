"""Shared fixtures: an in-memory control plane wired into Chronicle, reset between tests."""

import os
from collections.abc import Iterator

import pytest

import chronicle
from chronicle.framework.hooks.hook_registry import default_hooks
from tests.support.in_memory_control_plane import InMemoryControlPlane


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with no code config, no CHRONICLE_* env and no default hooks."""
    for key in list(os.environ):
        if key.startswith("CHRONICLE_"):
            monkeypatch.delenv(key)
    chronicle.reset()
    default_hooks.clear()
    yield
    chronicle.reset()
    default_hooks.clear()


@pytest.fixture
def control_plane() -> InMemoryControlPlane:
    """An in-memory control plane that Chronicle writes to, delivered promptly."""
    plane = InMemoryControlPlane()
    chronicle.configure(client=plane, batch_size=1, flush_interval=0.01)
    return plane
