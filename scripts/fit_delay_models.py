#!/usr/bin/env python3
"""Fit pooled and heterogeneous delay propagation models and produce figures."""

from __future__ import annotations

import argparse
import gc
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from matplotlib.patches import FancyBboxPatch
from sklearn.metrics import average_precision_score, roc_auc_score

from pipeline_utils import BASE_DIR, discover_monthly_raw_files, ensure_project_dirs


TURNAROUND_BINS: list[tuple[float, float, str]] = [
    (20.0, 45.0, "20-44"),
    (45.0, 90.0, "45-89"),
    (90.0, 180.0, "90-179"),
    (180.0, 601.0, "180-600"),
]
TURNAROUND_LABELS = [label for _, _, label in TURNAROUND_BINS]
DEP_PERIOD_LABELS = ["overnight", "morning", "afternoon", "evening"]

MODEL_USECOLS = [
    "current_FL_DATE",
    "OP_UNIQUE_CARRIER",
    "current_sched_dep_hour",
    "current_DEP_DELAY",
    "current_DISTANCE",
    "prev_ARR_DELAY",
    "scheduled_turnaround_minutes",
    "current_dep_delayed_15",
]

def build_formulas(include_year_effect: bool) -> dict[str, str]:
    controls = [
        "scheduled_turnaround_minutes",
        "current_sched_dep_hour",
        "current_DISTANCE",
        "C(current_month)",
        "C(current_day_of_week)",
        "C(dep_period)",
    ]
    if include_year_effect:
        controls.append("C(current_year)")

    linear_formula = (
        "current_DEP_DELAY ~ prev_ARR_DELAY + C(OP_UNIQUE_CARRIER) + " + " + ".join(controls)
    )
    logistic_formula = (
        "current_dep_delayed_15 ~ prev_ARR_DELAY + C(OP_UNIQUE_CARRIER) + " + " + ".join(controls)
    )
    logistic_airline_formula = (
        "current_dep_delayed_15 ~ prev_ARR_DELAY * C(OP_UNIQUE_CARRIER) + " + " + ".join(controls)
    )
    turnaround_controls = ["C(OP_UNIQUE_CARRIER)", *controls]
    logistic_turnaround_formula = (
        "current_dep_delayed_15 ~ prev_ARR_DELAY * C(turnaround_bin) + " + " + ".join(turnaround_controls)
    )
    return {
        "linear": linear_formula,
        "logistic": logistic_formula,
        "logistic_airline": logistic_airline_formula,
        "logistic_turnaround": logistic_turnaround_formula,
    }


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
        help="Directory for result tables",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=BASE_DIR / "results" / "figures",
        help="Directory for figures",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50_000,
        help="Maximum number of rows to plot in the hexbin figure",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Optional inclusive lower bound for current_FL_DATE year",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Optional inclusive upper bound for current_FL_DATE year",
    )
    parser.add_argument(
        "--read-chunksize",
        type=int,
        default=500_000,
        help="Chunk size used while reading pair files",
    )
    parser.add_argument(
        "--skip-heterogeneity",
        action="store_true",
        help="Skip airline and turnaround interaction models (lower memory use)",
    )
    return parser.parse_args()


def turnaround_bin_series(values: pd.Series) -> pd.Series:
    data = pd.to_numeric(values, errors="coerce")
    result = pd.Series(pd.NA, index=values.index, dtype="string")
    for lower, upper, label in TURNAROUND_BINS:
        mask = data.ge(lower) & data.lt(upper)
        if label == "180-600":
            mask = data.ge(lower) & data.le(600)
        result.loc[mask] = label
    return pd.Categorical(result, categories=TURNAROUND_LABELS, ordered=True)


def dep_period_series(values: pd.Series) -> pd.Series:
    hours = pd.to_numeric(values, errors="coerce")
    result = pd.Series(pd.NA, index=values.index, dtype="string")
    result.loc[hours.between(0, 5, inclusive="both")] = "overnight"
    result.loc[hours.between(6, 11, inclusive="both")] = "morning"
    result.loc[hours.between(12, 17, inclusive="both")] = "afternoon"
    result.loc[hours.between(18, 23, inclusive="both")] = "evening"
    return pd.Categorical(result, categories=DEP_PERIOD_LABELS, ordered=True)


def load_pair_data(
    pairs_dir: Path,
    start_year: int | None = None,
    end_year: int | None = None,
    read_chunksize: int = 500_000,
) -> pd.DataFrame:
    pair_files = sorted(pairs_dir.glob("pairs_*.csv"))
    if not pair_files:
        raise FileNotFoundError(f"No pair files found in {pairs_dir}")

    frames: list[pd.DataFrame] = []
    dtypes = {
        "OP_UNIQUE_CARRIER": "string",
        "current_FL_DATE": "string",
        "current_sched_dep_hour": "float32",
        "current_DEP_DELAY": "float32",
        "current_DISTANCE": "float32",
        "prev_ARR_DELAY": "float32",
        "scheduled_turnaround_minutes": "float32",
        "current_dep_delayed_15": "float32",
    }
    for path in pair_files:
        for chunk in pd.read_csv(
            path,
            usecols=MODEL_USECOLS,
            dtype=dtypes,
            chunksize=read_chunksize,
            low_memory=False,
        ):
            if start_year is not None or end_year is not None:
                year_part = pd.to_numeric(chunk["current_FL_DATE"].str.slice(0, 4), errors="coerce")
                mask = pd.Series(True, index=chunk.index)
                if start_year is not None:
                    mask &= year_part.ge(start_year)
                if end_year is not None:
                    mask &= year_part.le(end_year)
                chunk = chunk.loc[mask]
            if not chunk.empty:
                frames.append(chunk)
    if not frames:
        scope = f" for years [{start_year}, {end_year}]" if start_year or end_year else ""
        raise ValueError(f"Pair data are empty{scope}; cannot fit delay models.")
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        scope = f" for years [{start_year}, {end_year}]" if start_year or end_year else ""
        raise ValueError(f"Pair data are empty{scope}; cannot fit delay models.")
    return df


def model_dataframe(pair_df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "current_DEP_DELAY",
        "prev_ARR_DELAY",
        "scheduled_turnaround_minutes",
        "current_sched_dep_hour",
        "current_DISTANCE",
        "current_dep_delayed_15",
    ]
    for column in numeric_cols:
        pair_df[column] = pd.to_numeric(pair_df[column], errors="coerce")

    current_dates = pd.to_datetime(pair_df["current_FL_DATE"], errors="coerce")
    pair_df["current_year"] = current_dates.dt.year.astype("Int64")
    pair_df["current_month"] = current_dates.dt.month.astype("Int64")
    pair_df["current_day_of_week"] = (current_dates.dt.dayofweek + 1).astype("Int64")
    pair_df["turnaround_bin"] = turnaround_bin_series(pair_df["scheduled_turnaround_minutes"])
    pair_df["dep_period"] = dep_period_series(pair_df["current_sched_dep_hour"])

    df = pair_df.dropna(
        subset=[
            "current_DEP_DELAY",
            "prev_ARR_DELAY",
            "scheduled_turnaround_minutes",
            "current_sched_dep_hour",
            "current_DISTANCE",
            "OP_UNIQUE_CARRIER",
            "current_dep_delayed_15",
            "current_year",
            "current_month",
            "current_day_of_week",
            "turnaround_bin",
            "dep_period",
        ]
    ).copy()
    df["current_year"] = df["current_year"].astype(int).astype("category")
    df["current_month"] = df["current_month"].astype(int).astype("category")
    df["current_day_of_week"] = df["current_day_of_week"].astype(int).astype("category")
    df["OP_UNIQUE_CARRIER"] = df["OP_UNIQUE_CARRIER"].astype("category")
    df["current_dep_delayed_15"] = df["current_dep_delayed_15"].astype("int8")
    if "current_FL_DATE" in df.columns:
        df = df.drop(columns=["current_FL_DATE"])
    if len(df) < 100:
        raise ValueError(f"Only {len(df)} usable pairs remain after filtering; too few to fit models.")
    return df


def coefficients_frame(model_name: str, result) -> pd.DataFrame:
    conf_int = result.conf_int()
    rows = []
    for term in result.params.index:
        rows.append(
            {
                "model": model_name,
                "term": term,
                "estimate": float(result.params[term]),
                "std_err": float(result.bse[term]),
                "ci_lower": float(conf_int.loc[term, 0]),
                "ci_upper": float(conf_int.loc[term, 1]),
                "p_value": float(result.pvalues[term]),
                "odds_ratio": float(np.exp(result.params[term])) if model_name.startswith("logistic") else np.nan,
                "odds_ratio_per_10": float(np.exp(10.0 * result.params[term]))
                if model_name.startswith("logistic")
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def linear_metrics(result, df: pd.DataFrame) -> dict[str, float]:
    return {
        "model": "linear",
        "n_obs": float(result.nobs),
        "r_squared": float(result.rsquared),
        "adj_r_squared": float(result.rsquared_adj),
        "aic": float(result.aic),
        "bic": float(result.bic),
        "mean_target": float(df["current_DEP_DELAY"].mean()),
    }


def logistic_metrics(result, df: pd.DataFrame) -> dict[str, float]:
    y_true = df["current_dep_delayed_15"].astype(int)
    y_score = result.predict(df)
    try:
        roc_auc = float(roc_auc_score(y_true, y_score))
    except ValueError:
        roc_auc = float("nan")
    try:
        avg_precision = float(average_precision_score(y_true, y_score))
    except ValueError:
        avg_precision = float("nan")
    return {
        "model": "logistic",
        "n_obs": float(result.nobs),
        "aic": float(result.aic),
        "deviance": float(result.deviance),
        "null_deviance": float(result.null_deviance),
        "roc_auc": roc_auc,
        "average_precision": avg_precision,
        "mean_target": float(y_true.mean()),
    }


def main_result_table(
    n_obs: int,
    linear_coef: float,
    linear_ci: tuple[float, float],
    logistic_coef: float,
    logistic_ci: tuple[float, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pooled = pd.DataFrame(
        [
            {
                "n_modeling_pairs": int(n_obs),
                "logistic_prev_arr_delay_coef": float(logistic_coef),
                "logistic_ci_lower": float(logistic_ci[0]),
                "logistic_ci_upper": float(logistic_ci[1]),
                "logistic_odds_ratio_per_1_min": float(np.exp(logistic_coef)),
                "logistic_odds_ratio_per_10_min": float(np.exp(10.0 * logistic_coef)),
                "logistic_or10_ci_lower": float(np.exp(10.0 * logistic_ci[0])),
                "logistic_or10_ci_upper": float(np.exp(10.0 * logistic_ci[1])),
                "linear_prev_arr_delay_coef": float(linear_coef),
                "linear_ci_lower": float(linear_ci[0]),
                "linear_ci_upper": float(linear_ci[1]),
                "minutes_carried_per_10_min_prev_delay": float(10.0 * linear_coef),
            }
        ]
    )

    secondary = pd.DataFrame(
        [
            {
                "linear_prev_arr_delay_coef": float(linear_coef),
                "linear_ci_lower": float(linear_ci[0]),
                "linear_ci_upper": float(linear_ci[1]),
                "minutes_carried_per_10_min_prev_delay": float(10.0 * linear_coef),
            }
        ]
    )
    return pooled, secondary


def contrast_summary(result, terms: dict[str, float]) -> tuple[float, float, float, float]:
    params = result.params
    covariance = result.cov_params()
    weights = pd.Series(0.0, index=params.index, dtype="float64")
    for term, value in terms.items():
        if term in weights.index:
            weights.loc[term] = value
    estimate = float(np.dot(weights, params))
    variance = float(weights.to_numpy() @ covariance.to_numpy() @ weights.to_numpy())
    std_err = float(np.sqrt(max(variance, 0.0)))
    ci_lower = estimate - 1.96 * std_err
    ci_upper = estimate + 1.96 * std_err
    return estimate, std_err, ci_lower, ci_upper


def heterogeneity_airline_table(result, df: pd.DataFrame) -> pd.DataFrame:
    airlines = list(df["OP_UNIQUE_CARRIER"].cat.categories)
    rows = []
    for airline in airlines:
        terms = {"prev_ARR_DELAY": 1.0}
        interaction_term = f"prev_ARR_DELAY:C(OP_UNIQUE_CARRIER)[T.{airline}]"
        if interaction_term in result.params.index:
            terms[interaction_term] = 1.0
        estimate, std_err, ci_lower, ci_upper = contrast_summary(result, terms)
        rows.append(
            {
                "airline": airline,
                "carryover_log_odds_per_1_min": estimate,
                "std_err": std_err,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "odds_ratio_per_10_min": float(np.exp(10.0 * estimate)),
                "or10_ci_lower": float(np.exp(10.0 * ci_lower)),
                "or10_ci_upper": float(np.exp(10.0 * ci_upper)),
                "n_obs": int((df["OP_UNIQUE_CARRIER"] == airline).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("odds_ratio_per_10_min", ascending=False)


def heterogeneity_turnaround_table(result, df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label in TURNAROUND_LABELS:
        terms = {"prev_ARR_DELAY": 1.0}
        interaction_term = f"prev_ARR_DELAY:C(turnaround_bin)[T.{label}]"
        if interaction_term in result.params.index:
            terms[interaction_term] = 1.0
        estimate, std_err, ci_lower, ci_upper = contrast_summary(result, terms)
        rows.append(
            {
                "turnaround_bin": label,
                "carryover_log_odds_per_1_min": estimate,
                "std_err": std_err,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "odds_ratio_per_10_min": float(np.exp(10.0 * estimate)),
                "or10_ci_lower": float(np.exp(10.0 * ci_lower)),
                "or10_ci_upper": float(np.exp(10.0 * ci_upper)),
                "n_obs": int((df["turnaround_bin"].astype("string") == label).sum()),
            }
        )
    return pd.DataFrame(rows)


def make_prev_arrival_plot(
    df: pd.DataFrame,
    intercept: float,
    slope: float,
    out_path: Path,
    sample_size: int,
) -> None:
    sample = df.sample(min(len(df), sample_size), random_state=42)
    plt.figure(figsize=(8, 5))
    plt.hexbin(
        sample["prev_ARR_DELAY"],
        sample["current_DEP_DELAY"],
        gridsize=45,
        cmap="viridis",
        mincnt=1,
    )
    x_vals = np.linspace(sample["prev_ARR_DELAY"].quantile(0.01), sample["prev_ARR_DELAY"].quantile(0.99), 200)
    plt.plot(x_vals, intercept + slope * x_vals, color="crimson", linewidth=2.0)
    plt.colorbar(label="Observation density")
    plt.title("Previous Arrival Delay vs Current Departure Delay")
    plt.xlabel("Previous arrival delay (minutes)")
    plt.ylabel("Current departure delay (minutes)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def make_delay_rate_plot(df: pd.DataFrame, out_path: Path) -> None:
    bins = [-120, -60, -30, -15, -5, 0, 5, 15, 30, 60, 120, 240, 480]
    labels = [f"{bins[i]} to {bins[i + 1]}" for i in range(len(bins) - 1)]
    plot_df = df.copy()
    plot_df["prev_delay_bin"] = pd.cut(plot_df["prev_ARR_DELAY"], bins=bins, labels=labels, include_lowest=True)
    summary = (
        plot_df.groupby("prev_delay_bin", observed=True)["current_dep_delayed_15"]
        .mean()
        .reset_index(name="delay_rate")
    )
    plt.figure(figsize=(9, 5))
    plt.bar(summary["prev_delay_bin"].astype(str), summary["delay_rate"], color="#4C78A8")
    plt.xticks(rotation=45, ha="right")
    plt.title("Current >15-Min Departure Delay Rate by Previous Arrival Delay Bin")
    plt.xlabel("Previous arrival delay bin (minutes)")
    plt.ylabel("Share of flights with departure delay > 15 min")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def make_airline_plot(summary_df: pd.DataFrame, out_path: Path) -> None:
    plot_df = summary_df.sort_values("odds_ratio_per_10_min", ascending=False)
    plt.figure(figsize=(9, 5))
    plt.bar(plot_df["airline"], plot_df["odds_ratio_per_10_min"], color="#F58518")
    plt.errorbar(
        plot_df["airline"],
        plot_df["odds_ratio_per_10_min"],
        yerr=[
            plot_df["odds_ratio_per_10_min"] - plot_df["or10_ci_lower"],
            plot_df["or10_ci_upper"] - plot_df["odds_ratio_per_10_min"],
        ],
        fmt="none",
        ecolor="black",
        elinewidth=1,
        capsize=3,
    )
    plt.axhline(1.0, color="black", linestyle="--", linewidth=1.0)
    plt.title("Odds Ratio per 10-Min Previous Arrival Delay, by Airline")
    plt.xlabel("Airline")
    plt.ylabel("Odds ratio for current departure delay > 15 min")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def make_turnaround_plot(summary_df: pd.DataFrame, out_path: Path) -> None:
    plot_df = summary_df.copy()
    plt.figure(figsize=(8, 5))
    plt.bar(plot_df["turnaround_bin"], plot_df["odds_ratio_per_10_min"], color="#54A24B")
    plt.errorbar(
        plot_df["turnaround_bin"],
        plot_df["odds_ratio_per_10_min"],
        yerr=[
            plot_df["odds_ratio_per_10_min"] - plot_df["or10_ci_lower"],
            plot_df["or10_ci_upper"] - plot_df["odds_ratio_per_10_min"],
        ],
        fmt="none",
        ecolor="black",
        elinewidth=1,
        capsize=3,
    )
    plt.axhline(1.0, color="black", linestyle="--", linewidth=1.0)
    plt.title("Odds Ratio per 10-Min Previous Arrival Delay, by Turnaround Bin")
    plt.xlabel("Scheduled turnaround (minutes)")
    plt.ylabel("Odds ratio for current departure delay > 15 min")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()


def add_flow_box(ax, x: float, y: float, text: str, facecolor: str) -> None:
    width = 0.2
    height = 0.18
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.5,
        edgecolor="#333333",
        facecolor=facecolor,
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=11)


def make_pipeline_flow_figure(pairs_dir: Path, out_path: Path) -> None:
    raw_count = len(discover_monthly_raw_files())
    pair_jobs = len(list(pairs_dir.glob("pairs_*.csv")))
    partition_jobs = pair_jobs

    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    add_flow_box(ax, 0.03, 0.4, f"Raw monthly files\n{raw_count} files", "#DCEAF7")
    add_flow_box(ax, 0.29, 0.4, f"Cleaning jobs\n{raw_count} jobs", "#FDE2CF")
    add_flow_box(ax, 0.55, 0.4, f"Tail partitions\n{partition_jobs} buckets", "#D9F0D3")
    add_flow_box(ax, 0.81, 0.4, f"Pair jobs + models\n{pair_jobs} + 1 jobs", "#F7D8E6")

    arrow_y = 0.49
    for start_x in [0.23, 0.49, 0.75]:
        ax.annotate(
            "",
            xy=(start_x + 0.04, arrow_y),
            xytext=(start_x, arrow_y),
            arrowprops=dict(arrowstyle="->", linewidth=2.0, color="#555555"),
        )

    ax.set_title("Parallel Flight-Delay Pipeline", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    ensure_project_dirs()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    args.figures_dir.mkdir(parents=True, exist_ok=True)

    pairs = load_pair_data(
        args.pairs_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        read_chunksize=args.read_chunksize,
    )
    df = model_dataframe(pairs)

    del pairs
    gc.collect()

    formulas = build_formulas(include_year_effect=df["current_year"].nunique() > 1)
    coefficient_frames: list[pd.DataFrame] = []

    linear_result = smf.ols(formulas["linear"], data=df).fit()
    (args.results_dir / "linear_delay_model_summary.txt").write_text(
        linear_result.summary().as_text(),
        encoding="utf-8",
    )
    coefficient_frames.append(coefficients_frame("linear", linear_result))
    linear_metrics_row = linear_metrics(linear_result, df)
    linear_ci_series = linear_result.conf_int().loc["prev_ARR_DELAY"]
    linear_coef = float(linear_result.params["prev_ARR_DELAY"])
    linear_ci = (float(linear_ci_series.iloc[0]), float(linear_ci_series.iloc[1]))
    linear_intercept = float(linear_result.params.get("Intercept", 0.0))
    make_prev_arrival_plot(
        df,
        linear_intercept,
        linear_coef,
        args.figures_dir / "prev_arr_delay_vs_current_dep_delay.png",
        sample_size=args.sample_size,
    )
    del linear_result
    gc.collect()

    logistic_result = smf.glm(
        formulas["logistic"],
        data=df,
        family=sm.families.Binomial(),
    ).fit()
    (args.results_dir / "logistic_delay_model_summary.txt").write_text(
        logistic_result.summary().as_text(),
        encoding="utf-8",
    )
    coefficient_frames.append(coefficients_frame("logistic", logistic_result))
    logistic_metrics_row = logistic_metrics(logistic_result, df)
    logistic_ci_series = logistic_result.conf_int().loc["prev_ARR_DELAY"]
    logistic_coef = float(logistic_result.params["prev_ARR_DELAY"])
    logistic_ci = (float(logistic_ci_series.iloc[0]), float(logistic_ci_series.iloc[1]))
    del logistic_result
    gc.collect()

    pooled_table, secondary_table = main_result_table(
        n_obs=len(df),
        linear_coef=linear_coef,
        linear_ci=linear_ci,
        logistic_coef=logistic_coef,
        logistic_ci=logistic_ci,
    )
    pooled_table.to_csv(args.results_dir / "main_result_table.csv", index=False)
    secondary_table.to_csv(args.results_dir / "secondary_linear_result_table.csv", index=False)

    if args.skip_heterogeneity:
        (args.results_dir / "logistic_airline_interaction_summary.txt").write_text(
            "Skipped because --skip-heterogeneity was set.\n",
            encoding="utf-8",
        )
        (args.results_dir / "logistic_turnaround_interaction_summary.txt").write_text(
            "Skipped because --skip-heterogeneity was set.\n",
            encoding="utf-8",
        )
        airline_table = pd.DataFrame(
            columns=[
                "airline",
                "carryover_log_odds_per_1_min",
                "std_err",
                "ci_lower",
                "ci_upper",
                "odds_ratio_per_10_min",
                "or10_ci_lower",
                "or10_ci_upper",
                "n_obs",
            ]
        )
        turnaround_table = pd.DataFrame(
            columns=[
                "turnaround_bin",
                "carryover_log_odds_per_1_min",
                "std_err",
                "ci_lower",
                "ci_upper",
                "odds_ratio_per_10_min",
                "or10_ci_lower",
                "or10_ci_upper",
                "n_obs",
            ]
        )
        airline_table.to_csv(args.results_dir / "airline_carryover_summary.csv", index=False)
        turnaround_table.to_csv(args.results_dir / "turnaround_carryover_summary.csv", index=False)
    else:
        airline_result = smf.glm(
            formulas["logistic_airline"],
            data=df,
            family=sm.families.Binomial(),
        ).fit()
        (args.results_dir / "logistic_airline_interaction_summary.txt").write_text(
            airline_result.summary().as_text(),
            encoding="utf-8",
        )
        coefficient_frames.append(coefficients_frame("logistic_airline_interaction", airline_result))
        airline_table = heterogeneity_airline_table(airline_result, df)
        airline_table.to_csv(args.results_dir / "airline_carryover_summary.csv", index=False)
        del airline_result
        gc.collect()

        turnaround_result = smf.glm(
            formulas["logistic_turnaround"],
            data=df,
            family=sm.families.Binomial(),
        ).fit()
        (args.results_dir / "logistic_turnaround_interaction_summary.txt").write_text(
            turnaround_result.summary().as_text(),
            encoding="utf-8",
        )
        coefficient_frames.append(coefficients_frame("logistic_turnaround_interaction", turnaround_result))
        turnaround_table = heterogeneity_turnaround_table(turnaround_result, df)
        turnaround_table.to_csv(args.results_dir / "turnaround_carryover_summary.csv", index=False)
        del turnaround_result
        gc.collect()

    coefficients = pd.concat(coefficient_frames, ignore_index=True)
    coefficients.to_csv(args.results_dir / "model_coefficients.csv", index=False)

    metrics = pd.DataFrame([linear_metrics_row, logistic_metrics_row])
    metrics.to_csv(args.results_dir / "model_metrics.csv", index=False)

    make_delay_rate_plot(df, args.figures_dir / "delay_rate_by_prev_delay_bin.png")
    if not airline_table.empty:
        make_airline_plot(airline_table, args.figures_dir / "carryover_by_airline.png")
    if not turnaround_table.empty:
        make_turnaround_plot(turnaround_table, args.figures_dir / "carryover_by_turnaround_bin.png")
    make_pipeline_flow_figure(args.pairs_dir, args.figures_dir / "pipeline_parallel_flow.png")

    print(f"Loaded {len(df):,} modeling pairs from {args.pairs_dir}")
    if args.start_year is not None or args.end_year is not None:
        print(f"Year scope: {args.start_year if args.start_year is not None else '-inf'} to {args.end_year if args.end_year is not None else '+inf'}")
    if args.skip_heterogeneity:
        print("Heterogeneity models: skipped")
    print(f"Linear carry-over coefficient (prev_ARR_DELAY): {linear_coef:.4f}")
    print(f"Logistic carry-over coefficient (prev_ARR_DELAY): {logistic_coef:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
