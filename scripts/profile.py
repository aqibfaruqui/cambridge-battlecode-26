#!/usr/bin/env python3
"""Profile an instrumented v12 bot (harvester or attacker) and interpret the
cProfile .pstats files it dumps.

The instrumentation in bots/v12/builders/harvester.py and
bots/v12/builders/attacker.py writes one .pstats file per bot instance
(one per subinterpreter) to a per-target profile directory. This CLI runs a
match and aggregates those files into a readable report.

You MUST specify the profiling target (harvester or attacker) — there is no
default. Each target writes to a different directory so harvester and attacker
runs don't pollute each other:
  harvester  →  /tmp/harvester_profiles
  attacker   →  /tmp/attacker_profiles

Usage:
  uv run scripts/profile.py run harvester                          # v12 vs v12 on separated, TLE off
  uv run scripts/profile.py run attacker -m default_large1 --bot-b v11
  uv run scripts/profile.py report attacker                        # analyze existing .pstats
  uv run scripts/profile.py report harvester --sort tottime --top 30
  uv run scripts/profile.py report attacker --filter d_star        # only frames matching regex
  uv run scripts/profile.py callers harvester _succ                # who calls a hot function
  uv run scripts/profile.py callees attacker _recompute_rhs        # what it calls

Override the per-target directory with `--profile-dir <path>` if you want a
custom location (e.g. when comparing two harvester runs side-by-side).
"""

from __future__ import annotations

import argparse
import pstats
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_PROFILE_DIRS = {
    "harvester": Path("/tmp/harvester_profiles"),
    "attacker": Path("/tmp/attacker_profiles"),
}
TARGET_CHOICES = tuple(TARGET_PROFILE_DIRS.keys())
DEFAULT_MAP = "separated"
DEFAULT_BOT = "v12"


def _resolve_profile_dir(args: argparse.Namespace) -> Path:
    """An explicit --profile-dir wins; otherwise derive from `target`."""
    if args.profile_dir is not None:
        return Path(args.profile_dir)
    return TARGET_PROFILE_DIRS[args.target]


def _aggregate(profile_dir: Path) -> pstats.Stats:
    files = sorted(profile_dir.glob("*.pstats"))
    if not files:
        print(f"No .pstats files in {profile_dir}", file=sys.stderr)
        print("Run `profile.py run` first, or check the instrumentation writes here.", file=sys.stderr)
        sys.exit(1)
    print(f"Aggregating {len(files)} .pstats file(s) from {profile_dir}\n")
    s = pstats.Stats(str(files[0]))
    for f in files[1:]:
        s.add(str(f))
    return s


def cmd_run(args: argparse.Namespace) -> int:
    profile_dir = _resolve_profile_dir(args)
    if profile_dir.exists() and args.clean:
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    cambc = shutil.which("cambc") or str(ROOT / ".venv" / "bin" / "cambc")
    cmd = [
        cambc, "run", args.bot_a, args.bot_b, args.map,
        "--tle", str(args.tle),
        "--replay", args.replay,
    ]
    if args.seed is not None:
        cmd += ["--seed", str(args.seed)]
    print(f"# Profiling target: {args.target}  (writing to {profile_dir})")
    print("$ " + " ".join(cmd) + "\n")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    print()
    return cmd_report(args)


def cmd_report(args: argparse.Namespace) -> int:
    s = _aggregate(_resolve_profile_dir(args))
    s.strip_dirs()

    for sort_key in args.sort:
        print("=" * 80)
        print(f"TOP {args.top} by {sort_key.upper()}")
        print("=" * 80)
        s.sort_stats(sort_key)
        if args.filter:
            s.print_stats(args.filter, args.top)
        else:
            s.print_stats(args.top)
    return 0


def cmd_callers(args: argparse.Namespace) -> int:
    s = _aggregate(_resolve_profile_dir(args))
    s.strip_dirs().sort_stats("cumulative")
    print(f"CALLERS of functions matching: {args.pattern}\n")
    s.print_callers(args.pattern)
    return 0


def cmd_callees(args: argparse.Namespace) -> int:
    s = _aggregate(_resolve_profile_dir(args))
    s.strip_dirs().sort_stats("cumulative")
    print(f"CALLEES of functions matching: {args.pattern}\n")
    s.print_callees(args.pattern)
    return 0


def _add_target_arg(parser: argparse.ArgumentParser) -> None:
    """Required positional — no default; must explicitly pick which bot."""
    parser.add_argument(
        "target",
        choices=TARGET_CHOICES,
        help="Which bot to profile (required, no default). "
             "Each target uses its own /tmp/<target>_profiles directory.",
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile-dir", default=None,
                   help="Override the per-target .pstats directory "
                        "(defaults: /tmp/harvester_profiles or /tmp/attacker_profiles).")

    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Run a match and produce a report")
    _add_target_arg(pr)
    pr.add_argument("--bot-a", default=DEFAULT_BOT)
    pr.add_argument("--bot-b", default=DEFAULT_BOT)
    pr.add_argument("-m", "--map", default=DEFAULT_MAP)
    pr.add_argument("--seed", type=int, default=None)
    pr.add_argument("--tle", type=int, default=0, help="Turn time limit in ms (0=off, default for profiling)")
    pr.add_argument("--replay", default="/tmp/prof.replay26")
    pr.add_argument("--clean", action="store_true", default=True,
                    help="Delete the profile dir before the run (default: on)")
    pr.add_argument("--no-clean", dest="clean", action="store_false")
    pr.add_argument("--top", type=int, default=25)
    pr.add_argument("--sort", nargs="+", default=["cumulative", "tottime"],
                    help="pstats sort keys (default: cumulative tottime)")
    pr.add_argument("--filter", default=None, help="Regex filter on frame names")
    pr.set_defaults(func=cmd_run)

    prep = sub.add_parser("report", help="Aggregate and report existing .pstats files")
    _add_target_arg(prep)
    prep.add_argument("--top", type=int, default=25)
    prep.add_argument("--sort", nargs="+", default=["cumulative", "tottime"])
    prep.add_argument("--filter", default=None, help="Regex filter on frame names (e.g. 'd_star' or 'raw_map_representation')")
    prep.set_defaults(func=cmd_report)

    pc = sub.add_parser("callers", help="Show callers of functions matching a pattern")
    _add_target_arg(pc)
    pc.add_argument("pattern", help="Regex to match frame names (e.g. '_succ' or 'd_star.py:318')")
    pc.set_defaults(func=cmd_callers)

    pe = sub.add_parser("callees", help="Show callees of functions matching a pattern")
    _add_target_arg(pe)
    pe.add_argument("pattern", help="Regex to match frame names")
    pe.set_defaults(func=cmd_callees)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
