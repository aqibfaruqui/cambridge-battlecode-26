#!/usr/bin/env python3
"""Scrape Cambridge Battlecode docs and save to docs/."""

import os
import urllib.request

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT_DIR, "docs")

PAGES = [
    ("https://docs.battlecode.cam/api/constants.md", "game_constants.md"),
    ("https://docs.battlecode.cam/api/controller.md", "api.md"),
    ("https://docs.battlecode.cam/api/types.md", "types_and_enums.md"),
    ("https://docs.battlecode.cam/getting-started/cli.md", "cli.md"),
    ("https://docs.battlecode.cam/getting-started/first-bot.md", "first_bot.md"),
    ("https://docs.battlecode.cam/getting-started/matches.md", "matches.md"),
    ("https://docs.battlecode.cam/getting-started/running-matches.md", "running_matches.md"),
    ("https://docs.battlecode.cam/getting-started/submitting.md", "submitting.md"),
    ("https://docs.battlecode.cam/index.md", "index.md"),
    ("https://docs.battlecode.cam/spec/builder-bot.md", "builder_bot.md"),
    ("https://docs.battlecode.cam/spec/conveyors.md", "conveyors.md"),
    ("https://docs.battlecode.cam/spec/core.md", "core.md"),
    ("https://docs.battlecode.cam/spec/harvester-and-foundry.md", "harvester_foundry.md"),
    ("https://docs.battlecode.cam/spec/other-buildings.md", "road_barrier_marker.md"),
    ("https://docs.battlecode.cam/spec/overview.md", "overview.md"),
    ("https://docs.battlecode.cam/spec/reference.md", "reference_tables.md"),
    ("https://docs.battlecode.cam/spec/resources.md", "resources.md"),
    ("https://docs.battlecode.cam/spec/turrets.md", "turrets.md"),
]


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)

    for url, filename in PAGES:
        print(f"Fetching {url} -> docs/{filename}")
        with urllib.request.urlopen(url, timeout=15) as resp:
            content = resp.read().decode("utf-8")
        path = os.path.join(DOCS_DIR, filename)
        with open(path, "w") as f:
            f.write(content)
        print(f"  OK ({len(content)} bytes)")

    print(f"\nDone — {len(PAGES)} pages saved to {DOCS_DIR}/")


if __name__ == "__main__":
    main()
