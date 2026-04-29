#!/usr/bin/env python3
"""Shared helpers for the STAT/DSCP flight delay propagation pipeline."""

from __future__ import annotations

import io
import math
import re
import zipfile
import zlib
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RAW_SEARCH_DIRS = [
    BASE_DIR / "data" / "csv",
    BASE_DIR / "data" / "raw",
    BASE_DIR / "dataset",
]

MONTH_PATTERNS = [
    re.compile(r"flight_data_(\d{4})_(\d{2})\.csv$", re.IGNORECASE),
    re.compile(
        r"On_Time_Reporting_Carrier_On_Time_Performance_1987_present_(\d{4})_(\d{1,2})\.zip$",
        re.IGNORECASE,
    ),
    re.compile(
        r"On_Time_Reporting_Carrier_On_Time_Performance_1987_present_(\d{4})_(\d{1,2})\.csv$",
        re.IGNORECASE,
    ),
    re.compile(
        r"On_Time_Reporting_Carrier_On_Time_Performance_\(1987_present\)_(\d{4})_(\d{1,2})\.csv$",
        re.IGNORECASE,
    ),
    re.compile(r"airlines_(\d{4})_(\d{1,2})\.csv$", re.IGNORECASE),
]

REQUIRED_CANONICAL_COLUMNS = [
    "TAIL_NUM",
    "FL_DATE",
    "OP_UNIQUE_CARRIER",
    "ORIGIN",
    "DEST",
    "CRS_DEP_TIME",
    "CRS_ARR_TIME",
    "DEP_DELAY",
    "ARR_DELAY",
    "DISTANCE",
    "CANCELLED",
    "DIVERTED",
]

OPTIONAL_CANONICAL_COLUMNS = [
    "MONTH",
    "DAY_OF_WEEK",
    "CRS_ELAPSED_TIME",
    "DEP_TIME",
    "ARR_TIME",
]

COLUMN_ALIASES: dict[str, list[str]] = {
    "TAIL_NUM": ["TAIL_NUM", "Tail_Number", "TailNum"],
    "FL_DATE": ["FL_DATE", "FlightDate"],
    "OP_UNIQUE_CARRIER": [
        "OP_UNIQUE_CARRIER",
        "Reporting_Airline",
        "UniqueCarrier",
        "UNIQUE_CARRIER",
    ],
    "ORIGIN": ["ORIGIN", "Origin"],
    "DEST": ["DEST", "Dest"],
    "CRS_DEP_TIME": ["CRS_DEP_TIME", "CRSDepTime"],
    "CRS_ARR_TIME": ["CRS_ARR_TIME", "CRSArrTime"],
    "DEP_DELAY": ["DEP_DELAY", "DepDelay"],
    "ARR_DELAY": ["ARR_DELAY", "ArrDelay"],
    "DISTANCE": ["DISTANCE", "Distance"],
    "CANCELLED": ["CANCELLED", "Cancelled"],
    "DIVERTED": ["DIVERTED", "Diverted"],
    "MONTH": ["MONTH", "Month"],
    "DAY_OF_WEEK": ["DAY_OF_WEEK", "DayOfWeek"],
    "CRS_ELAPSED_TIME": ["CRS_ELAPSED_TIME", "CRSElapsedTime"],
    "DEP_TIME": ["DEP_TIME", "DepTime"],
    "ARR_TIME": ["ARR_TIME", "ArrTime"],
}


def ensure_project_dirs() -> None:
    """Create the main project folders if they are missing."""
    for path in [
        BASE_DIR / "processed",
        BASE_DIR / "processed" / "monthly_clean",
        BASE_DIR / "processed" / "partitions",
        BASE_DIR / "processed" / "pairs",
        BASE_DIR / "results",
        BASE_DIR / "results" / "figures",
        BASE_DIR / "logs",
        BASE_DIR / "scripts",
        BASE_DIR / "chtc",
        BASE_DIR / "data" / "csv",
        BASE_DIR / "data" / "raw",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def infer_year_month_from_path(path: Path) -> tuple[int, int] | None:
    """Return (year, month) when a file name matches a supported monthly pattern."""
    for pattern in MONTH_PATTERNS:
        match = pattern.search(path.name)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _source_priority(path: Path) -> tuple[int, int, str]:
    """Smaller tuples win when selecting a preferred raw source for a month."""
    normalized = str(path)
    if path.suffix.lower() == ".csv" and "/data/csv/" in normalized:
        return (0, len(path.name), normalized)
    if path.suffix.lower() == ".zip":
        return (1, len(path.name), normalized)
    if path.suffix.lower() == ".csv":
        return (2, len(path.name), normalized)
    return (9, len(path.name), normalized)


def discover_monthly_raw_files(
    base_dir: Path = BASE_DIR,
    search_dirs: Iterable[Path] | None = None,
) -> list[Path]:
    """Find one preferred raw monthly source per year-month in the project."""
    search_roots = list(search_dirs or DEFAULT_RAW_SEARCH_DIRS)
    chosen: dict[tuple[int, int], Path] = {}

    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            year_month = infer_year_month_from_path(path)
            if year_month is None:
                continue

            existing = chosen.get(year_month)
            if existing is None or _source_priority(path) < _source_priority(existing):
                chosen[year_month] = path

    return [chosen[key] for key in sorted(chosen)]


def compression_for_path(path: Path) -> str | None:
    if path.suffix.lower() == ".zip":
        return "zip"
    return None


def _zip_csv_member_name(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(
            f"Expected exactly one CSV member inside {path.name}, found {members}"
        )
    return members[0]


def read_raw_header(path: Path) -> list[str]:
    if path.suffix.lower() == ".zip":
        member_name = _zip_csv_member_name(path)
        with zipfile.ZipFile(path) as zf:
            with zf.open(member_name) as handle:
                header = pd.read_csv(
                    io.TextIOWrapper(handle, encoding="utf-8-sig"),
                    nrows=0,
                    low_memory=False,
                )
    else:
        header = pd.read_csv(
            path,
            compression=compression_for_path(path),
            nrows=0,
            low_memory=False,
        )
    return list(header.columns)


def resolve_column_selection(
    available_columns: Iterable[str],
    required_columns: Iterable[str] | None = None,
    optional_columns: Iterable[str] | None = None,
) -> tuple[list[str], dict[str, str], list[str]]:
    """Return usecols, rename map, and missing canonical columns."""
    available = list(available_columns)
    required = list(required_columns or REQUIRED_CANONICAL_COLUMNS)
    optional = list(optional_columns or OPTIONAL_CANONICAL_COLUMNS)

    usecols: list[str] = []
    rename_map: dict[str, str] = {}
    missing: list[str] = []

    for canonical in required + optional:
        raw_name = next(
            (candidate for candidate in COLUMN_ALIASES[canonical] if candidate in available),
            None,
        )
        if raw_name is None:
            if canonical in required:
                missing.append(canonical)
            continue
        usecols.append(raw_name)
        rename_map[raw_name] = canonical

    return usecols, rename_map, missing


def read_raw_month(
    path: Path,
    usecols: list[str] | None = None,
) -> pd.DataFrame:
    """Read one monthly raw file, supporting either CSV or a single-file ZIP archive."""
    if path.suffix.lower() == ".zip":
        member_name = _zip_csv_member_name(path)
        with zipfile.ZipFile(path) as zf:
            with zf.open(member_name) as handle:
                df = pd.read_csv(
                    io.TextIOWrapper(handle, encoding="utf-8-sig"),
                    usecols=usecols,
                    low_memory=False,
                    dtype={"Tail_Number": "string", "TAIL_NUM": "string"},
                )
    else:
        df = pd.read_csv(
            path,
            compression=compression_for_path(path),
            usecols=usecols,
            low_memory=False,
            dtype={"Tail_Number": "string", "TAIL_NUM": "string"},
        )
    unnamed_cols = [col for col in df.columns if str(col).startswith("Unnamed:")]
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)
    return df


def stable_tail_partition(tail_num: str, n_partitions: int) -> int:
    """Assign a reproducible partition id from the aircraft tail number."""
    if pd.isna(tail_num):
        return 0
    encoded = str(tail_num).strip().encode("utf-8")
    return zlib.crc32(encoded) % n_partitions


def parse_hhmm_timestamp(
    flight_dates: pd.Series,
    hhmm_values: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Convert FL_DATE + HHMM into naive local timestamps and extract hour-of-day."""
    base_dates = pd.to_datetime(flight_dates, errors="coerce")
    numeric = pd.to_numeric(hhmm_values, errors="coerce")

    hhmm = numeric.fillna(-1).astype(int)
    extra_day = np.where(hhmm == 2400, 1, 0)
    hhmm = np.where(hhmm == 2400, 0, hhmm)

    hours = hhmm // 100
    minutes = hhmm % 100
    valid = (
        numeric.notna()
        & (hours >= 0)
        & (hours <= 23)
        & (minutes >= 0)
        & (minutes <= 59)
        & base_dates.notna()
    )

    timestamps = pd.Series(pd.NaT, index=hhmm_values.index, dtype="datetime64[ns]")
    timestamps.loc[valid] = (
        base_dates.loc[valid]
        + pd.to_timedelta(extra_day[valid], unit="D")
        + pd.to_timedelta(hours[valid], unit="h")
        + pd.to_timedelta(minutes[valid], unit="m")
    )

    hour_series = pd.Series(pd.NA, index=hhmm_values.index, dtype="Int64")
    hour_series.loc[valid] = pd.Series(hours[valid], index=hhmm_values.index[valid]).astype(
        "Int64"
    )
    return timestamps, hour_series


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Compute a weighted median for positive weights."""
    if len(values) == 0:
        return math.nan
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = 0.5 * sorted_weights.sum()
    idx = np.searchsorted(cumulative, cutoff, side="left")
    idx = min(idx, len(sorted_values) - 1)
    return float(sorted_values[idx])


def count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file without reading the full frame into memory."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        count = sum(1 for _ in handle)
    return max(count - 1, 0)
