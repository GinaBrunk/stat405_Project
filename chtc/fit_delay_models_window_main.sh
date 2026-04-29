#!/bin/bash
set -euo pipefail

PAIRS_DIR="${1:-processed/pairs_2015_2024}"
RESULTS_ROOT="${2:-results_2015_2024_windows}"
START_YEAR="${3:-2015}"
END_YEAR="${4:-2017}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

WINDOW_ID="${START_YEAR}_${END_YEAR}"
RESULTS_DIR="${RESULTS_ROOT}/${WINDOW_ID}"
FIGURES_DIR="${RESULTS_DIR}/figures"

if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then
  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${RESULTS_DIR}" "${FIGURES_DIR}"

"${PYTHON_BIN}" scripts/fit_delay_models.py \
  --pairs-dir "${PAIRS_DIR}" \
  --results-dir "${RESULTS_DIR}" \
  --figures-dir "${FIGURES_DIR}" \
  --start-year "${START_YEAR}" \
  --end-year "${END_YEAR}" \
  --skip-heterogeneity
