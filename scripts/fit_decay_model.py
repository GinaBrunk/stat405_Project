#!/usr/bin/env python3
"""Fit a delay decay model across later legs of the same aircraft."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from pipeline_utils import BASE_DIR, ensure_project_dirs, weighted_median


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=BASE_DIR / "processed" / "partitions",
        help="Directory containing part_XXX.csv files",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=BASE_DIR / "results",
        help="Directory for decay outputs",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=BASE_DIR / "results" / "figures",
        help="Directory for figures",
    )
    parser.add_argument("--max-leg", type=int, default=5, help="Maximum later-leg index k")
    parser.add_argument(
        "--shock-threshold",
        type=float,
        default=15.0,
        help="Shock definition threshold on ARR_DELAY",
    )
    return parser.parse_args()


def decay_curve(k: np.ndarray, amplitude: float, decay_rate: float) -> np.ndarray:
    return amplitude * np.exp(-decay_rate * k)


def tail_leg_summary_from_partition(
    path: Path,
    max_leg: int,
    shock_threshold: float,
) -> list[dict[str, float | int | str]]:
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return []
    df["sched_dep_timestamp"] = pd.to_datetime(df["sched_dep_timestamp"], errors="coerce")
    df["ARR_DELAY"] = pd.to_numeric(df["ARR_DELAY"], errors="coerce")
    df["DEP_DELAY"] = pd.to_numeric(df["DEP_DELAY"], errors="coerce")
    df = df.sort_values(["TAIL_NUM", "sched_dep_timestamp"], kind="mergesort").reset_index(drop=True)

    rows: list[dict[str, float | int | str]] = []
    for tail_num, group in df.groupby("TAIL_NUM", sort=False):
        shock_mask = group["ARR_DELAY"] > shock_threshold
        if not shock_mask.any():
            continue
        for leg_index in range(1, max_leg + 1):
            remaining_delay = group["DEP_DELAY"].shift(-leg_index)
            values = remaining_delay.loc[shock_mask].dropna()
            if values.empty:
                continue
            rows.append(
                {
                    "TAIL_NUM": tail_num,
                    "leg_index": leg_index,
                    "n_obs": int(len(values)),
                    "mean_remaining_delay": float(values.mean()),
                    "median_remaining_delay": float(values.median()),
                }
            )
    return rows


def fit_decay_parameters(decay_by_leg: pd.DataFrame) -> tuple[float, float]:
    positive = decay_by_leg.loc[decay_by_leg["mean_remaining_delay"] > 0].copy()
    if len(positive) < 2:
        return float("nan"), float("nan")
    x = positive["leg_index"].to_numpy(dtype=float)
    y = positive["mean_remaining_delay"].to_numpy(dtype=float)
    params, _ = curve_fit(
        decay_curve,
        x,
        y,
        p0=(y[0], 0.25),
        bounds=(0, np.inf),
        maxfev=10_000,
    )
    return float(params[0]), float(params[1])


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    args.figures_dir.mkdir(parents=True, exist_ok=True)

    partition_files = sorted(args.input_dir.glob("part_*.csv"))
    if not partition_files:
        raise FileNotFoundError(f"No partition files found in {args.input_dir}")

    tail_rows: list[dict[str, float | int | str]] = []
    for path in partition_files:
        print(f"Processing {path.name} for decay analysis")
        tail_rows.extend(
            tail_leg_summary_from_partition(path, args.max_leg, args.shock_threshold)
        )

    if not tail_rows:
        raise ValueError("No delayed shock legs were found for the decay analysis.")

    tail_df = pd.DataFrame(tail_rows)
    tail_df.to_csv(args.results_dir / "decay_tail_k_summary.csv", index=False)

    aggregated_rows = []
    for leg_index, group in tail_df.groupby("leg_index", sort=True):
        weights = group["n_obs"].to_numpy(dtype=float)
        means = group["mean_remaining_delay"].to_numpy(dtype=float)
        medians = group["median_remaining_delay"].to_numpy(dtype=float)
        aggregated_rows.append(
            {
                "leg_index": int(leg_index),
                "n_obs": int(weights.sum()),
                "mean_remaining_delay": float(np.average(means, weights=weights)),
                "median_remaining_delay": weighted_median(medians, weights),
            }
        )
    decay_by_leg = pd.DataFrame(aggregated_rows).sort_values("leg_index").reset_index(drop=True)

    amplitude, decay_rate = fit_decay_parameters(decay_by_leg)
    if np.isfinite(amplitude) and np.isfinite(decay_rate):
        decay_by_leg["fitted_decay_value"] = decay_curve(
            decay_by_leg["leg_index"].to_numpy(dtype=float),
            amplitude,
            decay_rate,
        )
    else:
        decay_by_leg["fitted_decay_value"] = np.nan

    decay_by_leg.to_csv(args.results_dir / "decay_by_leg.csv", index=False)

    half_life = float(np.log(2) / decay_rate) if decay_rate > 0 else np.nan
    pd.DataFrame(
        [
            {
                "amplitude_A": amplitude,
                "lambda": decay_rate,
                "half_life_legs": half_life,
                "shock_threshold": args.shock_threshold,
                "max_leg": args.max_leg,
                "delay_measure": "future_departure_delay",
            }
        ]
    ).to_csv(args.results_dir / "decay_model_parameters.csv", index=False)

    plt.figure(figsize=(7, 5))
    plt.plot(
        decay_by_leg["leg_index"],
        decay_by_leg["mean_remaining_delay"],
        marker="o",
        label="Observed mean remaining delay",
    )
    if np.isfinite(decay_rate):
        plt.plot(
            decay_by_leg["leg_index"],
            decay_by_leg["fitted_decay_value"],
            linestyle="--",
            linewidth=2.0,
            label="Fitted exponential decay",
        )
    plt.title("Delay Decay Across Later Legs of the Same Aircraft")
    plt.xlabel("Later-leg index k")
    plt.ylabel("Mean remaining departure delay (minutes)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.figures_dir / "decay_curve.png", dpi=160)
    plt.close()

    print(f"Processed {len(partition_files)} partition files for decay analysis")
    print(f"Estimated decay lambda: {decay_rate:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
