"""Governed prior-period state.

Each run saves the balances the next period depends on (cumulative earned, carryforward,
paid YTD). A period must be approved and locked before the next one can run, and a
locked period can never be overwritten, so approved history can't drift.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class StateError(Exception):
    pass


def state_path(state_dir: Path, fiscal_year: int, period: int) -> Path:
    return state_dir / f"FY{fiscal_year}_P{period:02d}.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_locked(state_dir: Path, fiscal_year: int, period: int) -> bool:
    path = state_path(state_dir, fiscal_year, period)
    return path.exists() and bool(_read(path).get("locked"))


def load_prior_state(state_dir: Path, fiscal_year: int, period: int) -> dict:
    if period == 1:
        return {}
    path = state_path(state_dir, fiscal_year, period - 1)
    if not path.exists():
        raise StateError(f"No state for FY{fiscal_year} P{period - 1:02d}. Run and lock it first.")
    doc = _read(path)
    if not doc.get("locked"):
        raise StateError(f"FY{fiscal_year} P{period - 1:02d} is not locked. Approve and lock it first.")
    return doc["employees"]


def save_state(state_dir: Path, fiscal_year: int, period: int, run_id: str, employees: dict) -> Path:
    if is_locked(state_dir, fiscal_year, period):
        raise StateError(f"FY{fiscal_year} P{period:02d} is locked and cannot be overwritten.")
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_path(state_dir, fiscal_year, period)
    doc = {"fiscal_year": fiscal_year, "period": period, "run_id": run_id,
           "locked": False, "employees": employees}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def lock_state(state_dir: Path, fiscal_year: int, period: int) -> Path:
    path = state_path(state_dir, fiscal_year, period)
    if not path.exists():
        raise StateError(f"Nothing to lock: FY{fiscal_year} P{period:02d} has not been run.")
    doc = _read(path)
    if doc.get("locked"):
        raise StateError(f"FY{fiscal_year} P{period:02d} is already locked.")
    doc["locked"] = True
    doc["locked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path
