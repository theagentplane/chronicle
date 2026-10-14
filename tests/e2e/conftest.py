"""Fixtures for the end-to-end suite: a ``System`` factory that cleans up after itself."""

import os
from collections.abc import Iterator

import pytest

import chronicle
from chronicle.framework.hooks.hook_registry import default_hooks
from tests.e2e.system import System


@pytest.fixture(autouse=True)
def _mark_and_isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("CHRONICLE_"):
            monkeypatch.delenv(key)
    chronicle.reset()
    default_hooks.clear()
    yield
    default_hooks.clear()


@pytest.fixture
def system() -> Iterator[System]:
    built = System()
    try:
        yield built
    finally:
        built.close()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything under tests/e2e carries the ``e2e`` marker."""
    for item in items:
        if "/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)
