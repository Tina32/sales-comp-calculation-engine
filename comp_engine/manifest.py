"""JSON run manifest with SHA-256 hashes of every input and output, for audit traceability."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .contract import ValidationReport


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    path: Path,
    run_id: str,
    reporting_month: str,
    report: ValidationReport,
    inputs: list[Path],
    outputs: list[Path],
) -> Path:
    doc = {
        "run_id": run_id,
        "reporting_month": reporting_month,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation_status": report.status,
        "findings": [vars(f) for f in report.findings if f.level != "PASS"],
        "inputs": {p.name: sha256(p) for p in inputs},
        "outputs": {p.name: sha256(p) for p in outputs},
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path
