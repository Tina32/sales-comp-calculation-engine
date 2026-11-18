"""Generate a fully synthetic, seeded input set. No real people, deals or company data."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FY_MONTHS = pd.date_range("2025-04-01", "2026-03-01", freq="MS")  # FY2026
PRODUCT_LINES = ["Analytics", "Platform", "Services", "Support"]
OPEN_STAGES = {"Prospecting": 10, "Qualification": 40, "Negotiation": 75}

# Monthly performance vs. quota. E007 is front-loaded to show negative carryforward;
# E008 is a new hire on a guarantee; E009 is not SIP eligible.
PERFORMANCE = {"E001": 1.3, "E002": 1.0, "E003": 0.85, "E004": 1.1,
               "E005": 0.95, "E006": 1.6, "E008": 0.4, "E009": 0.3}


def _roster() -> pd.DataFrame:
    rows = [("M01", "Manager One", "manager", "", True),
            ("M02", "Manager Two", "manager", "", True)]
    for i in range(1, 10):
        emp = f"E{i:03d}"
        rows.append((emp, f"Rep {i:02d}", "rep", "M01" if i <= 4 else "M02", emp != "E009"))
    return pd.DataFrame(rows, columns=["employee_id", "employee_name", "role",
                                       "supervisor_id", "sip_eligible"])


def _goals(roster: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in roster.itertuples():
        if r.role == "rep":
            goal = 600_000 if r.employee_id == "E008" else 1_200_000
            rows.append((r.employee_id, 2026, goal, 60_000))
    reps = pd.DataFrame(rows, columns=["employee_id", "fiscal_year", "annual_goal",
                                       "annual_target_incentive"])
    team = reps.merge(roster[["employee_id", "supervisor_id"]]).groupby("supervisor_id")
    for mgr, grp in team:
        rows.append((mgr, 2026, int(grp["annual_goal"].sum()), 90_000))
    return pd.DataFrame(rows, columns=reps.columns)


def _bookings(rng: np.random.Generator, goals: pd.DataFrame) -> pd.DataFrame:
    goal_by_emp = goals.set_index("employee_id")["annual_goal"]
    rows, opp_seq = [], 0

    def add_opportunity(owner: str, close: pd.Timestamp, stage: str, prob, amount: float):
        nonlocal opp_seq
        opp_seq += 1
        lines = rng.choice(PRODUCT_LINES, size=rng.integers(1, 4), replace=False)
        for line, share in zip(lines, rng.dirichlet(np.ones(len(lines)))):
            rows.append((f"OPP-{opp_seq:05d}", line, owner, close.date().isoformat(),
                         stage, prob, round(amount * share, 2)))

    def random_day(month_start: pd.Timestamp) -> pd.Timestamp:
        return month_start + pd.Timedelta(days=int(rng.integers(0, month_start.days_in_month)))

    for owner in [f"E{i:03d}" for i in range(1, 10)]:
        monthly_quota = goal_by_emp.get(owner, 600_000) / 12
        for idx, month in enumerate(FY_MONTHS):
            if owner == "E007":
                perf = 3.0 if idx == 0 else 0.2
            else:
                perf = PERFORMANCE[owner]
            won_total = monthly_quota * perf * rng.uniform(0.75, 1.25)
            n_won = int(rng.integers(2, 5))
            for share in rng.dirichlet(np.ones(n_won)):
                prob = 100 if rng.random() < 0.5 else 1.0
                add_opportunity(owner, random_day(month), "Closed Won", prob, won_total * share)
            for _ in range(int(rng.integers(1, 3))):
                add_opportunity(owner, random_day(month), "Closed Lost", 0,
                                monthly_quota * rng.uniform(0.1, 0.4))
            stage = str(rng.choice(list(OPEN_STAGES)))
            pct = OPEN_STAGES[stage]
            prob = pct if rng.random() < 0.5 else pct / 100  # mixed 60 / 0.60 formats
            add_opportunity(owner, random_day(month + pd.DateOffset(months=2)), stage, prob,
                            monthly_quota * rng.uniform(0.2, 0.8))
        add_opportunity(owner, random_day(FY_MONTHS[-1]), "", None, monthly_quota * 0.1)

    return pd.DataFrame(rows, columns=["opportunity_id", "product_line", "owner_id",
                                       "close_date", "stage", "probability", "total_price"])


def generate(input_dir: Path, seed: int = 7) -> list[Path]:
    rng = np.random.default_rng(seed)
    input_dir = Path(input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)

    roster = _roster()
    goals = _goals(roster)
    bookings = _bookings(rng, goals)

    spiffs = pd.DataFrame([
        ("E002", "2025-06", 1500.0, "Launch SPIFF: new Analytics module"),
        ("E006", "2025-08", 2000.0, "Multi-year renewal SPIFF"),
    ], columns=["employee_id", "reporting_month", "spiff_bonus", "spiff_notes"])

    guarantees = pd.DataFrame([("E008", "2025-04-01", "2025-09-30", 4000.0)],
                              columns=["employee_id", "guarantee_start", "guarantee_end",
                                       "monthly_guarantee"])

    sept_won = bookings[(bookings["owner_id"] == "E003") & (bookings["stage"] == "Closed Won")
                        & bookings["close_date"].str.startswith("2025-09")]
    overrides = pd.DataFrame([("2025-09", sept_won["opportunity_id"].iloc[0], "E004")],
                             columns=["reporting_month", "opportunity_id",
                                      "rep_id_receiving_credit"])

    files = {
        "roster.csv": roster, "goals.csv": goals, "bookings.csv": bookings,
        "spiff_bonus.csv": spiffs, "new_hire_guarantee.csv": guarantees,
        "credit_override.csv": overrides,
    }
    paths = []
    for name, df in files.items():
        path = input_dir / name
        df.to_csv(path, index=False)
        paths.append(path)
    return paths
