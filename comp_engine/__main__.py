"""Command line entry point.

    python -m comp_engine demo --through 2025-09
    python -m comp_engine generate
    python -m comp_engine run --month 2025-04
    python -m comp_engine lock --month 2025-04
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import engine, fiscal, state, synthetic
from .engine import RunResult

DATA = Path("data")
INPUT, OUTPUT, STATE = DATA / "input", DATA / "output", DATA / "state"


def _print_result(result: RunResult) -> None:
    print(f"[{result.reporting_month}] status={result.status} run_id={result.run_id[:8]}")
    for f in result.report.findings:
        if f.level != "PASS":
            print(f"    {f.level:<7} {f.code}: {f.message}")
    if result.payouts is not None:
        total = result.payouts["amount_due"].sum()
        print(f"    total amount due: {total:,.2f} across {len(result.payouts)} employees")
        print(f"    outputs: {result.outputs['workbook'].parent}")


def _run(month: str) -> RunResult:
    result = engine.run(INPUT, OUTPUT / month, STATE, month)
    _print_result(result)
    return result


def _lock(month: str) -> None:
    fy, period = fiscal.parse_reporting_month(month)
    state.lock_state(STATE, fy, period)
    print(f"[{month}] approved and locked")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="comp_engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", help="write synthetic inputs to data/input")
    for name in ("run", "lock"):
        p = sub.add_parser(name)
        p.add_argument("--month", required=True, help="reporting month, YYYY-MM")
    demo = sub.add_parser("demo", help="generate data, then run and lock each month in order")
    demo.add_argument("--through", default="2025-09", help="last reporting month, YYYY-MM")
    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            for path in synthetic.generate(INPUT):
                print(f"wrote {path}")
        elif args.command == "run":
            return 1 if _run(args.month).status == "FAIL" else 0
        elif args.command == "lock":
            _lock(args.month)
        elif args.command == "demo":
            for folder in (INPUT, OUTPUT, STATE):
                shutil.rmtree(folder, ignore_errors=True)
            synthetic.generate(INPUT)
            months = fiscal.months_in_fiscal_year_through(args.through)
            for month in months:
                if _run(month).status == "FAIL":
                    return 1
                if month != months[-1]:
                    _lock(month)
            print(f"[{months[-1]}] left unlocked, awaiting approval "
                  f"(python -m comp_engine lock --month {months[-1]})")
    except (state.StateError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
