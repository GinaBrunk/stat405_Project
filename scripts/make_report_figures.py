#!/usr/bin/env python3
"""Build a compact, presentation-ready figure pack for the STAT605 report."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yearly-summary",
        type=Path,
        default=Path("results/chtc_pull/yearly_main_summary_2015_2024.csv"),
        help="CSV with per-year main model summary (2015-2024).",
    )
    parser.add_argument(
        "--hetero-dir",
        type=Path,
        default=Path("results/chtc_pull/results_2024_hetero/2024"),
        help="Directory containing 2024 heterogeneity outputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/report_figures"),
        help="Directory where final report figures will be saved.",
    )
    return parser.parse_args()


def copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Missing required source figure: {src}")
    shutil.copy2(src, dst)


def plot_or10_trend(summary: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    years = summary["year"]
    ax.plot(years, summary["logistic_or_per_10min"], marker="o", linewidth=2.0, color="#1f77b4")
    ax.fill_between(
        years,
        summary["logistic_or10_ci_lower"],
        summary["logistic_or10_ci_upper"],
        color="#1f77b4",
        alpha=0.2,
    )
    ax.axhline(1.0, linestyle="--", linewidth=1.2, color="black")
    ax.set_title("Yearly Carry-Over Odds Ratio per 10-Min Previous Arrival Delay")
    ax.set_xlabel("Year")
    ax.set_ylabel("Odds ratio (current departure delay > 15 min)")
    ax.set_xticks(years)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_linear_trend(summary: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    years = summary["year"]
    ax.plot(
        years,
        summary["minutes_carried_per_10min"],
        marker="o",
        linewidth=2.0,
        color="#d62728",
    )
    ax.set_title("Yearly Delay Carry-Over in Minutes (Linear Model)")
    ax.set_xlabel("Year")
    ax.set_ylabel("Minutes carried to next departure per 10-min previous arrival delay")
    ax.set_xticks(years)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_pairs_by_year(summary: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    years = summary["year"].astype(str)
    pairs_million = summary["n_modeling_pairs"] / 1_000_000.0
    ax.bar(years, pairs_million, color="#2ca02c")
    ax.set_title("Modeling Pair Count by Year")
    ax.set_xlabel("Year")
    ax.set_ylabel("Pairs (millions)")
    for idx, value in enumerate(pairs_million):
        ax.text(idx, value + 0.03, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def plot_airline_top_bottom(airline_df: pd.DataFrame, out_path: Path) -> None:
    plot_df = airline_df.sort_values("odds_ratio_per_10_min", ascending=False)
    top = plot_df.head(6)
    bottom = plot_df.tail(6)
    merged = pd.concat([top, bottom], ignore_index=True)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(merged["airline"], merged["odds_ratio_per_10_min"], color="#9467bd")
    ax.errorbar(
        merged["airline"],
        merged["odds_ratio_per_10_min"],
        yerr=[
            merged["odds_ratio_per_10_min"] - merged["or10_ci_lower"],
            merged["or10_ci_upper"] - merged["odds_ratio_per_10_min"],
        ],
        fmt="none",
        ecolor="black",
        elinewidth=1,
        capsize=3,
    )
    ax.axhline(1.0, linestyle="--", linewidth=1.2, color="black")
    ax.set_title("2024 Airline Heterogeneity (Top/Bottom Carry-Over)")
    ax.set_xlabel("Airline")
    ax.set_ylabel("Odds ratio per 10-min previous arrival delay")
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def _draw_flow_box(ax, x: float, y: float, text: str, facecolor: str) -> None:
    width = 0.21
    height = 0.22
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.03",
        linewidth=1.5,
        edgecolor="#333333",
        facecolor=facecolor,
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=12)


def plot_pipeline_flow(summary: pd.DataFrame, out_path: Path) -> None:
    n_years = int(summary["year"].nunique())
    raw_files = n_years * 12
    cleaning_jobs = raw_files
    tail_partitions = 100
    pair_jobs = 100
    model_jobs = n_years + 1  # yearly models + 2024 heterogeneity job

    fig, ax = plt.subplots(figsize=(13.5, 4.2))
    ax.set_xlim(0, 1.13)
    ax.set_ylim(0, 1)
    ax.axis("off")

    _draw_flow_box(ax, 0.03, 0.40, f"Raw monthly files\n{raw_files} files", "#DCEAF7")
    _draw_flow_box(ax, 0.30, 0.40, f"Cleaning jobs\n{cleaning_jobs} jobs", "#FDE2CF")
    _draw_flow_box(ax, 0.57, 0.40, f"Tail partitions\n{tail_partitions} buckets", "#D9F0D3")
    _draw_flow_box(ax, 0.84, 0.40, f"Pair jobs + models\n{pair_jobs} + {model_jobs} jobs", "#F7D8E6")

    arrow_y = 0.51
    for start_x in [0.245, 0.515, 0.785]:
        ax.annotate(
            "",
            xy=(start_x + 0.05, arrow_y),
            xytext=(start_x, arrow_y),
            arrowprops=dict(arrowstyle="->", linewidth=2.4, color="#555555"),
        )

    ax.set_title("Parallel Flight-Delay Pipeline (2015-2024 Production Run)", fontsize=15)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170)
    plt.close(fig)


def write_index(output_dir: Path) -> None:
    lines = [
        "# Report Figure Pack",
        "",
        "1. `fig01_delay_rate_by_prev_delay_bin_2024.png`",
        "2. `fig02_carryover_by_airline_2024.png`",
        "3. `fig03_carryover_by_turnaround_bin_2024.png`",
        "4. `fig04_pipeline_parallel_flow.png`",
        "5. `fig05_prev_arr_delay_vs_current_dep_delay_2024.png`",
        "6. `fig06_yearly_or10_trend_2015_2024.png`",
        "7. `fig07_yearly_linear_minutes_trend_2015_2024.png`",
        "8. `fig08_pairs_by_year_2015_2024.png`",
        "9. `fig09_airline_top_bottom_2024.png`",
        "",
        "Generated by `scripts/make_report_figures.py`.",
    ]
    (output_dir / "figure_index.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    yearly = pd.read_csv(args.yearly_summary).sort_values("year")
    airline_df = pd.read_csv(args.hetero_dir / "airline_carryover_summary.csv")

    figures_2024 = args.hetero_dir / "figures"
    copy_if_exists(figures_2024 / "delay_rate_by_prev_delay_bin.png", output_dir / "fig01_delay_rate_by_prev_delay_bin_2024.png")
    copy_if_exists(figures_2024 / "carryover_by_airline.png", output_dir / "fig02_carryover_by_airline_2024.png")
    copy_if_exists(figures_2024 / "carryover_by_turnaround_bin.png", output_dir / "fig03_carryover_by_turnaround_bin_2024.png")
    copy_if_exists(figures_2024 / "prev_arr_delay_vs_current_dep_delay.png", output_dir / "fig05_prev_arr_delay_vs_current_dep_delay_2024.png")

    plot_pipeline_flow(yearly, output_dir / "fig04_pipeline_parallel_flow.png")
    plot_or10_trend(yearly, output_dir / "fig06_yearly_or10_trend_2015_2024.png")
    plot_linear_trend(yearly, output_dir / "fig07_yearly_linear_minutes_trend_2015_2024.png")
    plot_pairs_by_year(yearly, output_dir / "fig08_pairs_by_year_2015_2024.png")
    plot_airline_top_bottom(airline_df, output_dir / "fig09_airline_top_bottom_2024.png")
    write_index(output_dir)

    print(f"Wrote report figure pack to: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
