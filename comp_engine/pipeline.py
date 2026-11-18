"""Weighted pipeline at product-line grain.

Rules:
  - closed won                 -> weighted amount = total_price
  - open, non-blank stage      -> weighted amount = total_price x normalized probability
  - closed lost / blank stage  -> null
Probabilities may arrive as 60 or 0.60; both mean 60%. Anything outside 0-1 after
normalization is a validation error. Rows are never deduplicated: one opportunity
can span several product lines.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _stage(df: pd.DataFrame) -> pd.Series:
    return df["stage"].fillna("").astype(str).str.strip().str.lower()


def is_closed_won(df: pd.DataFrame) -> pd.Series:
    return _stage(df) == "closed won"


def normalize_probability(raw: pd.Series) -> pd.Series:
    values = pd.to_numeric(raw, errors="coerce")
    return values.where(values <= 1, values / 100)


def add_weighted_pipeline(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return bookings with weighted_pipeline_amount, plus opportunity IDs with invalid probability."""
    out = df.copy()
    stage = _stage(out)
    won = stage == "closed won"
    closed = stage.str.startswith("closed")
    open_stage = (stage != "") & ~closed

    prob = normalize_probability(out["probability"])
    invalid = prob.notna() & ((prob < 0) | (prob > 1))

    out["normalized_probability"] = prob
    out["weighted_pipeline_amount"] = np.nan
    out.loc[won, "weighted_pipeline_amount"] = out.loc[won, "total_price"]
    weighted = open_stage & prob.notna() & ~invalid
    out.loc[weighted, "weighted_pipeline_amount"] = (
        out.loc[weighted, "total_price"] * prob[weighted]
    )
    bad_ids = sorted(out.loc[invalid & open_stage, "opportunity_id"].astype(str).unique())
    return out, bad_ids


def pipeline_by_owner(bookings: pd.DataFrame) -> pd.DataFrame:
    """Opportunity-owner summary derived from booking detail (no separate upload needed)."""
    summary = (
        bookings.groupby("owner_id", as_index=False)
        .agg(
            opportunities=("opportunity_id", "nunique"),
            product_lines=("opportunity_id", "size"),
            weighted_pipeline_amount=("weighted_pipeline_amount", "sum"),
        )
        .sort_values("weighted_pipeline_amount", ascending=False)
    )
    summary["weighted_pipeline_amount"] = summary["weighted_pipeline_amount"].round(2)
    return summary
