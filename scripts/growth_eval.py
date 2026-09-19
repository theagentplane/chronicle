#!/usr/bin/env python
"""Fixed, non-subjective adoption-readiness eval. Do not modify (see prepare.md).

Builds a fresh venv, installs the repo exactly as a new user would, runs the
same no-API-key demo command the README advertises, and combines that with a
handful of deterministic repo checks into one score. Every component is a
file-system check or a process exit code -- nothing here is graded by
judgment, so the score cannot be gamed by writing more convincing prose.

Usage: python scripts/growth_eval.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_CMD = ["python", "examples/financial_incidents/run.py", "refund", "test"]
DOC_CHECKLIST_HEADINGS = [
    "## Install",
    "## Quick start",
    "## Why Chronicle",
    "## How Chronicle compares",
    "## FAQ",
    "## Roadmap",
    "## Demos",
]
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def check_ttfsr() -> dict:
    """Fresh venv -> editable install -> run the README's no-key demo command."""
    with tempfile.TemporaryDirectory(prefix="chronicle-growth-eval-") as tmp:
        venv_dir = Path(tmp) / "venv"
        t0 = time.monotonic()
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        py = _venv_python(venv_dir)
        install = subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet", "-e", "."],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        if install.returncode != 0:
            return {"pass": False, "seconds": time.monotonic() - t0,
                     "stage": "install", "log": install.stderr[-4000:]}
        demo = subprocess.run(
            [str(py)] + DEMO_CMD[1:], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=120,
        )
        elapsed = time.monotonic() - t0
        if demo.returncode != 0:
            return {"pass": False, "seconds": elapsed, "stage": "demo",
                     "log": demo.stdout[-2000:] + demo.stderr[-2000:]}
        return {"pass": True, "seconds": round(elapsed, 1), "stage": None, "log": ""}


def check_tests_green() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "layer1", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    return {"pass": result.returncode == 0, "log": result.stdout[-2000:]}


def check_broken_internal_links() -> dict:
    broken = []
    for md in list(REPO_ROOT.glob("*.md")) + list((REPO_ROOT / "docs").glob("*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if not path:
                continue
            resolved = (md.parent / path).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(REPO_ROOT)}: {target}")
    return {"count": len(broken), "broken": broken}


def check_version_consistency() -> dict:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    pyproject_version = m.group(1) if m else None

    init_path = REPO_ROOT / "chronicle" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8") if init_path.exists() else ""
    m2 = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    init_version = m2.group(1) if m2 else None

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m3 = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    changelog_version = m3.group(1) if m3 else None

    consistent = pyproject_version is not None and pyproject_version in (init_version, None) \
        and changelog_version == pyproject_version
    return {"consistent": consistent, "pyproject": pyproject_version,
            "init": init_version, "changelog_latest": changelog_version}


def check_doc_checklist() -> dict:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    present = [h for h in DOC_CHECKLIST_HEADINGS if h in readme]
    return {"present": len(present), "total": len(DOC_CHECKLIST_HEADINGS), "missing": [h for h in DOC_CHECKLIST_HEADINGS if h not in present]}


def check_example_coverage() -> dict:
    examples_dir = REPO_ROOT / "examples"
    tests_dir = REPO_ROOT / "tests"
    test_text = " ".join(p.read_text(encoding="utf-8", errors="replace")
                          for p in tests_dir.glob("test_*.py"))
    covered = 0
    total = 0
    for child in sorted(examples_dir.iterdir()):
        if not child.is_dir() or child.name == "control_plane":
            continue
        total += 1
        if child.name in test_text:
            covered += 1
    return {"covered": covered, "total": total}


def lines_before_first_code_block() -> int:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(readme):
        if line.strip().startswith("```"):
            return i
    return len(readme)


def score(results: dict) -> float:
    if not results["ttfsr"]["pass"] or not results["tests_green"]["pass"]:
        return 0.0
    s = 100.0
    s -= results["broken_links"]["count"] * 10
    s -= max(0, lines_before_first_code_block() - 40) * 0.5
    s += results["example_coverage"]["covered"] * 5
    s += 10 if results["version_consistency"]["consistent"] else 0
    s += results["doc_checklist"]["present"] * 2
    return round(s, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-ttfsr", action="store_true",
                         help="skip the fresh-venv install (fast iteration while drafting)")
    args = parser.parse_args()

    results = {
        "ttfsr": {"pass": True, "seconds": 0.0, "stage": None, "log": ""} if args.skip_ttfsr else check_ttfsr(),
        "tests_green": check_tests_green(),
        "broken_links": check_broken_internal_links(),
        "version_consistency": check_version_consistency(),
        "doc_checklist": check_doc_checklist(),
        "example_coverage": check_example_coverage(),
    }
    results["lines_before_first_code_block"] = lines_before_first_code_block()
    results["score"] = score(results)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"ttfsr_pass:        {results['ttfsr']['pass']} ({results['ttfsr']['seconds']}s)")
        print(f"tests_green:       {results['tests_green']['pass']}")
        print(f"broken_links:      {results['broken_links']['count']}")
        print(f"version_consistent: {results['version_consistency']['consistent']}")
        print(f"doc_checklist:     {results['doc_checklist']['present']}/{results['doc_checklist']['total']}")
        print(f"example_coverage:  {results['example_coverage']['covered']}/{results['example_coverage']['total']}")
        print(f"lines_before_code: {results['lines_before_first_code_block']}")
        print(f"score:             {results['score']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
