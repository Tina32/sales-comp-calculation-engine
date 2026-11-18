"""Input contract: which files the engine expects, and run-level validation status.

Inputs fall into four classes so the business only supplies what actually changed:
  - recurring source   : refreshed every month (CRM bookings export)
  - reusable reference : reused until the underlying business information changes
  - exception input    : supplied only when a documented override applies
  - engine-derived     : never uploaded; computed from source (YTD sales, pipeline)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED_FILES = {
    "bookings.csv": "recurring source",
    "roster.csv": "reusable reference",
    "goals.csv": "reusable reference",
}
OPTIONAL_FILES = {
    "spiff_bonus.csv": "reusable reference",
    "new_hire_guarantee.csv": "reusable reference",
    "credit_override.csv": "exception input",
}
REQUIRED_COLUMNS = {
    "bookings.csv": ["opportunity_id", "product_line", "owner_id", "close_date",
                     "stage", "probability", "total_price"],
    "roster.csv": ["employee_id", "employee_name", "role", "supervisor_id", "sip_eligible"],
    "goals.csv": ["employee_id", "fiscal_year", "annual_goal", "annual_target_incentive"],
    "spiff_bonus.csv": ["employee_id", "reporting_month", "spiff_bonus", "spiff_notes"],
    "new_hire_guarantee.csv": ["employee_id", "guarantee_start", "guarantee_end",
                               "monthly_guarantee"],
    "credit_override.csv": ["reporting_month", "opportunity_id", "rep_id_receiving_credit"],
}

PASS, WARNING, FAIL = "PASS", "WARNING", "FAIL"


@dataclass
class Finding:
    level: str
    code: str
    message: str


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    def ok(self, code: str, message: str) -> None:
        self.findings.append(Finding(PASS, code, message))

    def warn(self, code: str, message: str) -> None:
        self.findings.append(Finding(WARNING, code, message))

    def fail(self, code: str, message: str) -> None:
        self.findings.append(Finding(FAIL, code, message))

    @property
    def status(self) -> str:
        levels = {f.level for f in self.findings}
        if FAIL in levels:
            return FAIL
        if WARNING in levels:
            return WARNING
        return PASS

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(f) for f in self.findings], columns=["level", "code", "message"])


def _files_by_lower_name(input_dir: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and not path.name.startswith("."):
            found.setdefault(path.name.lower(), []).append(path)
    return found


def check_input_files(input_dir: Path) -> ValidationReport:
    """Gate the run on file readiness before any data is read."""
    report = ValidationReport()
    if not input_dir.is_dir():
        report.fail("INPUT_DIR_MISSING", f"Input directory not found: {input_dir}")
        return report

    found = _files_by_lower_name(input_dir)
    for name, paths in found.items():
        if len(paths) > 1:
            report.fail("DUPLICATE_FILE", f"Duplicate case-insensitive filename: {name}")

    for name, kind in REQUIRED_FILES.items():
        if name in found:
            report.ok("REQUIRED_PRESENT", f"{name} ({kind}) present")
        else:
            report.fail("REQUIRED_MISSING", f"Required {kind} file missing: {name}")

    for name in OPTIONAL_FILES:
        if name not in found:
            report.ok("OPTIONAL_ABSENT", f"{name} not supplied (optional, not blocking)")

    unexpected = set(found) - set(REQUIRED_FILES) - set(OPTIONAL_FILES)
    for name in sorted(unexpected):
        report.warn("UNEXPECTED_FILE", f"Unexpected file in input directory (QC review): {name}")
    return report


def load_inputs(input_dir: Path, report: ValidationReport) -> dict[str, pd.DataFrame]:
    """Read every known file that is present and check its required columns."""
    found = _files_by_lower_name(input_dir)
    frames: dict[str, pd.DataFrame] = {}
    for name in [*REQUIRED_FILES, *OPTIONAL_FILES]:
        if name not in found:
            continue
        df = pd.read_csv(found[name][0], dtype={"reporting_month": str, "supervisor_id": str})
        missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
        if missing:
            report.fail("MISSING_COLUMNS", f"{name} is missing columns: {', '.join(missing)}")
        frames[name] = df
    return frames
