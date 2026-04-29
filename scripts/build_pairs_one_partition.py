#!/usr/bin/env python3
"""Build one-leg consecutive-flight pairs for one aircraft-tail partition."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline_utils import BASE_DIR, ensure_project_dirs


PAIR_COLUMNS = [
    "TAIL_NUM",
    "OP_UNIQUE_CARRIER",
    "current_FL_DATE",
    "current_ORIGIN",
    "current_DEST",
    "current_route",
    "current_sched_dep_hour",
    "current_DEP_DELAY",
    "current_ARR_DELAY",
    "current_DISTANCE",
    "prev_ORIGIN",
    "prev_DEST",
    "prev_route",
    "prev_ARR_DELAY",
    "prev_DEP_DELAY",
    "prev_DISTANCE",
    "prev_sched_arr_timestamp",
    "current_sched_dep_timestamp",
    "scheduled_turnaround_minutes",
    "same_airport_connection",
    "current_dep_delayed_15",
    "prev_arr_delayed_15",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", required=True, type=Path, help="Path to one part_XXX.csv file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "processed" / "pairs",
        help="Directory for pairs_XXX.csv outputs",
    )
    return parser.parse_args()


def build_pairs_for_partition(partition_path: Path, output_dir: Path) -> dict[str, int | str]:
    ensure_project_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)

    part_match = re.search(r"part_(\d+)\.csv$", partition_path.name)
    if not part_match:
        raise ValueError(f"Could not parse partition id from {partition_path.name}")
    part_id = part_match.group(1)

    df = pd.read_csv(partition_path, low_memory=False)
    raw_rows = len(df)
    if raw_rows == 0:
        out_path = output_dir / f"pairs_{part_id}.csv"
        pd.DataFrame(columns=PAIR_COLUMNS).to_csv(out_path, index=False)
        return {
            "partition": str(partition_path),
            "output": str(out_path),
            "raw_rows": 0,
            "candidate_pairs": 0,
            "output_pairs": 0,
        }

    df["sched_dep_timestamp"] = pd.to_datetime(df["sched_dep_timestamp"], errors="coerce")
    df["sched_arr_timestamp"] = pd.to_datetime(df["sched_arr_timestamp"], errors="coerce")
    df = df.sort_values(["TAIL_NUM", "sched_dep_timestamp"], kind="mergesort").reset_index(drop=True)

    grouped = df.groupby("TAIL_NUM", sort=False)
    df["prev_ORIGIN"] = grouped["ORIGIN"].shift(1)
    df["prev_DEST"] = grouped["DEST"].shift(1)
    df["prev_route"] = grouped["route"].shift(1)
    df["prev_ARR_DELAY"] = grouped["ARR_DELAY"].shift(1)
    df["prev_DEP_DELAY"] = grouped["DEP_DELAY"].shift(1)
    df["prev_DISTANCE"] = grouped["DISTANCE"].shift(1)
    df["prev_sched_arr_timestamp"] = grouped["sched_arr_timestamp"].shift(1)

    pair_df = pd.DataFrame(
        {
            "TAIL_NUM": df["TAIL_NUM"],
            "OP_UNIQUE_CARRIER": df["OP_UNIQUE_CARRIER"],
            "current_FL_DATE": df["FL_DATE"],
            "current_ORIGIN": df["ORIGIN"],
            "current_DEST": df["DEST"],
            "current_route": df["route"],
            "current_sched_dep_hour": df["sched_dep_hour"],
            "current_DEP_DELAY": df["DEP_DELAY"],
            "current_ARR_DELAY": df["ARR_DELAY"],
            "current_DISTANCE": df["DISTANCE"],
            "prev_ORIGIN": df["prev_ORIGIN"],
            "prev_DEST": df["prev_DEST"],
            "prev_route": df["prev_route"],
            "prev_ARR_DELAY": df["prev_ARR_DELAY"],
            "prev_DEP_DELAY": df["prev_DEP_DELAY"],
            "prev_DISTANCE": df["prev_DISTANCE"],
            "prev_sched_arr_timestamp": df["prev_sched_arr_timestamp"],
            "current_sched_dep_timestamp": df["sched_dep_timestamp"],
        }
    )
    same_airport = (
        pair_df["prev_DEST"].astype("string") == pair_df["current_ORIGIN"].astype("string")
    ).fillna(False)
    pair_df["same_airport_connection"] = same_airport.astype(int)
    pair_df["scheduled_turnaround_minutes"] = (
        pair_df["current_sched_dep_timestamp"] - pair_df["prev_sched_arr_timestamp"]
    ).dt.total_seconds() / 60.0
    pair_df["current_dep_delayed_15"] = (pair_df["current_DEP_DELAY"] > 15).astype(int)
    pair_df["prev_arr_delayed_15"] = (pair_df["prev_ARR_DELAY"] > 15).astype(int)

    candidate_pairs = int(pair_df["prev_sched_arr_timestamp"].notna().sum())
    pair_df = pair_df.loc[pair_df["same_airport_connection"] == 1].copy()
    pair_df = pair_df.loc[pair_df["scheduled_turnaround_minutes"].between(20, 600, inclusive="both")]
    pair_df = pair_df[PAIR_COLUMNS]

    out_path = output_dir / f"pairs_{part_id}.csv"
    pair_df.to_csv(out_path, index=False)
    return {
        "partition": str(partition_path),
        "output": str(out_path),
        "raw_rows": int(raw_rows),
        "candidate_pairs": int(candidate_pairs),
        "output_pairs": int(len(pair_df)),
    }


def main() -> int:
    args = parse_args()
    summary = build_pairs_for_partition(args.partition, args.output_dir)
    print(f"partition={summary['partition']}")
    print(f"output={summary['output']}")
    print(f"raw_rows={summary['raw_rows']}")
    print(f"candidate_pairs={summary['candidate_pairs']}")
    print(f"output_pairs={summary['output_pairs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
