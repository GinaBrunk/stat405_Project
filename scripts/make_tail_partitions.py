#!/usr/bin/env python3
"""Partition cleaned flights by aircraft tail number."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pipeline_utils import BASE_DIR, ensure_project_dirs, stable_tail_partition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=BASE_DIR / "processed" / "monthly_clean",
        help="Directory containing clean_YYYY_MM.csv files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "processed" / "partitions",
        help="Directory for part_XXX.csv outputs",
    )
    parser.add_argument("--n-partitions", type=int, required=True, help="Number of hash partitions")
    parser.add_argument(
        "--chunksize",
        type=int,
        default=200_000,
        help="Chunk size when reading cleaned monthly files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    input_files = sorted(args.input_dir.glob("clean_*.csv"))
    if not input_files:
        raise FileNotFoundError(f"No cleaned monthly files found in {args.input_dir}")

    for old_file in args.output_dir.glob("part_*.csv"):
        old_file.unlink()

    headers_written = {part_id: False for part_id in range(args.n_partitions)}
    total_rows = 0

    for path in input_files:
        print(f"Partitioning {path.name}")
        for chunk in pd.read_csv(path, chunksize=args.chunksize, low_memory=False):
            total_rows += len(chunk)
            chunk["partition_id"] = chunk["TAIL_NUM"].map(
                lambda tail: stable_tail_partition(tail, args.n_partitions)
            )
            for part_id, group in chunk.groupby("partition_id", sort=False):
                out_path = args.output_dir / f"part_{int(part_id):03d}.csv"
                group.drop(columns=["partition_id"]).to_csv(
                    out_path,
                    mode="a",
                    header=not headers_written[int(part_id)],
                    index=False,
                )
                headers_written[int(part_id)] = True

    print(f"Processed {len(input_files)} cleaned monthly files.")
    print(f"Total rows assigned to partitions: {total_rows}")
    print(f"Wrote {args.n_partitions} partition slots to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
