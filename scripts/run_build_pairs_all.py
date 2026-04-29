#!/usr/bin/env python3
"""Run pair-building over all partition files."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_pairs_one_partition import build_pairs_for_partition
from pipeline_utils import BASE_DIR, ensure_project_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=BASE_DIR / "processed" / "partitions",
        help="Directory containing part_XXX.csv files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "processed" / "pairs",
        help="Directory for pairs_XXX.csv outputs",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=BASE_DIR / "logs" / "build_pairs_all.log",
        help="Log file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of partitions for local testing",
    )
    return parser.parse_args()


def append_log(log_file: Path, message: str) -> None:
    print(message)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    args.log_file.write_text("", encoding="utf-8")

    partition_files = sorted(args.input_dir.glob("part_*.csv"))
    if args.limit is not None:
        partition_files = partition_files[: args.limit]
    if not partition_files:
        raise FileNotFoundError(f"No partition files found in {args.input_dir}")

    append_log(args.log_file, f"Discovered {len(partition_files)} partition files.")
    for path in partition_files:
        append_log(args.log_file, f"Building pairs for {path}")
        summary = build_pairs_for_partition(path, args.output_dir)
        append_log(
            args.log_file,
            (
                f"Finished {Path(summary['output']).name}: "
                f"raw_rows={summary['raw_rows']}, "
                f"candidate_pairs={summary['candidate_pairs']}, "
                f"output_pairs={summary['output_pairs']}"
            ),
        )

    append_log(args.log_file, "All pair-building jobs completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
