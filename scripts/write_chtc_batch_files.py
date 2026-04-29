#!/usr/bin/env python3
"""Generate CHTC batch submit files for full-sample cleaning, pairing, and modeling."""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline_utils import BASE_DIR, discover_monthly_raw_files, ensure_project_dirs, infer_year_month_from_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chtc-dir",
        type=Path,
        default=BASE_DIR / "chtc",
        help="Directory for generated CHTC submit files",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=BASE_DIR,
        help="Project root path as seen on the CHTC login node",
    )
    parser.add_argument(
        "--clean-output-dir",
        default="processed/monthly_clean",
        help="Relative output directory for cleaned monthly files",
    )
    parser.add_argument(
        "--partitions-dir",
        default="processed/partitions",
        help="Relative directory containing partition files",
    )
    parser.add_argument(
        "--pairs-dir",
        default="processed/pairs",
        help="Relative directory containing pair files",
    )
    parser.add_argument(
        "--results-dir",
        default="results/full_sample",
        help="Relative directory for full-sample model outputs",
    )
    parser.add_argument("--start-year", type=int, default=None, help="Optional inclusive start year filter")
    parser.add_argument("--end-year", type=int, default=None, help="Optional inclusive end year filter")
    parser.add_argument(
        "--name-suffix",
        default="",
        help="Optional suffix for generated file names, e.g. _2015_2024",
    )
    parser.add_argument("--n-partitions", type=int, default=100, help="Number of tail partitions")
    parser.add_argument("--clean-memory", default="6GB", help="request_memory for cleaning jobs")
    parser.add_argument("--clean-disk", default="12GB", help="request_disk for cleaning jobs")
    parser.add_argument("--pairs-memory", default="6GB", help="request_memory for pair jobs")
    parser.add_argument("--pairs-disk", default="12GB", help="request_disk for pair jobs")
    parser.add_argument("--model-memory", default="32GB", help="request_memory for pooled model job")
    parser.add_argument("--model-disk", default="30GB", help="request_disk for pooled model job")
    return parser.parse_args()


def filtered_raw_files(args: argparse.Namespace, raw_files: list[Path]) -> list[Path]:
    selected: list[Path] = []
    for path in raw_files:
        year_month = infer_year_month_from_path(path)
        if year_month is None:
            continue
        year, _ = year_month
        if args.start_year is not None or args.end_year is not None:
            if args.start_year is not None and year < args.start_year:
                continue
            if args.end_year is not None and year > args.end_year:
                continue
        selected.append(path)
    return selected


def write_clean_submit(args: argparse.Namespace, raw_files: list[Path]) -> None:
    out_path = args.chtc_dir / f"clean_all_months{args.name_suffix}.sub"
    lines = [
        "universe = vanilla",
        f"initialdir = {args.project_root}",
        "executable = chtc/clean_one_month.sh",
        f"arguments = $(input_path) {args.clean_output_dir}",
        "",
        "should_transfer_files = YES",
        "when_to_transfer_output = ON_EXIT",
        "preserve_relative_paths = True",
        "transfer_input_files = scripts/clean_one_month.py,scripts/pipeline_utils.py,python_deps,$(input_path)",
        f"transfer_output_files = {args.clean_output_dir}",
        "",
        "output = logs/chtc_clean_all_$(cluster)_$(process).out",
        "error = logs/chtc_clean_all_$(cluster)_$(process).err",
        "log = logs/chtc_clean_all_$(cluster).log",
        "",
        "request_cpus = 1",
        f"request_memory = {args.clean_memory}",
        f"request_disk = {args.clean_disk}",
        "",
        "queue input_path from (",
    ]
    lines.extend(str(path.relative_to(BASE_DIR)) for path in raw_files)
    lines.append(")")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pairs_submit(args: argparse.Namespace) -> None:
    out_path = args.chtc_dir / f"build_pairs_all{args.name_suffix}.sub"
    lines = [
        "universe = vanilla",
        f"initialdir = {args.project_root}",
        "executable = chtc/build_pairs_one_partition.sh",
        f"arguments = $(partition_path) {args.pairs_dir}",
        "",
        "should_transfer_files = YES",
        "when_to_transfer_output = ON_EXIT",
        "preserve_relative_paths = True",
        "transfer_input_files = scripts/build_pairs_one_partition.py,scripts/pipeline_utils.py,python_deps,$(partition_path)",
        f"transfer_output_files = {args.pairs_dir}",
        "",
        f"output = logs/chtc_pairs_all{args.name_suffix}_$(cluster)_$(process).out",
        f"error = logs/chtc_pairs_all{args.name_suffix}_$(cluster)_$(process).err",
        f"log = logs/chtc_pairs_all{args.name_suffix}_$(cluster).log",
        "",
        "request_cpus = 1",
        f"request_memory = {args.pairs_memory}",
        f"request_disk = {args.pairs_disk}",
        "",
        "queue partition_path from (",
    ]
    for part_id in range(args.n_partitions):
        lines.append(f"{args.partitions_dir}/part_{part_id:03d}.csv")
    lines.append(")")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_model_files(args: argparse.Namespace) -> None:
    shell_path = args.chtc_dir / f"fit_delay_models_full{args.name_suffix}.sh"
    shell_path.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                "",
                f'PAIRS_DIR="${{1:-{args.pairs_dir}}}"',
                f'RESULTS_DIR="${{2:-{args.results_dir}}}"',
                f'FIGURES_DIR="${{3:-{args.results_dir}/figures}}"',
                'PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"',
                "",
                'if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then',
                '  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"',
                "fi",
                "",
                'PYTHON_BIN="${PYTHON_BIN:-python3}"',
                'mkdir -p "${RESULTS_DIR}" "${FIGURES_DIR}"',
                "",
                '"${PYTHON_BIN}" scripts/fit_delay_models.py \\',
                '  --pairs-dir "${PAIRS_DIR}" \\',
                '  --results-dir "${RESULTS_DIR}" \\',
                '  --figures-dir "${FIGURES_DIR}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    submit_path = args.chtc_dir / f"fit_delay_models_full{args.name_suffix}.sub"
    submit_path.write_text(
        "\n".join(
            [
                "universe = vanilla",
                f"initialdir = {args.project_root}",
                "executable = chtc/fit_delay_models_full.sh",
                f"arguments = {args.pairs_dir} {args.results_dir} {args.results_dir}/figures",
                "",
                "should_transfer_files = YES",
                "when_to_transfer_output = ON_EXIT",
                "preserve_relative_paths = True",
                "transfer_input_files = scripts/fit_delay_models.py,scripts/pipeline_utils.py,python_deps,"
                + args.pairs_dir,
                f"transfer_output_files = {args.results_dir}",
                "",
                f"output = logs/chtc_fit_delay_full{args.name_suffix}_$(cluster)_$(process).out",
                f"error = logs/chtc_fit_delay_full{args.name_suffix}_$(cluster)_$(process).err",
                f"log = logs/chtc_fit_delay_full{args.name_suffix}_$(cluster).log",
                "",
                "request_cpus = 1",
                f"request_memory = {args.model_memory}",
                f"request_disk = {args.model_disk}",
                "",
                "queue 1",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.chtc_dir.mkdir(parents=True, exist_ok=True)

    raw_files = filtered_raw_files(args, discover_monthly_raw_files())
    if not raw_files:
        raise FileNotFoundError("No monthly raw files were discovered while generating CHTC batch files.")

    write_clean_submit(args, raw_files)
    write_pairs_submit(args)
    write_model_files(args)

    print(f"Wrote {args.chtc_dir / f'clean_all_months{args.name_suffix}.sub'}")
    print(f"Wrote {args.chtc_dir / f'build_pairs_all{args.name_suffix}.sub'}")
    print(f"Wrote {args.chtc_dir / f'fit_delay_models_full{args.name_suffix}.sh'}")
    print(f"Wrote {args.chtc_dir / f'fit_delay_models_full{args.name_suffix}.sub'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
