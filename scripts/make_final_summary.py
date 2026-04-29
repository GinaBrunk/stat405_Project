#!/usr/bin/env python3
"""Create concise summary tables for reporting and presentation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline_utils import BASE_DIR, count_csv_rows, ensure_project_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean-dir",
        type=Path,
        default=BASE_DIR / "processed" / "monthly_clean",
        help="Directory containing clean_YYYY_MM.csv files",
    )
    parser.add_argument(
        "--pairs-dir",
        type=Path,
        default=BASE_DIR / "processed" / "pairs",
        help="Directory containing pairs_XXX.csv files",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=BASE_DIR / "results",
        help="Directory containing model outputs",
    )
    parser.add_argument(
        "--chtc-dir",
        type=Path,
        default=BASE_DIR / "chtc",
        help="Directory containing CHTC submit templates",
    )
    return parser.parse_args()


def parse_requested_resource(submit_path: Path, field: str) -> float:
    if not submit_path.exists():
        return np.nan
    text = submit_path.read_text(encoding="utf-8")
    match = re.search(rf"{field}\s*=\s*([0-9.]+)\s*([A-Za-z]+)", text)
    if not match:
        return np.nan
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "gb":
        return value
    if unit == "mb":
        return value / 1024.0
    if unit == "kb":
        return value / (1024.0 * 1024.0)
    return value


def submit_template_for_stage(chtc_dir: Path, stage: str) -> Path | None:
    candidates = {
        "clean": ["clean_all_months.sub", "clean_2024.sub", "clean_one_month.sub"],
        "pairs": ["build_pairs_all.sub", "build_pairs_2024.sub", "build_pairs_one_partition.sub"],
        "modeling": ["fit_delay_models_full.sub", "fit_delay_models_2024.sub"],
    }
    for name in candidates.get(stage, []):
        path = chtc_dir / name
        if path.exists():
            return path
    return None


def parallel_job_summary(
    clean_files: list[Path],
    pair_files: list[Path],
    results_dir: Path,
    chtc_dir: Path,
) -> pd.DataFrame:
    modeling_jobs = 1 if (results_dir / "model_coefficients.csv").exists() else 0
    rows = []
    stage_counts = {
        "clean": len(clean_files),
        "pairs": len(pair_files),
        "modeling": modeling_jobs,
    }
    for stage, job_count in stage_counts.items():
        submit_path = submit_template_for_stage(chtc_dir, stage)
        rows.append(
            {
                "stage": stage,
                "job_count": int(job_count),
                "submit_template": str(submit_path) if submit_path else "",
                "requested_memory_gb": parse_requested_resource(submit_path, "request_memory")
                if submit_path
                else np.nan,
                "requested_disk_gb": parse_requested_resource(submit_path, "request_disk")
                if submit_path
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.results_dir.mkdir(parents=True, exist_ok=True)

    clean_files = sorted(args.clean_dir.glob("clean_*.csv"))
    pair_files = sorted(args.pairs_dir.glob("pairs_*.csv"))

    total_cleaned = sum(count_csv_rows(path) for path in clean_files)
    total_pairs = sum(count_csv_rows(path) for path in pair_files)

    coef_path = args.results_dir / "model_coefficients.csv"
    metrics_path = args.results_dir / "model_metrics.csv"
    main_result_path = args.results_dir / "main_result_table.csv"
    decay_path = args.results_dir / "decay_model_parameters.csv"
    bootstrap_path = args.results_dir / "bootstrap_coefficients.csv"

    coefficients = pd.read_csv(coef_path) if coef_path.exists() else pd.DataFrame()
    metrics = pd.read_csv(metrics_path) if metrics_path.exists() else pd.DataFrame()
    main_result = pd.read_csv(main_result_path) if main_result_path.exists() else pd.DataFrame()
    decay = pd.read_csv(decay_path) if decay_path.exists() else pd.DataFrame()
    bootstrap = pd.read_csv(bootstrap_path) if bootstrap_path.exists() else pd.DataFrame()

    linear_coef = coefficients.loc[
        (coefficients["model"] == "linear") & (coefficients["term"] == "prev_ARR_DELAY"),
        "estimate",
    ]
    logistic_coef = coefficients.loc[
        (coefficients["model"] == "logistic") & (coefficients["term"] == "prev_ARR_DELAY"),
        "estimate",
    ]
    logistic_odds_ratio = coefficients.loc[
        (coefficients["model"] == "logistic") & (coefficients["term"] == "prev_ARR_DELAY"),
        "odds_ratio",
    ]

    beta_ci_lower = beta_ci_upper = np.nan
    if not bootstrap.empty and "beta_prev_arr_delay" in bootstrap:
        beta_ci_lower, beta_ci_upper = np.nanpercentile(
            bootstrap["beta_prev_arr_delay"].dropna(),
            [2.5, 97.5],
        )

    lambda_ci_lower = lambda_ci_upper = np.nan
    if not bootstrap.empty and "lambda_decay" in bootstrap and bootstrap["lambda_decay"].notna().any():
        lambda_ci_lower, lambda_ci_upper = np.nanpercentile(
            bootstrap["lambda_decay"].dropna(),
            [2.5, 97.5],
        )

    decay_lambda = float(decay["lambda"].iloc[0]) if not decay.empty else np.nan
    half_life = float(np.log(2) / decay_lambda) if decay_lambda > 0 else np.nan

    summary = pd.DataFrame(
        [
            {
                "total_raw_files_used": int(len(clean_files)),
                "total_cleaned_flights": int(total_cleaned),
                "total_flight_pairs": int(total_pairs),
                "main_carryover_coefficient": float(linear_coef.iloc[0]) if not linear_coef.empty else np.nan,
                "bootstrap_ci_lower": beta_ci_lower,
                "bootstrap_ci_upper": beta_ci_upper,
                "logistic_prev_delay_coefficient": float(logistic_coef.iloc[0]) if not logistic_coef.empty else np.nan,
                "logistic_prev_delay_odds_ratio": float(logistic_odds_ratio.iloc[0])
                if not logistic_odds_ratio.empty
                else np.nan,
                "logistic_odds_ratio_per_10_min": float(main_result["logistic_odds_ratio_per_10_min"].iloc[0])
                if not main_result.empty
                else np.nan,
                "logistic_or10_ci_lower": float(main_result["logistic_or10_ci_lower"].iloc[0])
                if not main_result.empty
                else np.nan,
                "logistic_or10_ci_upper": float(main_result["logistic_or10_ci_upper"].iloc[0])
                if not main_result.empty
                else np.nan,
                "decay_lambda": decay_lambda,
                "decay_lambda_ci_lower": lambda_ci_lower,
                "decay_lambda_ci_upper": lambda_ci_upper,
                "decay_half_life_legs": half_life,
            }
        ]
    )
    out_path = args.results_dir / "final_summary.csv"
    summary.to_csv(out_path, index=False)

    job_summary = parallel_job_summary(clean_files, pair_files, args.results_dir, args.chtc_dir)
    job_summary.to_csv(args.results_dir / "parallel_job_summary.csv", index=False)

    if not metrics.empty:
        presentation_rows = [
            {
                "metric": "n_modeling_pairs",
                "value": float(main_result["n_modeling_pairs"].iloc[0]) if not main_result.empty else np.nan,
            },
            {
                "metric": "linear_minutes_carried_per_10_min_prev_delay",
                "value": float(main_result["minutes_carried_per_10_min_prev_delay"].iloc[0])
                if not main_result.empty
                else np.nan,
            },
            {
                "metric": "logistic_odds_ratio_per_10_min_prev_delay",
                "value": float(main_result["logistic_odds_ratio_per_10_min"].iloc[0]) if not main_result.empty else np.nan,
            },
            {
                "metric": "logistic_roc_auc",
                "value": float(metrics.loc[metrics["model"] == "logistic", "roc_auc"].iloc[0]),
            },
            {
                "metric": "logistic_average_precision",
                "value": float(metrics.loc[metrics["model"] == "logistic", "average_precision"].iloc[0]),
            },
            {
                "metric": "linear_r_squared",
                "value": float(metrics.loc[metrics["model"] == "linear", "r_squared"].iloc[0]),
            },
        ]
        pd.DataFrame(presentation_rows).to_csv(args.results_dir / "presentation_metrics.csv", index=False)

    print(f"Saved final summary to {out_path}")
    print(f"Saved parallel job summary to {args.results_dir / 'parallel_job_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
