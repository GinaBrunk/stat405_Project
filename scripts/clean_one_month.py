#!/usr/bin/env python3
"""Clean one BTS monthly raw file for delay propagation analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_utils import (
    BASE_DIR,
    REQUIRED_CANONICAL_COLUMNS,
    ensure_project_dirs,
    infer_year_month_from_path,
    parse_hhmm_timestamp,
    read_raw_header,
    read_raw_month,
    resolve_column_selection,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Path to one raw monthly CSV/ZIP")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "processed" / "monthly_clean",
        help="Directory for clean_YYYY_MM.csv outputs",
    )
    return parser.parse_args()


def process_month(input_path: Path, output_dir: Path) -> dict[str, int | str]:
    ensure_project_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)

    available_columns = read_raw_header(input_path)
    usecols, rename_map, missing = resolve_column_selection(available_columns)
    if missing:
        raise ValueError(
            f"Missing required columns in {input_path.name}: {', '.join(missing)}"
        )

    df = read_raw_month(input_path, usecols=usecols).rename(columns=rename_map)
    input_rows = len(df)

    df["TAIL_NUM"] = df["TAIL_NUM"].astype("string").str.strip()
    df["FL_DATE"] = pd.to_datetime(df["FL_DATE"], errors="coerce")

    numeric_cols = [
        "CRS_DEP_TIME",
        "CRS_ARR_TIME",
        "DEP_DELAY",
        "ARR_DELAY",
        "DISTANCE",
        "CANCELLED",
        "DIVERTED",
        "MONTH",
        "DAY_OF_WEEK",
        "CRS_ELAPSED_TIME",
        "DEP_TIME",
        "ARR_TIME",
    ]
    for column in numeric_cols:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    missing_counts = {
        column: int(df[column].isna().sum()) for column in REQUIRED_CANONICAL_COLUMNS if column in df
    }

    df = df.loc[df["TAIL_NUM"].notna() & (df["TAIL_NUM"] != "")]
    df = df.loc[df["FL_DATE"].notna()]
    df = df.loc[df["CRS_DEP_TIME"].notna() & df["CRS_ARR_TIME"].notna()]
    df = df.loc[(df["CANCELLED"].fillna(0) != 1) & (df["DIVERTED"].fillna(0) != 1)].copy()

    if "MONTH" not in df.columns:
        df["MONTH"] = df["FL_DATE"].dt.month.astype("Int64")
    if "DAY_OF_WEEK" not in df.columns:
        df["DAY_OF_WEEK"] = (df["FL_DATE"].dt.dayofweek + 1).astype("Int64")

    dep_ts, dep_hour = parse_hhmm_timestamp(df["FL_DATE"], df["CRS_DEP_TIME"])
    arr_ts, arr_hour = parse_hhmm_timestamp(df["FL_DATE"], df["CRS_ARR_TIME"])
    overnight_mask = dep_ts.notna() & arr_ts.notna() & (arr_ts < dep_ts)
    arr_ts.loc[overnight_mask] = arr_ts.loc[overnight_mask] + pd.Timedelta(days=1)

    df["sched_dep_timestamp"] = dep_ts
    df["sched_arr_timestamp"] = arr_ts
    df["sched_dep_hour"] = dep_hour
    df["sched_arr_hour"] = arr_hour
    df["month"] = pd.to_numeric(df["MONTH"], errors="coerce").astype("Int64")
    df["day_of_week"] = pd.to_numeric(df["DAY_OF_WEEK"], errors="coerce").astype("Int64")
    df["route"] = df["ORIGIN"].astype("string") + "-" + df["DEST"].astype("string")

    df["FL_DATE"] = df["FL_DATE"].dt.strftime("%Y-%m-%d")

    year_month = infer_year_month_from_path(input_path)
    if year_month is None:
        if df.empty:
            raise ValueError(f"Could not infer year-month from empty input {input_path}")
        year_month = (
            int(pd.to_datetime(df["FL_DATE"]).dt.year.iloc[0]),
            int(pd.to_datetime(df["FL_DATE"]).dt.month.iloc[0]),
        )

    output_path = output_dir / f"clean_{year_month[0]}_{year_month[1]:02d}.csv"
    output_columns = [
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
        "MONTH",
        "DAY_OF_WEEK",
        "CRS_ELAPSED_TIME",
        "DEP_TIME",
        "ARR_TIME",
        "sched_dep_hour",
        "sched_arr_hour",
        "month",
        "day_of_week",
        "route",
        "sched_dep_timestamp",
        "sched_arr_timestamp",
    ]
    output_columns = [column for column in output_columns if column in df.columns]
    df.to_csv(output_path, index=False, columns=output_columns)

    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "input_rows": int(input_rows),
        "output_rows": int(len(df)),
        "distinct_tail_numbers": int(df["TAIL_NUM"].nunique()),
    }
    for column, count in missing_counts.items():
        summary[f"missing_{column}"] = int(count)
    return summary


def main() -> int:
    args = parse_args()
    summary = process_month(args.input, args.output_dir)
    print(f"input={summary['input']}")
    print(f"output={summary['output']}")
    print(f"input_rows={summary['input_rows']}")
    print(f"output_rows={summary['output_rows']}")
    print(f"distinct_tail_numbers={summary['distinct_tail_numbers']}")
    missing_keys = sorted(key for key in summary if key.startswith("missing_"))
    for key in missing_keys:
        print(f"{key}={summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
