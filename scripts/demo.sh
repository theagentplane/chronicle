#!/usr/bin/env bash
# Deletion agent demo (delegates to cross-platform runner).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python scripts/run.py demo "$@"
