"""
VO₂ baseline configuration.

Personalized Z2 baselines derived from lactate-verified Zone 2 sessions
with Polar H10 respiratory data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class VO2Baseline:
    """Personalized Z2 baseline parameters."""

    # Session metadata
    baseline_date: date
    workout_id: str

    # Performance at Z2 threshold
    power_watts: float
    hr_bpm: float
    lactate_mmol: float

    # Respiratory baseline (for Gate 2)
    rr_median: float  # Median respiratory rate (br/min)
    rr_mad: float     # Median absolute deviation

    # HRV baseline
    rmssd_ms: float
    sdnn_ms: float

    @property
    def rr_elevated_threshold(self) -> float:
        """RR threshold for 'elevated' detection."""
        return self.rr_median + max(6, 3 * self.rr_mad)

    @property
    def rr_failing_threshold(self) -> float:
        """Minimum RR drop for 'failing to recover' detection."""
        return max(1.5, 2 * self.rr_mad)

    @property
    def rr_chaotic_threshold(self) -> float:
        """RR variability threshold for 'chaotic' detection."""
        return max(2.0, 2 * self.rr_mad)


# Current personalized baseline (updated 2026-01-06)
CURRENT_BASELINE = VO2Baseline(
    baseline_date=date(2026, 1, 5),
    workout_id="110743430",
    power_watts=149.0,
    hr_bpm=116.0,
    lactate_mmol=2.0,
    rr_median=28.0,
    rr_mad=2.0,
    rmssd_ms=7.5,
    sdnn_ms=33.1,
)


def calculate_zone2_rr_baseline(
    data_path: str = "Data/Parquet",
    workout_ids: list[str] | None = None,
    auto_detect: bool = True
) -> dict:
    """
    Calculate personalized RR baseline from Zone 2 sessions.
    """
    con = duckdb.connect()

    if workout_ids is None and auto_detect:
        # Find lactate-verified Zone 2 workouts
        query = f"""
        WITH z2_candidates AS (
            SELECT DISTINCT w.workout_id
            FROM read_parquet('{data_path}/workouts/**/*.parquet') w
            LEFT JOIN read_parquet('{data_path}/lactate/**/*.parquet') l ON w.workout_id = l.workout_id
            WHERE w.source = 'Concept2'
              AND w.duration_s BETWEEN 1800 AND 3600
              AND (l.lactate_mmol IS NULL OR l.lactate_mmol BETWEEN 1.0 AND 2.2)
            ORDER BY w.start_time_utc DESC
            LIMIT 5
        )
        SELECT workout_id FROM z2_candidates
        """
        try:
            workout_ids = con.execute(query).df()["workout_id"].tolist()
        except Exception as e:
            log.warning(f"Error auto-detecting Z2 sessions: {e}")
            workout_ids = []

    if not workout_ids:
        return {
            "rr_z2_med": CURRENT_BASELINE.rr_median,
            "rr_z2_mad": CURRENT_BASELINE.rr_mad,
            "source": "fallback",
        }

    # Get respiratory data
    ids_str = "', '".join(workout_ids)
    query = f"""
    SELECT
        respiratory_rate
    FROM read_parquet('{data_path}/polar_respiratory/**/*.parquet')
    WHERE workout_id IN ('{ids_str}')
      AND confidence > 0.5
    """
    try:
        resp_df = con.execute(query).df()
    except Exception as e:
        log.warning(f"Error querying respiratory data for baseline: {e}")
        return {
            "rr_z2_med": CURRENT_BASELINE.rr_median,
            "rr_z2_mad": CURRENT_BASELINE.rr_mad,
            "source": "error_fallback",
        }

    if resp_df.empty:
        return {
            "rr_z2_med": CURRENT_BASELINE.rr_median,
            "rr_z2_mad": CURRENT_BASELINE.rr_mad,
            "source": "empty_fallback",
        }

    rr_med = resp_df["respiratory_rate"].median()
    rr_mad = (resp_df["respiratory_rate"] - rr_med).abs().median()

    return {
        "rr_z2_med": float(rr_med),
        "rr_z2_mad": float(rr_mad),
        "workout_count": len(workout_ids),
        "source": "calculated",
    }


def get_gate2_params(data_path: str = "Data/Parquet") -> dict:
    """Get Gate 2 parameters, dynamically calculating if possible."""
    baseline = calculate_zone2_rr_baseline(data_path=data_path)
    return {
        "zone2_baseline_rr_med": baseline["rr_z2_med"],
        "zone2_baseline_rr_mad": baseline["rr_z2_mad"],
    }
