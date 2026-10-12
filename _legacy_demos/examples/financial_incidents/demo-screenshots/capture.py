#!/usr/bin/env python3
"""Capture annotated trade demo slides as PNG screenshots."""

from pathlib import Path

from playwright.sync_api import sync_playwright

DIR = Path(__file__).parent
BASE = "http://127.0.0.1:8877"
SLIDES = [
    "01-scenario-setup",
    "02-agent-bug",
    "03-max-amount-gate",
    "04-chronicle-test",
    "05-record-terminal",
    "06-test-terminal",
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        for name in SLIDES:
            page.goto(f"{BASE}/{name}.html", wait_until="networkidle")
            out = DIR / f"{name}.png"
            page.locator(".slide").screenshot(path=str(out))
            print(f"Wrote {out}")
        browser.close()


if __name__ == "__main__":
    main()
