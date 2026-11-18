"""April-to-March fiscal calendar. FY2026 runs April 2025 through March 2026."""
from __future__ import annotations

import pandas as pd

FISCAL_START_MONTH = 4


def parse_reporting_month(reporting_month: str) -> tuple[int, int]:
    """'2025-09' -> (fiscal_year=2026, fiscal_period=6)."""
    try:
        ts = pd.Timestamp(f"{reporting_month}-01")
    except ValueError as exc:
        raise ValueError(f"Reporting month must look like YYYY-MM, got {reporting_month!r}") from exc
    return fiscal_year(ts), fiscal_period(ts)


def fiscal_year(ts: pd.Timestamp) -> int:
    return ts.year + 1 if ts.month >= FISCAL_START_MONTH else ts.year


def fiscal_period(ts: pd.Timestamp) -> int:
    return (ts.month - FISCAL_START_MONTH) % 12 + 1


def months_in_fiscal_year_through(reporting_month: str) -> list[str]:
    """Every reporting month from the start of the fiscal year up to and including this one."""
    _, period = parse_reporting_month(reporting_month)
    end = pd.Timestamp(f"{reporting_month}-01")
    start = end - pd.DateOffset(months=period - 1)
    return [d.strftime("%Y-%m") for d in pd.date_range(start, end, freq="MS")]


def add_fiscal_columns(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    out = df.copy()
    dates = pd.to_datetime(out[date_col])
    out["fiscal_year"] = dates.dt.year + (dates.dt.month >= FISCAL_START_MONTH).astype(int)
    out["fiscal_period"] = (dates.dt.month - FISCAL_START_MONTH) % 12 + 1
    return out
