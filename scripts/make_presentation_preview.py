#!/usr/bin/env python3
"""Create a quick 2024 vs 2025 presentation preview from model outputs."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from pipeline_utils import BASE_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-root",
        type=Path,
        default=BASE_DIR / "results" / "year_compare",
        help="Directory containing results_2024 and results_2025 folders",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "results" / "year_compare" / "preview",
        help="Directory for preview outputs",
    )
    return parser.parse_args()


def load_year_main_summary(results_dir: Path, year: int) -> dict[str, float | int]:
    coef_path = results_dir / f"results_{year}" / "model_coefficients.csv"
    metrics_path = results_dir / f"results_{year}" / "model_metrics.csv"
    if not coef_path.exists() or not metrics_path.exists():
        raise FileNotFoundError(f"Missing model outputs for {year} under {results_dir}")

    coefs = pd.read_csv(coef_path)
    metrics = pd.read_csv(metrics_path)

    linear_coef = float(
        coefs.loc[(coefs["model"] == "linear") & (coefs["term"] == "prev_ARR_DELAY"), "estimate"].iloc[0]
    )
    logistic_coef = float(
        coefs.loc[(coefs["model"] == "logistic") & (coefs["term"] == "prev_ARR_DELAY"), "estimate"].iloc[0]
    )
    logistic_metrics = metrics.loc[metrics["model"] == "logistic"].iloc[0]
    linear_metrics = metrics.loc[metrics["model"] == "linear"].iloc[0]

    return {
        "year": int(year),
        "n_modeling_pairs": int(round(float(logistic_metrics["n_obs"]))),
        "linear_coef": linear_coef,
        "minutes_carried_per_10_min": 10.0 * linear_coef,
        "linear_r_squared": float(linear_metrics["r_squared"]),
        "logistic_coef": logistic_coef,
        "logistic_or_per_10_min": math.exp(10.0 * logistic_coef),
        "logistic_auc": float(logistic_metrics["roc_auc"]),
        "logistic_average_precision": float(logistic_metrics["average_precision"]),
        "current_delay_rate_gt15": float(logistic_metrics["mean_target"]),
    }


def make_main_compare_figure(df: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))

    axes[0].bar(df["year"].astype(str), df["logistic_or_per_10_min"], color=["#4C78A8", "#F58518"])
    axes[0].axhline(1.0, color="black", linestyle="--", linewidth=1.0)
    axes[0].set_title("Odds Ratio per 10-Min Previous Arrival Delay")
    axes[0].set_ylabel("Odds ratio for departure delay > 15 min")

    axes[1].bar(df["year"].astype(str), df["minutes_carried_per_10_min"], color=["#54A24B", "#E45756"])
    axes[1].set_title("Minutes Carried to Next Departure")
    axes[1].set_ylabel("Extra departure delay per 10 min previous arrival delay")

    for ax in axes:
        ax.tick_params(labelsize=11)
        ax.set_xlabel("Year")

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def make_heterogeneity_figure(summary_df: pd.DataFrame, x_col: str, title: str, out_path: Path) -> None:
    plot_df = summary_df.copy()
    plt.figure(figsize=(9, 5))
    plt.bar(plot_df[x_col], plot_df["odds_ratio_per_10_min"], color="#4C78A8")
    plt.errorbar(
        plot_df[x_col],
        plot_df["odds_ratio_per_10_min"],
        yerr=[
            plot_df["odds_ratio_per_10_min"] - plot_df["or10_ci_lower"],
            plot_df["or10_ci_upper"] - plot_df["odds_ratio_per_10_min"],
        ],
        fmt="none",
        ecolor="black",
        capsize=3,
        linewidth=1.0,
    )
    plt.axhline(1.0, color="black", linestyle="--", linewidth=1.0)
    plt.title(title)
    plt.ylabel("Odds ratio per 10-min previous arrival delay")
    plt.xticks(rotation=30 if x_col == "airline" else 0, ha="right" if x_col == "airline" else "center")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()


def write_preview_notes(main_df: pd.DataFrame, output_path: Path) -> None:
    y2024 = main_df.loc[main_df["year"] == 2024].iloc[0]
    y2025 = main_df.loc[main_df["year"] == 2025].iloc[0]
    text = f"""# 2024 vs 2025 Preview

- `2024` modeled pairs: `{y2024['n_modeling_pairs']:,}`
- `2025` modeled pairs: `{y2025['n_modeling_pairs']:,}`
- `2024` logistic odds ratio per 10 minutes: `{y2024['logistic_or_per_10_min']:.3f}`
- `2025` logistic odds ratio per 10 minutes: `{y2025['logistic_or_per_10_min']:.3f}`
- `2024` linear carry-over per 10 minutes: `{y2024['minutes_carried_per_10_min']:.2f}` minutes
- `2025` linear carry-over per 10 minutes: `{y2025['minutes_carried_per_10_min']:.2f}` minutes
- `2024` logistic AUC: `{y2024['logistic_auc']:.3f}`
- `2025` logistic AUC: `{y2025['logistic_auc']:.3f}`

## Quick read

The main 2024 and 2025 carry-over estimates are very similar. In both years, a 10-minute previous arrival delay is associated with roughly a 39% to 41% increase in the odds of a next-flight departure delay above 15 minutes, and about 5.2 to 5.3 minutes of carry-over into the next departure.

For presentation, the strongest operational story remains:

1. The carry-over effect is stable across two full years.
2. The binary delayed/not-delayed model is easier to explain than the linear fit.
3. Short turnaround buffers amplify delay propagation much more than long buffers.
"""
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    main_rows = [
        load_year_main_summary(args.input_root, 2024),
        load_year_main_summary(args.input_root, 2025),
    ]
    main_df = pd.DataFrame(main_rows)
    main_df.to_csv(args.output_dir / "year_main_comparison.csv", index=False)

    make_main_compare_figure(main_df, args.output_dir / "main_effect_compare_2024_2025.png")

    airline_path = args.input_root / "results_2025" / "airline_carryover_summary.csv"
    if airline_path.exists():
        airline_df = pd.read_csv(airline_path).sort_values("odds_ratio_per_10_min", ascending=False)
        airline_df.to_csv(args.output_dir / "airline_carryover_2025_ranked.csv", index=False)
        make_heterogeneity_figure(
            airline_df.head(10),
            "airline",
            "2025 Airline Carry-Over Strength",
            args.output_dir / "airline_carryover_2025_top10.png",
        )

    turnaround_path = args.input_root / "results_2025" / "turnaround_carryover_summary.csv"
    if turnaround_path.exists():
        turnaround_df = pd.read_csv(turnaround_path)
        turnaround_df.to_csv(args.output_dir / "turnaround_carryover_2025.csv", index=False)
        make_heterogeneity_figure(
            turnaround_df,
            "turnaround_bin",
            "2025 Carry-Over by Turnaround Bin",
            args.output_dir / "turnaround_carryover_2025.png",
        )

    write_preview_notes(main_df, args.output_dir / "preview_notes.md")
    print(f"Saved preview outputs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
