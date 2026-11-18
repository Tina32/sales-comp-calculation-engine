import math

import pandas as pd
import pytest

from comp_engine import contract, fiscal, pipeline, state
from comp_engine.payout import apply_carryforward, apply_guarantee, payout_factor


# ---- fiscal calendar ------------------------------------------------------------------
@pytest.mark.parametrize("month, expected", [
    ("2025-04", (2026, 1)), ("2025-12", (2026, 9)), ("2026-03", (2026, 12)), ("2026-04", (2027, 1)),
])
def test_parse_reporting_month(month, expected):
    assert fiscal.parse_reporting_month(month) == expected


def test_months_through():
    assert fiscal.months_in_fiscal_year_through("2025-06") == ["2025-04", "2025-05", "2025-06"]


# ---- weighted pipeline ----------------------------------------------------------------
def _bookings(rows):
    return pd.DataFrame(rows, columns=["opportunity_id", "stage", "probability", "total_price"])


def test_weighted_pipeline_rules():
    df = _bookings([
        ("A", "Closed Won", 100, 1000.0),
        ("B", "Negotiation", 60, 1000.0),
        ("C", "Negotiation", 0.60, 1000.0),
        ("D", "Closed Lost", 0, 1000.0),
        ("E", "", None, 1000.0),
        ("E", None, None, 500.0),
    ])
    out, bad = pipeline.add_weighted_pipeline(df)
    w = out["weighted_pipeline_amount"].tolist()
    assert w[0] == 1000.0
    assert w[1] == pytest.approx(600.0) and w[2] == pytest.approx(600.0)
    assert all(math.isnan(x) for x in w[3:])
    assert bad == []
    assert len(out) == len(df)  # product-line rows are never deduplicated


def test_invalid_probability_flagged():
    _, bad = pipeline.add_weighted_pipeline(_bookings([("X", "Qualification", 150, 10.0),
                                                       ("Y", "Qualification", -5, 10.0)]))
    assert bad == ["X", "Y"]


# ---- payout curve, carryforward, guarantee --------------------------------------------
@pytest.mark.parametrize("att, factor", [(0, 0), (0.5, 0.25), (1.0, 1.0), (1.5, 2.0), (2.0, 2.25)])
def test_payout_factor(att, factor):
    assert payout_factor(att) == pytest.approx(factor)


def test_negative_month_becomes_carryforward():
    assert apply_carryforward(-500.0, 0.0) == (0.0, 0.0, 500.0)
    assert apply_carryforward(-200.0, 500.0) == (0.0, 0.0, 700.0)


def test_carryforward_offsets_future_earnings():
    assert apply_carryforward(300.0, 500.0) == (0.0, 300.0, 200.0)
    assert apply_carryforward(800.0, 500.0) == (300.0, 500.0, 0.0)


def test_guarantee_is_a_floor():
    assert apply_guarantee(1000.0, 4000.0) == (4000.0, 3000.0)
    assert apply_guarantee(5000.0, 4000.0) == (5000.0, 0.0)
    assert apply_guarantee(1000.0, None) == (1000.0, 0.0)


# ---- input contract -------------------------------------------------------------------
def test_missing_required_file_fails(tmp_path):
    (tmp_path / "roster.csv").write_text("x")
    report = contract.check_input_files(tmp_path)
    assert report.status == "FAIL"
    assert {f.code for f in report.findings if f.level == "FAIL"} == {"REQUIRED_MISSING"}


def test_optional_absent_and_unexpected_file(tmp_path):
    for name in contract.REQUIRED_FILES:
        (tmp_path / name).write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    report = contract.check_input_files(tmp_path)
    assert report.status == "WARNING"
    assert [f.code for f in report.findings if f.level == "WARNING"] == ["UNEXPECTED_FILE"]


# ---- governed state -------------------------------------------------------------------
def test_state_requires_locked_prior_period(tmp_path):
    with pytest.raises(state.StateError, match="Run and lock"):
        state.load_prior_state(tmp_path, 2026, 2)
    state.save_state(tmp_path, 2026, 1, "run1", {"E001": {"cumulative_earned": 1.0}})
    with pytest.raises(state.StateError, match="not locked"):
        state.load_prior_state(tmp_path, 2026, 2)
    state.lock_state(tmp_path, 2026, 1)
    assert state.load_prior_state(tmp_path, 2026, 2) == {"E001": {"cumulative_earned": 1.0}}


def test_locked_period_cannot_be_overwritten(tmp_path):
    state.save_state(tmp_path, 2026, 1, "run1", {})
    state.lock_state(tmp_path, 2026, 1)
    with pytest.raises(state.StateError, match="locked"):
        state.save_state(tmp_path, 2026, 1, "run2", {})
