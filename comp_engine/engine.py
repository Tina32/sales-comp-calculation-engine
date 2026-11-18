"""End-to-end monthly run: validate -> calculate -> write auditable output package."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import contract, fiscal, pipeline, state
from .contract import FAIL, ValidationReport
from .manifest import write_manifest
from .payout import calculate_payouts
from .sales import build_sales


@dataclass
class RunResult:
    run_id: str
    reporting_month: str
    report: ValidationReport
    payouts: pd.DataFrame | None = None
    outputs: dict[str, Path] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.report.status


def apply_credit_overrides(
    bookings: pd.DataFrame,
    overrides: pd.DataFrame | None,
    reporting_month: str,
    roster: pd.DataFrame,
    report: ValidationReport,
) -> pd.DataFrame:
    """Reassign every product-line row of an opportunity before sales and rollups are built.

    An override takes effect for the reporting month it was approved for. Because it
    recalculates both rep and manager impact, the same correction must not also be
    submitted as a manual payout adjustment.
    """
    out = bookings.copy()
    out["original_owner_id"] = out["owner_id"]
    out["credit_override_applied"] = False
    if overrides is None:
        return out

    active = overrides[overrides["reporting_month"] == reporting_month]
    roster_ids = set(roster["employee_id"])
    for o in active.itertuples():
        mask = out["opportunity_id"] == o.opportunity_id
        if not mask.any():
            report.fail("OVERRIDE_UNKNOWN_OPPORTUNITY",
                        f"Credit override references unknown opportunity {o.opportunity_id}")
            continue
        if o.rep_id_receiving_credit not in roster_ids:
            report.fail("OVERRIDE_UNKNOWN_REP",
                        f"Credit override for {o.opportunity_id} names {o.rep_id_receiving_credit}, "
                        "who is not in the roster")
            continue
        out.loc[mask, "owner_id"] = o.rep_id_receiving_credit
        out.loc[mask, "credit_override_applied"] = True
        report.ok("OVERRIDE_APPLIED",
                  f"{o.opportunity_id}: {int(mask.sum())} product-line rows credited to "
                  f"{o.rep_id_receiving_credit}")
    return out


def run(input_dir: Path, output_dir: Path, state_dir: Path, reporting_month: str) -> RunResult:
    input_dir, output_dir, state_dir = Path(input_dir), Path(output_dir), Path(state_dir)
    fy, period = fiscal.parse_reporting_month(reporting_month)
    run_id = uuid.uuid4().hex
    report = contract.check_input_files(input_dir)
    result = RunResult(run_id, reporting_month, report)
    if report.status == FAIL:
        return result

    if state.is_locked(state_dir, fy, period):
        report.fail("PERIOD_LOCKED", f"{reporting_month} is already approved and locked")
        return result
    try:
        prior_state = state.load_prior_state(state_dir, fy, period)
    except state.StateError as exc:
        report.fail("PRIOR_STATE", str(exc))
        return result

    data = contract.load_inputs(input_dir, report)
    if report.status == FAIL:
        return result
    roster = data["roster.csv"]

    bookings = apply_credit_overrides(
        data["bookings.csv"], data.get("credit_override.csv"), reporting_month, roster, report
    )
    bookings = fiscal.add_fiscal_columns(bookings, "close_date")
    bookings, bad_probabilities = pipeline.add_weighted_pipeline(bookings)
    if bad_probabilities:
        report.fail("INVALID_PROBABILITY",
                    f"Probability outside 0-1 for: {', '.join(bad_probabilities)}")
    if report.status == FAIL:
        return result

    sales = build_sales(bookings, roster, fy, period, report)
    payouts = calculate_payouts(
        sales, roster, data["goals.csv"], data.get("spiff_bonus.csv"),
        data.get("new_hire_guarantee.csv"), prior_state, fy, period, reporting_month, report,
    )
    if report.status == FAIL:
        return result
    result.payouts = payouts

    # ---- Output package -------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    payout_csv = output_dir / f"payouts_{reporting_month}.csv"
    detail_csv = output_dir / f"pipeline_detail_{reporting_month}.csv"
    workbook = output_dir / f"Sales_Compensation_{reporting_month}_{run_id[:8]}.xlsx"
    payouts.to_csv(payout_csv, index=False)
    bookings.to_csv(detail_csv, index=False)

    summary = pd.DataFrame({
        "item": ["run_id", "reporting_month", "fiscal_year", "fiscal_period",
                 "validation_status", "employees_paid", "total_amount_due"],
        "value": [run_id, reporting_month, fy, period, report.status,
                  int((payouts["amount_due"] > 0).sum()), round(payouts["amount_due"].sum(), 2)],
    })
    with pd.ExcelWriter(workbook, engine="openpyxl") as xl:
        summary.to_excel(xl, sheet_name="Summary", index=False)
        payouts.to_excel(xl, sheet_name="Payouts", index=False)
        sales.to_excel(xl, sheet_name="Sales", index=False)
        pipeline.pipeline_by_owner(bookings).to_excel(xl, sheet_name="Pipeline_By_Owner", index=False)
        report.to_frame().to_excel(xl, sheet_name="Validation", index=False)

    state_file = state.save_state(state_dir, fy, period, run_id, {
        row.employee_id: {
            "cumulative_earned": row.cumulative_earned,
            "carryforward_balance": row.carryforward_ending,
            "paid_ytd": row.paid_ytd,
        }
        for row in payouts.itertuples()
    })

    inputs = sorted(p for p in input_dir.iterdir() if p.is_file())
    outputs = [payout_csv, detail_csv, workbook, state_file]
    manifest = write_manifest(output_dir / f"run_manifest_{reporting_month}.json",
                              run_id, reporting_month, report, inputs, outputs)
    result.outputs = {"payouts": payout_csv, "pipeline_detail": detail_csv,
                      "workbook": workbook, "state": state_file, "manifest": manifest}
    return result
