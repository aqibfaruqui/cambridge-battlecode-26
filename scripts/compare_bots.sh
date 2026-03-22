#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: scripts/compare_bots.sh BOT_A BOT_B [SEEDS]"
  echo "Example: scripts/compare_bots.sh v5.1 v5 5"
  exit 1
fi

BOT_A="$1"
BOT_B="$2"
SEEDS="${3:-5}"

source .venv/bin/activate
mkdir -p tmp/compare_replays

python - "$BOT_A" "$BOT_B" "$SEEDS" <<'PY'
import concurrent.futures as cf
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

root = pathlib.Path.cwd()
bot_a = sys.argv[1]
bot_b = sys.argv[2]
seed_count = int(sys.argv[3])
maps = sorted((root / "maps").glob("*.map26"))
seeds = list(range(1, seed_count + 1))
cmd_base = [str(root / ".venv" / "bin" / "cambc"), "run", bot_a, bot_b]

winner_re = re.compile(r"Winner:\s+(\S+)\s+\((.+), turn (\d+)\)")
resource_re = re.compile(
    r"^\s*(Titanium|Axionite)\s+([0-9]+)\s+\([^)]*\)\s+([0-9]+)\s+\([^)]*\)\s*$"
)


def run_one(map_path: pathlib.Path, seed: int):
    replay = root / "tmp" / "compare_replays" / f"{bot_a}_vs_{bot_b}_{map_path.stem}_s{seed}.replay26"
    cmd = cmd_base + [str(map_path), "--seed", str(seed), "--replay", str(replay)]
    proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True)
    out = proc.stdout + proc.stderr

    winner = None
    reason = None
    turn = None
    titanium = None

    for line in out.splitlines():
        m = winner_re.search(line)
        if m:
            winner, reason, turn = m.group(1), m.group(2), int(m.group(3))
        m2 = resource_re.match(line)
        if m2 and m2.group(1) == "Titanium":
            titanium = (int(m2.group(2)), int(m2.group(3)))

    ok = proc.returncode == 0 and winner is not None and titanium is not None
    return {
        "map": map_path.name,
        "seed": seed,
        "ok": ok,
        "winner": winner,
        "reason": reason,
        "turn": turn,
        "ti_a": titanium[0] if titanium else None,
        "ti_b": titanium[1] if titanium else None,
    }


jobs = [(m, s) for m in maps for s in seeds]
results = []
with cf.ThreadPoolExecutor(max_workers=min(6, len(jobs))) as ex:
    for res in ex.map(lambda ms: run_one(*ms), jobs):
        results.append(res)

results.sort(key=lambda r: (r["map"], r["seed"]))
by_map = defaultdict(lambda: {"a_wins": 0, "b_wins": 0, "fails": 0, "avg_ti_diff": None, "matches": []})
all_diffs = []

for r in results:
    entry = by_map[r["map"]]
    if not r["ok"]:
        entry["fails"] += 1
        entry["matches"].append({"seed": r["seed"], "winner": None, "reason": "failed", "turn": None, "ti_diff": None})
        continue

    if r["winner"] == bot_a:
        entry["a_wins"] += 1
    elif r["winner"] == bot_b:
        entry["b_wins"] += 1

    ti_diff = r["ti_a"] - r["ti_b"]
    all_diffs.append(ti_diff)
    entry["matches"].append({
        "seed": r["seed"],
        "winner": r["winner"],
        "reason": r["reason"],
        "turn": r["turn"],
        "ti_diff": ti_diff,
    })

for entry in by_map.values():
    diffs = [m["ti_diff"] for m in entry["matches"] if m["ti_diff"] is not None]
    entry["avg_ti_diff"] = round(sum(diffs) / len(diffs), 1) if diffs else None

overall = {
    "matches": len(results),
    "bot_a": bot_a,
    "bot_b": bot_b,
    "a_wins": sum(1 for r in results if r["ok"] and r["winner"] == bot_a),
    "b_wins": sum(1 for r in results if r["ok"] and r["winner"] == bot_b),
    "fails": sum(1 for r in results if not r["ok"]),
    "avg_ti_diff": round(sum(all_diffs) / len(all_diffs), 1) if all_diffs else None,
}

print(json.dumps({"overall": overall, "by_map": dict(by_map)}, indent=2))
PY
