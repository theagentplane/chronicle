#!/usr/bin/env python3
"""Cross-platform Chronicle demo and test runner (Windows, macOS, Linux)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE_DIR = ROOT / "fixtures" / "traces" / "deletion-incident-001"
DEMO_STEPS = 3


def _python() -> str:
    return sys.executable


def _run(cmd: list[str], *, check: bool = True, quiet: bool = False) -> int:
    if not quiet:
        print(f"==> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def _step_confirm(args: argparse.Namespace, step: int, description: str) -> bool:
    """Ask before advancing to the next demo step."""
    if getattr(args, "yes", False):
        return True
    try:
        answer = input(
            f"\nContinue to step {step}/{DEMO_STEPS}: {description}? [Y/n] "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nDemo stopped.")
        return False
    if answer in ("n", "no"):
        print("Demo stopped.")
        return False
    return True


def _ui_prompt(args: argparse.Namespace) -> None:
    if args.no_ui_prompt:
        return
    try:
        answer = input("\nOpen trace in interactive UI? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if answer not in ("y", "yes"):
        return
    print(f"Starting UI at http://127.0.0.1:{args.port}/ (Ctrl+C to continue demo)")
    sys.path.insert(0, str(ROOT))
    try:
        from chronicle.visualizer import serve_trace_ui

        serve_trace_ui(TRACE_DIR, port=args.port, open_browser=not args.no_browser)
    except KeyboardInterrupt:
        print("\n(UI closed)")


def cmd_test(args: argparse.Namespace) -> None:
    extra = list(args.pytest_args)
    if extra and extra[0] == "--":
        extra = extra[1:]
    cmd = [_python(), "-m", "pytest"]
    if extra:
        cmd.extend(extra)
    else:
        cmd.append("-v")
    print("==> pytest (full suite)")
    _run(cmd)


def cmd_demo(args: argparse.Namespace) -> None:
    py = _python()

    if not _step_confirm(args, 1, "Record incident (ungated delete_file)"):
        return
    print("\n==> [1/3] Record incident (ungated delete_file)", flush=True)
    _run([py, "examples/deletion_agent/record_incident.py"], quiet=True)

    if not _step_confirm(args, 2, "Show trace (terminal)"):
        return
    print("\n==> [2/3] Show trace (terminal)", flush=True)
    _run([py, "examples/deletion_agent/show_trace.py"], quiet=True)

    _ui_prompt(args)

    if not _step_confirm(args, 3, "Cut-point replay demo (gated delete_file)"):
        return
    print("\n==> [3/3] Cut-point replay demo (gated delete_file)", flush=True)
    _run([py, "examples/deletion_agent/run_cutpoint_demo.py"], quiet=True)

    print("\nDemo complete.")
    print("Run tests separately: python scripts/run.py test")


def cmd_quickrun(args: argparse.Namespace) -> None:
    """Interactive demo walkthrough (same as demo — tests are separate)."""
    cmd_demo(args)


def _add_demo_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-y", "--yes", action="store_true", help="Skip step confirmation prompts")
    parser.add_argument("--port", type=int, default=8765, help="UI server port")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser for UI")
    parser.add_argument("--no-ui-prompt", action="store_true", help="Skip interactive UI prompt")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chronicle cross-platform demo and test runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser(
        "demo",
        help="Interactive demo: record → trace → optional UI → cut-point replay",
    )
    _add_demo_flags(demo)
    demo.set_defaults(func=cmd_demo)

    test = sub.add_parser("test", help="Run full pytest suite (separate from demo)")
    test.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        default=[],
        help="Extra pytest arguments (e.g. test -- -k cutpoint)",
    )
    test.set_defaults(func=cmd_test)

    quick = sub.add_parser(
        "quickrun",
        help="Alias for demo (use 'test' for the pytest suite)",
    )
    _add_demo_flags(quick)
    quick.set_defaults(func=cmd_quickrun)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
