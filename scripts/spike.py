#!/usr/bin/env python3
"""Analyse per-turn spike traces emitted by the harvester (or any bot wired
with the same SPK1 file format).

cProfile averages everything; this script reads the *full distribution* of
per-turn wall-clock times, so we can see how spiky a bot is — p99, p99.9,
max — and which sections (env_update, chain_memory, state_*, …) dominate
the worst turns. That is the diagnostic the user asked for: locate where
we are most abrupt, not just where we burn the most aggregate time.

File format (one .spikes file per bot subinterpreter):
  header  : 4s 'SPK1' | uint32 N_SECTIONS | uint32 RECORD_SIZE_BYTES
  records : uint32 round | uint64 total_ns | uint64 * N_SECTIONS section_ns

Usage:
  uv run scripts/spike.py report harvester
  uv run scripts/spike.py report harvester --top 20
  uv run scripts/spike.py worst harvester --n 15
  uv run scripts/spike.py sections harvester
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_SPIKE_DIRS = {
    "harvester": Path("/tmp/harvester_spikes"),
    # leave room for an attacker variant if it picks up the same harness
    "attacker": Path("/tmp/attacker_spikes"),
}
TARGET_CHOICES = tuple(TARGET_SPIKE_DIRS.keys())

_SECTION_NAMES = (
    "env_update",
    "chain_memory",
    "foundry_check",
    "symmetry_broadcast",
    "heal_nearby",
    "try_enter_defend",
    "try_enter_heal",
    "state_seek",
    "state_placing",
    "state_return",
    "state_defend",
    "state_patrol",
    "state_heal",
    "broadcaster",
    "draw_log",
)


def _resolve_dir(args: argparse.Namespace) -> Path:
    if args.spike_dir is not None:
        return Path(args.spike_dir)
    return TARGET_SPIKE_DIRS[args.target]


def _load(spike_dir: Path) -> tuple[list[int], list[int], list[list[int]]]:
    """Return (rounds, totals_ns, per_section_ns).

    per_section_ns is parallel to rounds: per_section_ns[i][k] is section k
    of turn i. Aggregates across all .spikes files in the directory (one per
    bot subinterpreter)."""
    files = sorted(spike_dir.glob("*.spikes"))
    if not files:
        print(f"No .spikes files in {spike_dir}", file=sys.stderr)
        print("Run the bot first — the harness writes here from harvester.py.",
              file=sys.stderr)
        sys.exit(1)

    rounds: list[int] = []
    totals: list[int] = []
    sections: list[list[int]] = []

    for path in files:
        data = path.read_bytes()
        if len(data) < 12:
            print(f"warn: {path} too small, skipping", file=sys.stderr)
            continue
        magic, n_sec, rec_size = struct.unpack("<4sII", data[:12])
        if magic != b"SPK1":
            print(f"warn: {path} bad magic {magic!r}, skipping", file=sys.stderr)
            continue
        if n_sec != len(_SECTION_NAMES):
            print(
                f"warn: {path} has {n_sec} sections; this script expects "
                f"{len(_SECTION_NAMES)}. Section names may not line up.",
                file=sys.stderr,
            )
        fmt = "<IQ" + "Q" * n_sec
        size = struct.calcsize(fmt)
        if size != rec_size:
            print(f"warn: {path} record size mismatch ({size} vs {rec_size}), skipping",
                  file=sys.stderr)
            continue
        body = data[12:]
        if len(body) % size != 0:
            # truncated tail — drop the partial.
            body = body[: len(body) - (len(body) % size)]
        unpack = struct.Struct(fmt).unpack_from
        for off in range(0, len(body), size):
            rec = unpack(body, off)
            rounds.append(rec[0])
            totals.append(rec[1])
            sections.append(list(rec[2:]))

    if not totals:
        print(f"No samples found in {spike_dir}", file=sys.stderr)
        sys.exit(1)
    return rounds, totals, sections


def _percentile(sorted_vals: list[int], p: float) -> int:
    if not sorted_vals:
        return 0
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]
    # nearest-rank, no interpolation — we want a real observed sample, not a synthesised one.
    k = max(0, min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _fmt_us(ns: int) -> str:
    if ns >= 1_000_000:
        return f"{ns / 1_000_000:8.2f} ms"
    if ns >= 1_000:
        return f"{ns / 1_000:8.2f} µs"
    return f"{ns:8d} ns"


def cmd_report(args: argparse.Namespace) -> int:
    rounds, totals, sections = _load(_resolve_dir(args))
    sorted_totals = sorted(totals)
    n = len(totals)
    mean = sum(totals) / n

    print(f"Per-turn distribution from {n} samples across "
          f"{len(set(rounds))} unique rounds")
    print()
    print(f"  count    {n}")
    print(f"  mean     {_fmt_us(int(mean))}")
    print(f"  p50      {_fmt_us(_percentile(sorted_totals, 50))}")
    print(f"  p90      {_fmt_us(_percentile(sorted_totals, 90))}")
    print(f"  p99      {_fmt_us(_percentile(sorted_totals, 99))}")
    print(f"  p99.9    {_fmt_us(_percentile(sorted_totals, 99.9))}")
    print(f"  max      {_fmt_us(sorted_totals[-1])}")
    print()
    # Spike concentration: what fraction of total time is spent in the worst 1% of turns?
    cutoff = max(1, n // 100)
    worst_sum = sum(sorted_totals[-cutoff:])
    total_sum = sum(sorted_totals)
    print(f"  worst 1% of turns ({cutoff}) account for "
          f"{worst_sum / total_sum * 100:.1f}% of total runtime")

    # Section-attributed dominant cost across all turns.
    print()
    print(f"{'section':<20}  {'sum':>12}  {'mean':>10}  {'p99':>10}  {'max':>10}")
    by_sec: list[tuple[str, int, int, int, int]] = []
    for k, name in enumerate(_SECTION_NAMES):
        vals = sorted(s[k] for s in sections)
        sm = sum(vals)
        mn = sm // n
        by_sec.append((name, sm, mn, _percentile(vals, 99), vals[-1]))
    by_sec.sort(key=lambda r: r[1], reverse=True)
    for name, sm, mn, p99, mx in by_sec:
        print(f"{name:<20}  {_fmt_us(sm):>12}  {_fmt_us(mn):>10}  "
              f"{_fmt_us(p99):>10}  {_fmt_us(mx):>10}")
    return 0


def cmd_worst(args: argparse.Namespace) -> int:
    rounds, totals, sections = _load(_resolve_dir(args))
    # Index by (-total_ns, idx) so we can break ties stably.
    order = sorted(range(len(totals)), key=lambda i: -totals[i])[: args.n]
    print(f"Worst {len(order)} turns (round = controller round, may collide across bots)")
    print()
    header = f"{'round':>7}  {'total':>11}  " + "  ".join(
        f"{n:>10}" for n in _SECTION_NAMES
    )
    print(header)
    for i in order:
        secs = sections[i]
        line = f"{rounds[i]:>7}  {_fmt_us(totals[i]):>11}  " + "  ".join(
            _fmt_us(s) for s in secs
        )
        print(line)
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    """Per-section distribution: for each section, show p50/p90/p99/max
    *across all turns*. Helps decide which section's tail is the spike source."""
    _rounds, _totals, sections = _load(_resolve_dir(args))
    print(f"{'section':<22}  {'p50':>10}  {'p90':>10}  {'p99':>10}  {'p99.9':>10}  {'max':>10}")
    for k, name in enumerate(_SECTION_NAMES):
        vals = sorted(s[k] for s in sections)
        print(f"{name:<22}  {_fmt_us(_percentile(vals, 50)):>10}  "
              f"{_fmt_us(_percentile(vals, 90)):>10}  "
              f"{_fmt_us(_percentile(vals, 99)):>10}  "
              f"{_fmt_us(_percentile(vals, 99.9)):>10}  "
              f"{_fmt_us(vals[-1]):>10}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--spike-dir", default=None,
                   help="Override the per-target spike dir (defaults: /tmp/<target>_spikes).")

    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("report", help="Distribution + section sums")
    pr.add_argument("target", choices=TARGET_CHOICES)
    pr.set_defaults(func=cmd_report)

    pw = sub.add_parser("worst", help="Show the N slowest turns with section breakdown")
    pw.add_argument("target", choices=TARGET_CHOICES)
    pw.add_argument("--n", type=int, default=10)
    pw.set_defaults(func=cmd_worst)

    ps = sub.add_parser("sections", help="Per-section percentile distribution")
    ps.add_argument("target", choices=TARGET_CHOICES)
    ps.set_defaults(func=cmd_sections)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
