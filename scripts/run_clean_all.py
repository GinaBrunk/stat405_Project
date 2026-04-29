#!/usr/bin/env python3
"""Run monthly cleaning over all discovered raw monthly files."""

from __future__ import annotations

import argparse
from pathlib import Path

from clean_one_month import process_month
from pipeline_utils import BASE_DIR, discover_monthly_raw_files, ensure_project_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "processed" / "monthly_clean",
        help="Directory for cleaned monthly outputs",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=BASE_DIR / "logs" / "clean_all.log",
        help="Log file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of monthly files for local testing",
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

    raw_files = discover_monthly_raw_files()
    if args.limit is not None:
        raw_files = raw_files[: args.limit]

    if not raw_files:
        raise FileNotFoundError("No monthly raw files were discovered in the project folder.")

    append_log(args.log_file, f"Discovered {len(raw_files)} monthly raw files.")
    for path in raw_files:
        append_log(args.log_file, f"Cleaning {path}")
        summary = process_month(path, args.output_dir)
        append_log(
            args.log_file,
            (
                f"Finished {Path(summary['output']).name}: "
                f"input_rows={summary['input_rows']}, "
                f"output_rows={summary['output_rows']}, "
                f"distinct_tail_numbers={summary['distinct_tail_numbers']}"
            ),
        )

    append_log(args.log_file, "All monthly cleaning jobs completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
