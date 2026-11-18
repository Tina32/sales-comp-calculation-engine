import json

import pandas as pd
import pytest

from comp_engine import engine, fiscal, state, synthetic
from comp_engine.manifest import sha256


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e")
    inp, out, st = root / "input", root / "output", root / "state"
    synthetic.generate(inp)
    results = {}
    for month in fiscal.months_in_fiscal_year_through("2025-09"):
        result = engine.run(inp, out / month, st, month)
        assert result.status != "FAIL", result.report.findings
        fy, period = fiscal.parse_reporting_month(month)
        state.lock_state(st, fy, period)
        results[month] = result
    return {"root": root, "results": results}


def _row(result, emp):
    return result.payouts.set_index("employee_id").loc[emp]


def test_output_package_written(runs):
    outputs = runs["results"]["2025-09"].outputs
    for key in ("payouts", "pipeline_detail", "workbook", "state", "manifest"):
        assert outputs[key].exists()


def test_manifest_hashes_match_files(runs):
    outputs = runs["results"]["2025-09"].outputs
    doc = json.loads(outputs["manifest"].read_text())
    assert doc["outputs"][outputs["payouts"].name] == sha256(outputs["payouts"])
    assert set(doc["inputs"]) >= {"bookings.csv", "roster.csv", "goals.csv"}


def test_manager_rollup_equals_direct_reports(runs):
    payouts = runs["results"]["2025-09"].payouts.set_index("employee_id")
    reps_m01 = ["E001", "E002", "E003", "E004"]
    assert payouts.loc["M01", "ytd_sales"] == pytest.approx(payouts.loc[reps_m01, "ytd_sales"].sum())


def test_front_loaded_rep_builds_carryforward(runs):
    e007 = _row(runs["results"]["2025-09"], "E007")
    assert e007["carryforward_ending"] > 0
    assert e007["amount_due"] == 0


def test_spiff_paid_in_its_month(runs):
    assert _row(runs["results"]["2025-06"], "E002")["spiff_bonus"] == 1500.0
    assert _row(runs["results"]["2025-07"], "E002")["spiff_bonus"] == 0.0


def test_new_hire_guarantee_applied(runs):
    e008 = _row(runs["results"]["2025-09"], "E008")
    assert e008["amount_due"] >= 4000.0
    assert e008["new_hire_guarantee_adjustment"] > 0


def test_non_sip_employee_excluded_with_warning(runs):
    result = runs["results"]["2025-09"]
    assert "E009" not in set(result.payouts["employee_id"])
    assert any(f.code == "NON_SIP_SALES" for f in result.report.findings)


def test_credit_override_moves_all_product_lines(runs):
    detail = pd.read_csv(runs["results"]["2025-09"].outputs["pipeline_detail"])
    moved = detail[detail["credit_override_applied"]]
    assert not moved.empty
    assert set(moved["owner_id"]) == {"E004"} and set(moved["original_owner_id"]) == {"E003"}


def test_rerunning_locked_period_fails(runs):
    root = runs["root"]
    result = engine.run(root / "input", root / "output" / "again", root / "state", "2025-09")
    assert result.status == "FAIL"
    assert any(f.code == "PERIOD_LOCKED" for f in result.report.findings)
