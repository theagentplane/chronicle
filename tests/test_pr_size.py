"""The PR size notifier counts changed lines and skips generated files."""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "pr_size.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_size", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_size = _load()


def test_counts_additions_and_deletions() -> None:
    files = [
        {"filename": "src/chronicle/models.py", "additions": 120, "deletions": 30},
        {"filename": "README.md", "additions": 10, "deletions": 0},
    ]
    assert pr_size.counted_lines(files) == (160, 0)


def test_generated_files_and_lockfiles_do_not_count() -> None:
    files = [
        {
            "filename": "tests/providers/openai/plain_text.raw.json",
            "additions": 500,
            "deletions": 0,
        },
        {"filename": "uv.lock", "additions": 900, "deletions": 100},
        {"filename": "src/chronicle/models.py", "additions": 40, "deletions": 0},
    ]
    assert pr_size.counted_lines(files) == (40, 1500)


def test_pure_rename_costs_nothing() -> None:
    files = [{"filename": "docs/new-name.md", "additions": 0, "deletions": 0}]
    assert pr_size.counted_lines(files) == (0, 0)


def test_threshold_is_four_hundred() -> None:
    assert pr_size.THRESHOLD_DEFAULT == 400
