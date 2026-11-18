"""Attainment, progressive payout curve, SPIFFs, negative carryforward and new-hire guarantees."""
from __future__ import annotations

import math

import pandas as pd

from .contract import ValidationReport

# (lower attainment, upper attainment, payout rate) applied progressively, like tax brackets.
# 100% attainment earns exactly 100% of target incentive.
PAYOUT_TIERS = [
    (0.0, 0.5, 0.5),
    (0.5, 1.0, 1.5),
    (1.0, 1.5, 2.0),
    (1.5, math.inf, 0.5),
]


def payout_factor(attainment: float) -> float:
    return sum(max(0.0, min(attainment, hi) - lo) * rate for lo, hi, rate in PAYOUT_TIERS)


def apply_carryforward(gross: float, opening_balance: float) -> tuple[float, float, float]:
    """Return (payable, applied, ending_balance).

    A negative month is never paid as negative payroll. It becomes a balance that
    offsets future positive earnings.
    """
    if gross <= 0:
        return 0.0, 0.0, opening_balance - gross
    applied = min(opening_balance, gross)
    return gross - applied, applied, opening_balance - applied


def apply_guarantee(payable: float, monthly_guarantee: float | None) -> tuple[float, float]:
    """Return (amount_due, guarantee_adjustment). Guarantee is a floor, tracked separately."""
    if monthly_guarantee is None:
        return payable, 0.0
    amount_due = max(payable, monthly_guarantee)
    return amount_due, amount_due - payable


def _guarantee_for(guarantees: pd.DataFrame | None, emp_id: str, payout_date: pd.Timestamp):
    if guarantees is None:
        return None
    rows = guarantees[guarantees["employee_id"] == emp_id]
    for g in rows.itertuples():
        if pd.Timestamp(g.guarantee_start) <= payout_date <= pd.Timestamp(g.guarantee_end):
            return float(g.monthly_guarantee)
    return None


def calculate_payouts(
    sales: pd.DataFrame,
    roster: pd.DataFrame,
    goals: pd.DataFrame,
    spiffs: pd.DataFrame | None,
    guarantees: pd.DataFrame | None,
    prior_state: dict,
    fiscal_year: int,
    period: int,
    reporting_month: str,
    report: ValidationReport,
) -> pd.DataFrame:
    goals_fy = goals[goals["fiscal_year"] == fiscal_year].set_index("employee_id")
    payout_date = pd.Timestamp(f"{reporting_month}-01") + pd.offsets.MonthEnd(0)
    month_spiffs = (
        spiffs[spiffs["reporting_month"] == reporting_month] if spiffs is not None else None
    )

    rows = []
    for r in sales.merge(roster, on="employee_id").itertuples():
        if not bool(r.sip_eligible):
            if r.ytd_sales > 0:
                report.warn("NON_SIP_SALES",
                            f"{r.employee_id} has Closed Won sales but is not SIP eligible")
            continue
        if r.employee_id not in goals_fy.index:
            report.fail("MISSING_GOAL", f"No FY{fiscal_year} goal for {r.employee_id}")
            continue

        goal = goals_fy.loc[r.employee_id]
        target_ytd = goal["annual_goal"] * period / 12
        attainment = r.ytd_sales / target_ytd if target_ytd else 0.0
        factor = payout_factor(attainment)
        cumulative_earned = goal["annual_target_incentive"] * period / 12 * factor

        prior = prior_state.get(r.employee_id, {})
        earned_this_month = cumulative_earned - prior.get("cumulative_earned", 0.0)

        spiff_bonus, spiff_notes = 0.0, ""
        if month_spiffs is not None:
            emp_spiffs = month_spiffs[month_spiffs["employee_id"] == r.employee_id]
            spiff_bonus = float(emp_spiffs["spiff_bonus"].sum())
            spiff_notes = "; ".join(emp_spiffs["spiff_notes"].dropna().astype(str))

        gross = earned_this_month + spiff_bonus
        opening = prior.get("carryforward_balance", 0.0)
        payable, applied, ending = apply_carryforward(gross, opening)
        amount_due, guarantee_adj = apply_guarantee(
            payable, _guarantee_for(guarantees, r.employee_id, payout_date)
        )

        rows.append({
            "employee_id": r.employee_id,
            "employee_name": r.employee_name,
            "role": r.role,
            "is_rollup": r.is_rollup,
            "month_sales": r.month_sales,
            "ytd_sales": r.ytd_sales,
            "ytd_goal": target_ytd,
            "ytd_attainment": attainment,
            "payout_factor": factor,
            "cumulative_earned": cumulative_earned,
            "earned_this_month": earned_this_month,
            "spiff_bonus": spiff_bonus,
            "spiff_notes": spiff_notes,
            "carryforward_opening": opening,
            "carryforward_applied": applied,
            "carryforward_ending": ending,
            "new_hire_guarantee_adjustment": guarantee_adj,
            "amount_due": amount_due,
            "paid_ytd": prior.get("paid_ytd", 0.0) + amount_due,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        money = out.select_dtypes("number").columns.difference(["ytd_attainment", "payout_factor"])
        out[money] = out[money].round(2)
        out[["ytd_attainment", "payout_factor"]] = out[["ytd_attainment", "payout_factor"]].round(4)
    return out
