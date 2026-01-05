"""
Polar H10 ECG/RR data ingestion.

Processes CSV exports from Polar Sensor Logger app containing:
- Raw ECG at ~130 Hz
- R-R intervals (beat-to-beat timing)
- Instantaneous HR

Derives respiratory rate from ECG using EDR (ECG-Derived Respiration) method.
"""
from __future__ import annotations

import glob
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
from scipy import signal
from scipy.interpolate import interp1d

from pipeline.common.parquet_io import upsert_by_key
from pipeline.common.schema import get_schema
from pipeline.paths import (
    RAW_POLAR_DIR,
    POLAR_RR_PATH,
    POLAR_SESSION_PATH,
    POLAR_RESPIRATORY_PATH,
)

log = logging.getLogger(__name__)

# Alias for readability
POLAR_RAW_PATH = RAW_POLAR_DIR


def parse_polar_csv(file_path: Path) -> dict:
    """
    Parse a Polar Sensor Logger CSV file.

    Returns:
        dict with keys:
            - ecg: DataFrame with time, ecg columns
            - rr: DataFrame with time, rr columns
            - hr: DataFrame with time, hr columns
            - metadata: dict with file info
    """
    df = pd.read_csv(file_path)

    # Convert nanosecond timestamps to datetime (truncate to microseconds for schema)
    start_ns = df["time"].min()
    start_utc = pd.Timestamp(start_ns // 1000, unit="us", tz="UTC")
    end_ns = df["time"].max()
    end_utc = pd.Timestamp(end_ns // 1000, unit="us", tz="UTC")

    # Separate data types
    ecg_data = df[["time", "ecg"]].copy()
    ecg_data["time_sec"] = (ecg_data["time"] - start_ns) / 1e9

    rr_data = df[df["rr"].notna()][["time", "rr"]].copy()
    rr_data["time_sec"] = (rr_data["time"] - start_ns) / 1e9

    hr_data = df[df["hr"].notna()][["time", "hr"]].copy()
    hr_data["time_sec"] = (hr_data["time"] - start_ns) / 1e9

    duration_sec = (end_ns - start_ns) / 1e9

    return {
        "ecg": ecg_data,
        "rr": rr_data,
        "hr": hr_data,
        "metadata": {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "duration_sec": duration_sec,
            "sample_count": len(df),
            "rr_count": len(rr_data),
        },
    }


def derive_respiratory_rate_edr(
    ecg_data: pd.DataFrame,
    window_sec: float = 30.0,
    step_sec: float = 15.0,
    fs: float = 130.0,
) -> pd.DataFrame:
    """
    Derive respiratory rate from ECG using EDR (ECG-Derived Respiration).

    Uses R-wave amplitude modulation caused by chest movement during breathing.

    Args:
        ecg_data: DataFrame with 'time_sec' and 'ecg' columns
        window_sec: Analysis window in seconds
        step_sec: Step between windows
        fs: ECG sample rate in Hz

    Returns:
        DataFrame with respiratory rate for each window
    """
    ecg = ecg_data["ecg"].values
    time_sec = ecg_data["time_sec"].values

    # Bandpass filter ECG (0.5-40 Hz)
    sos = signal.butter(4, [0.5, 40], btype="band", fs=fs, output="sos")
    ecg_filt = signal.sosfilt(sos, ecg)

    # Detect R-peaks
    threshold = np.std(ecg_filt) * 2
    peaks, properties = signal.find_peaks(ecg_filt, height=threshold, distance=int(fs * 0.4))

    if len(peaks) < 10:
        return pd.DataFrame()

    # Get R-peak amplitudes and times
    r_amplitudes = ecg_filt[peaks]
    r_times = time_sec[peaks]

    # Interpolate to uniform sampling for spectral analysis
    amp_interp = interp1d(r_times, r_amplitudes, kind="linear", fill_value="extrapolate")
    fs_resp = 4  # Hz for respiratory analysis
    t_uniform = np.arange(r_times.min(), r_times.max(), 1 / fs_resp)
    amp_uniform = amp_interp(t_uniform)

    # Calculate respiratory rate in sliding windows
    window_samples = int(window_sec * fs_resp)
    step_samples = int(step_sec * fs_resp)

    results = []
    for start in range(0, len(amp_uniform) - window_samples, step_samples):
        end = start + window_samples
        window = signal.detrend(amp_uniform[start:end])

        # FFT
        freqs = np.fft.rfftfreq(len(window), 1 / fs_resp)
        fft = np.abs(np.fft.rfft(window))

        # Respiratory band: 0.15-0.7 Hz (9-42 br/min)
        mask = (freqs >= 0.15) & (freqs <= 0.7)
        if np.any(mask) and np.any(fft[mask] > 0):
            resp_freqs = freqs[mask]
            resp_power = fft[mask]
            peak_idx = np.argmax(resp_power)
            resp_rate = resp_freqs[peak_idx] * 60  # breaths/min

            # Confidence based on peak prominence
            peak_power = resp_power[peak_idx]
            total_power = np.sum(resp_power)
            confidence = peak_power / total_power if total_power > 0 else 0

            window_center = t_uniform[start + window_samples // 2]
            results.append(
                {
                    "window_start_sec": t_uniform[start],
                    "window_end_sec": t_uniform[end - 1],
                    "window_center_min": window_center / 60,
                    "respiratory_rate": resp_rate,
                    "confidence": confidence,
                }
            )

    return pd.DataFrame(results)


def calculate_hrv_metrics(rr_intervals: np.ndarray) -> dict:
    """Calculate HRV metrics from RR intervals."""
    if len(rr_intervals) < 2:
        return {"rmssd_ms": None, "sdnn_ms": None}

    # RMSSD - root mean square of successive differences
    diffs = np.diff(rr_intervals)
    rmssd = np.sqrt(np.mean(diffs**2))

    # SDNN - standard deviation of NN intervals
    sdnn = np.std(rr_intervals)

    return {"rmssd_ms": float(rmssd), "sdnn_ms": float(sdnn)}


def match_to_concept2_workout(
    start_utc: pd.Timestamp, end_utc: pd.Timestamp
) -> str | None:
    """
    Try to match Polar session to a Concept2 workout by timestamp overlap.

    Returns workout_id if matched, None otherwise.
    """
    try:
        import duckdb

        con = duckdb.connect()
        result = con.execute(
            f"""
            SELECT workout_id
            FROM read_parquet('Data/Parquet/workouts/**/*.parquet')
            WHERE source = 'Concept2'
              AND start_time_utc BETWEEN '{start_utc - pd.Timedelta(minutes=5)}'
                                     AND '{end_utc + pd.Timedelta(minutes=5)}'
            ORDER BY ABS(EPOCH(start_time_utc) - EPOCH(TIMESTAMP '{start_utc}'))
            LIMIT 1
        """
        ).fetchone()
        return result[0] if result else None
    except Exception:
        return None


def ingest_polar_file(file_path: Path, ingest_run_id: str) -> dict:
    """
    Ingest a single Polar H10 CSV file.

    Returns:
        dict with counts of ingested records
    """
    log.info(f"Processing {file_path.name}")

    # Parse the CSV
    data = parse_polar_csv(file_path)
    metadata = data["metadata"]

    now_utc = datetime.now(timezone.utc)
    session_id = f"polar_{metadata['start_utc'].strftime('%Y%m%d_%H%M%S')}"

    # Try to match to Concept2 workout
    workout_id = match_to_concept2_workout(metadata["start_utc"], metadata["end_utc"])
    if workout_id:
        log.info(f"Matched to Concept2 workout: {workout_id}")

    counts = {"rr": 0, "sessions": 0, "respiratory": 0}

    # 1. Process RR intervals
    rr_data = data["rr"]
    if len(rr_data) > 0:
        rr_records = []
        cumulative_ms = 0
        for i, row in rr_data.iterrows():
            rr_ms = int(row["rr"])
            cumulative_ms += rr_ms
            rr_records.append(
                {
                    "workout_id": workout_id or session_id,
                    "workout_start_utc": metadata["start_utc"],
                    "beat_number": len(rr_records) + 1,
                    "time_cumulative_ms": cumulative_ms,
                    "rr_interval_ms": rr_ms,
                    "hr_instantaneous": 60000 / rr_ms if rr_ms > 0 else None,
                    "source": "Polar_H10",
                    "ingest_time_utc": now_utc,
                    "ingest_run_id": ingest_run_id,
                    "date": metadata["start_utc"].strftime("%Y-%m-01"),
                }
            )

        rr_df = pd.DataFrame(rr_records)
        upsert_by_key(
            rr_df,
            POLAR_RR_PATH,
            primary_key=["workout_id", "beat_number"],
            partition_cols=["date", "source"],
            schema=get_schema("polar_rr"),
        )
        counts["rr"] = len(rr_df)
        log.info(f"Wrote {counts['rr']} RR intervals")

    # 2. Process session summary
    rr_values = data["rr"]["rr"].values
    hrv_metrics = calculate_hrv_metrics(rr_values)

    session_record = {
        "session_id": session_id,
        "workout_id": workout_id,
        "start_time_utc": metadata["start_utc"],
        "end_time_utc": metadata["end_utc"],
        "duration_sec": float(metadata["duration_sec"]),
        "total_beats": len(rr_values),
        "avg_hr": float(60000 / rr_values.mean()) if len(rr_values) > 0 else None,
        "max_hr": float(60000 / rr_values.min()) if len(rr_values) > 0 else None,
        "min_hr": float(60000 / rr_values.max()) if len(rr_values) > 0 else None,
        "rmssd_ms": hrv_metrics["rmssd_ms"],
        "sdnn_ms": hrv_metrics["sdnn_ms"],
        "source_file": metadata["file_name"],
        "source": "Polar_H10",
        "ingest_time_utc": now_utc,
        "ingest_run_id": ingest_run_id,
        "date": metadata["start_utc"].strftime("%Y-%m-01"),
    }

    session_df = pd.DataFrame([session_record])
    upsert_by_key(
        session_df,
        POLAR_SESSION_PATH,
        primary_key=["session_id"],
        partition_cols=["date", "source"],
        schema=get_schema("polar_session"),
    )
    counts["sessions"] = 1
    log.info(f"Wrote session summary")

    # 3. Derive respiratory rate from ECG
    resp_df = derive_respiratory_rate_edr(data["ecg"])
    if len(resp_df) > 0:
        resp_df["session_id"] = session_id
        resp_df["workout_id"] = workout_id
        resp_df["derivation_method"] = "edr"
        resp_df["source"] = "Polar_H10"
        resp_df["ingest_time_utc"] = now_utc
        resp_df["ingest_run_id"] = ingest_run_id
        resp_df["date"] = metadata["start_utc"].strftime("%Y-%m-01")

        # Add concurrent HR from RR data
        for idx, row in resp_df.iterrows():
            window_rr = rr_data[
                (rr_data["time_sec"] >= row["window_start_sec"])
                & (rr_data["time_sec"] <= row["window_end_sec"])
            ]["rr"]
            if len(window_rr) > 0:
                resp_df.at[idx, "avg_hr"] = 60000 / window_rr.mean()
                resp_df.at[idx, "rmssd_ms"] = calculate_hrv_metrics(window_rr.values)[
                    "rmssd_ms"
                ]

        upsert_by_key(
            resp_df,
            POLAR_RESPIRATORY_PATH,
            primary_key=["session_id", "window_start_sec"],
            partition_cols=["date", "source"],
            schema=get_schema("polar_respiratory"),
        )
        counts["respiratory"] = len(resp_df)
        log.info(f"Wrote {counts['respiratory']} respiratory rate windows")

    return counts


def ingest_all_polar_files(ingest_run_id: str | None = None) -> dict:
    """
    Ingest all Polar H10 CSV files from Data/Raw/Polar/.

    Returns:
        dict with total counts
    """
    if ingest_run_id is None:
        ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    log.info(f"Starting Polar H10 ingestion (run_id={ingest_run_id})")

    # Find all CSV files
    csv_files = list(POLAR_RAW_PATH.glob("*.csv"))
    log.info(f"Found {len(csv_files)} CSV files")

    total_counts = {"rr": 0, "sessions": 0, "respiratory": 0}

    for file_path in csv_files:
        try:
            counts = ingest_polar_file(file_path, ingest_run_id)
            for key in total_counts:
                total_counts[key] += counts.get(key, 0)
        except Exception as e:
            log.error(f"Error processing {file_path.name}: {e}")

    log.info(f"Polar H10 ingestion complete: {total_counts}")
    return total_counts


def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Ingest Polar H10 ECG data")
    parser.add_argument("--file", type=str, help="Specific file to ingest")
    args = parser.parse_args()

    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.file:
        counts = ingest_polar_file(Path(args.file), ingest_run_id)
    else:
        counts = ingest_all_polar_files(ingest_run_id)

    print(f"\n✅ Ingestion complete:")
    print(f"   RR intervals: {counts['rr']}")
    print(f"   Sessions: {counts['sessions']}")
    print(f"   Respiratory windows: {counts['respiratory']}")


if __name__ == "__main__":
    main()
