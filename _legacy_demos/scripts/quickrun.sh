#!/usr/bin/env bash
# Demo + full test suite (delegates to cross-platform runner).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python scripts/run.py quickrun "$@"
