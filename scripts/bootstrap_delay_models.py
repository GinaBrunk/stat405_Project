#!/usr/bin/env python3
"""Cluster-bootstrap uncertainty for the main carry-over coefficient and decay rate."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm

from fit_decay_model import fit_decay_parameters
from pipeline_utils import BASE_DIR, ensure_project_dirs


LINEAR_FORMULA = (
    "current_DEP_DELAY ~ prev_ARR_DELAY + scheduled_turnaround_minutes + "
    "current_sched_dep_hour + current_DISTANCE + C(OP_UNIQUE_CARRIER) + "
    "C(current_year) + C(current_month) + C(current_day_of_week) + C(dep_period)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        help="Directory for reading/writing bootstrap-related outputs",
    )
    parser.add_argument("--n-reps", type=int, required=True, help="Number of bootstrap replications")
    parser.add_argument("--seed", type=int, required=True, help="Random seed")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output CSV path, e.g. results/bootstrap_coefficients.csv",
    )
    return parser.parse_args()


def load_pairs(pairs_dir: Path) -> pd.DataFrame:
    frames = [pd.read_csv(path, low_memory=False) for path in sorted(pairs_dir.glob("pairs_*.csv"))]
    if not frames:
        raise FileNotFoundError(f"No pair files found in {pairs_dir}")
    df = pd.concat(frames, ignore_index=True)
    keep = [
        "TAIL_NUM",
        "current_FL_DATE",
        "current_DEP_DELAY",
        "prev_ARR_DELAY",
        "scheduled_turnaround_minutes",
        "current_sched_dep_hour",
        "current_DISTANCE",
        "OP_UNIQUE_CARRIER",
    ]
    df = df[keep].copy()
    for column in keep:
        if column not in {"TAIL_NUM", "OP_UNIQUE_CARRIER", "current_FL_DATE"}:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["current_year"] = pd.to_datetime(df["current_FL_DATE"], errors="coerce").dt.year
    dt = pd.to_datetime(df["current_FL_DATE"], errors="coerce")
    df["current_month"] = dt.dt.month
    df["current_day_of_week"] = dt.dt.dayofweek + 1
    hour = pd.to_numeric(df["current_sched_dep_hour"], errors="coerce")
    df["dep_period"] = pd.Series(pd.NA, index=df.index, dtype="string")
    df.loc[hour.between(0, 5, inclusive="both"), "dep_period"] = "overnight"
    df.loc[hour.between(6, 11, inclusive="both"), "dep_period"] = "morning"
    df.loc[hour.between(12, 17, inclusive="both"), "dep_period"] = "afternoon"
    df.loc[hour.between(18, 23, inclusive="both"), "dep_period"] = "evening"
    df = df.dropna()
    return df


def load_decay_tail_summary(results_dir: Path) -> pd.DataFrame | None:
    path = results_dir / "decay_tail_k_summary.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, low_memory=False)
    df["n_obs"] = pd.to_numeric(df["n_obs"], errors="coerce")
    df["mean_remaining_delay"] = pd.to_numeric(df["mean_remaining_delay"], errors="coerce")
    return df.dropna(subset=["TAIL_NUM", "leg_index", "n_obs", "mean_remaining_delay"])


def bootstrap_decay_lambda(tail_summary: pd.DataFrame, sampled_counts: pd.Series) -> float:
    merged = tail_summary.merge(
        sampled_counts.rename("bootstrap_count"),
        left_on="TAIL_NUM",
        right_index=True,
        how="inner",
    )
    if merged.empty:
        return float("nan")
    merged["weight"] = merged["n_obs"] * merged["bootstrap_count"]
    aggregated = (
        merged.groupby("leg_index", as_index=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n_obs": g["weight"].sum(),
                    "mean_remaining_delay": np.average(
                        g["mean_remaining_delay"], weights=g["weight"]
                    ),
                }
            )
        )
        .reset_index(drop=True)
    )
    amplitude, decay_rate = fit_decay_parameters(aggregated)
    return decay_rate


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    pair_df = load_pairs(args.pairs_dir)
    y, X = patsy.dmatrices(LINEAR_FORMULA, pair_df, return_type="dataframe")
    tail_series = pair_df["TAIL_NUM"].astype("string")
    unique_tails = tail_series.dropna().unique()
    if len(unique_tails) == 0:
        raise ValueError("No non-missing tail numbers are available for the cluster bootstrap.")

    decay_tail_summary = load_decay_tail_summary(args.results_dir)
    rng = np.random.default_rng(args.seed)
    rows: list[dict[str, float | int]] = []

    for replicate in range(args.n_reps):
        sampled_tails = rng.choice(unique_tails, size=len(unique_tails), replace=True)
        sampled_counts = pd.Series(sampled_tails).value_counts()
        row_weights = tail_series.map(sampled_counts).fillna(0.0).to_numpy(dtype=float)
        active = row_weights > 0
        glm = sm.GLM(
            y.loc[active],
            X.loc[active],
            family=sm.families.Gaussian(),
            freq_weights=row_weights[active],
        ).fit()
        row = {
            "replicate": int(replicate),
            "seed": int(args.seed),
            "beta_prev_arr_delay": float(glm.params["prev_ARR_DELAY"]),
        }
        if decay_tail_summary is not None:
            row["lambda_decay"] = float(bootstrap_decay_lambda(decay_tail_summary, sampled_counts))
        rows.append(row)

    pd.DataFrame(rows).to_csv(args.output, index=False)
    print(f"Saved {args.n_reps} bootstrap replicates to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
