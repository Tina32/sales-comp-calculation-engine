"""Monthly and YTD sales per employee, plus manager rollups with reconciliation."""
from __future__ import annotations

import pandas as pd

from .contract import ValidationReport
from .pipeline import is_closed_won


def build_sales(
    bookings: pd.DataFrame,
    roster: pd.DataFrame,
    fiscal_year: int,
    period: int,
    report: ValidationReport,
) -> pd.DataFrame:
    won = bookings[
        is_closed_won(bookings)
        & (bookings["fiscal_year"] == fiscal_year)
        & (bookings["fiscal_period"] <= period)
    ]

    unknown = sorted(set(won["owner_id"]) - set(roster["employee_id"]))
    if unknown:
        report.warn(
            "OWNER_NOT_IN_ROSTER",
            f"Closed Won activity for owners not in roster (excluded, needs QC): {', '.join(unknown)}",
        )

    by_period = won.groupby(["owner_id", "fiscal_period"])["total_price"].sum()

    def sales_for(emp_id: str) -> tuple[float, float]:
        if emp_id not in by_period.index.get_level_values(0):
            return 0.0, 0.0
        emp = by_period.loc[emp_id]
        return float(emp.get(period, 0.0)), float(emp.sum())

    reps = roster[roster["role"] == "rep"]
    rows = []
    for rep in reps.itertuples():
        month, ytd = sales_for(rep.employee_id)
        rows.append({"employee_id": rep.employee_id, "month_sales": month,
                     "ytd_sales": ytd, "is_rollup": False})
    rep_sales = pd.DataFrame(rows)

    managers = roster[roster["role"] == "manager"]
    manager_ids = set(managers["employee_id"])
    orphans = sorted(reps.loc[~reps["supervisor_id"].isin(manager_ids), "employee_id"])
    if orphans:
        report.warn("REP_WITHOUT_MANAGER",
                    f"Reps whose supervisor is not a rostered manager: {', '.join(orphans)}")

    with_sup = rep_sales.merge(reps[["employee_id", "supervisor_id"]], on="employee_id")
    rollup = with_sup.groupby("supervisor_id")[["month_sales", "ytd_sales"]].sum()
    mgr_rows = []
    for mgr in managers.itertuples():
        totals = rollup.loc[mgr.employee_id] if mgr.employee_id in rollup.index else None
        mgr_rows.append({
            "employee_id": mgr.employee_id,
            "month_sales": float(totals["month_sales"]) if totals is not None else 0.0,
            "ytd_sales": float(totals["ytd_sales"]) if totals is not None else 0.0,
            "is_rollup": True,
        })
    mgr_sales = pd.DataFrame(mgr_rows, columns=rep_sales.columns)

    # Reconciliation: manager rollups must equal the direct-report contributor rows they summarize.
    covered = with_sup[with_sup["supervisor_id"].isin(manager_ids)]
    diff = abs(mgr_sales["ytd_sales"].sum() - covered["ytd_sales"].sum())
    if diff > 0.01:
        report.warn("ROLLUP_MISMATCH", f"Manager YTD rollups differ from direct reports by {diff:,.2f}")
    else:
        report.ok("ROLLUP_RECONCILED", "Manager rollups reconcile to direct-report totals")

    return pd.concat([rep_sales, mgr_sales], ignore_index=True)
