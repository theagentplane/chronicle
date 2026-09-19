#!/usr/bin/env python
"""Ground-truth growth snapshot: real stars/forks/traffic/downloads.

Not part of the per-iteration loop score (see prepare.md for why) -- run this
weekly by hand to log whether the proxy score is actually tracking real growth.
Requires `gh auth login` (repo scope, for traffic) and network access.

Usage: python scripts/growth_snapshot.py [--write]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date, timezone, datetime
from pathlib import Path

REPO = "theagentplane/chronicle"
PACKAGE = "agent-chronicle"
STARS_TSV = Path(__file__).resolve().parent.parent / "docs" / "growth" / "stars.tsv"
HEADER = "date\tstars\tforks\twatchers\topen_issues\tviews_14d\tuniques_14d\tclones_14d\tclone_uniques_14d\tpypi_downloads_month\tpypi_downloads_week\n"


def gh_json(args: list[str]) -> dict:
    result = subprocess.run(["gh", "api"] + args, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def pypi_downloads() -> dict:
    with urllib.request.urlopen(
        f"https://pypistats.org/api/packages/{PACKAGE}/recent", timeout=15
    ) as resp:
        data = json.loads(resp.read())["data"]
    return {"month": data.get("last_month", 0), "week": data.get("last_week", 0)}


def snapshot() -> dict:
    repo = gh_json([f"repos/{REPO}"])
    views = gh_json([f"repos/{REPO}/traffic/views"])
    clones = gh_json([f"repos/{REPO}/traffic/clones"])
    downloads = pypi_downloads()
    return {
        "date": date.today().isoformat(),
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "watchers": repo["subscribers_count"],
        "open_issues": repo["open_issues_count"],
        "views_14d": views["count"],
        "uniques_14d": views["uniques"],
        "clones_14d": clones["count"],
        "clone_uniques_14d": clones["uniques"],
        "pypi_downloads_month": downloads["month"],
        "pypi_downloads_week": downloads["week"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="append the row to stars.tsv")
    args = parser.parse_args()

    row = snapshot()
    line = "\t".join(str(row[k]) for k in [
        "date", "stars", "forks", "watchers", "open_issues", "views_14d",
        "uniques_14d", "clones_14d", "clone_uniques_14d",
        "pypi_downloads_month", "pypi_downloads_week",
    ])

    print(json.dumps(row, indent=2))

    if args.write:
        STARS_TSV.parent.mkdir(parents=True, exist_ok=True)
        is_new = not STARS_TSV.exists()
        with STARS_TSV.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(HEADER)
            f.write(line + "\n")
        print(f"\nAppended to {STARS_TSV}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
