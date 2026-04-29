#!/bin/bash
set -euo pipefail

PAIRS_DIR="${1:-processed/pairs_2015_2024}"
RESULTS_ROOT="${2:-results_2015_2024_yearly}"
YEAR="${3:-2025}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

RESULTS_DIR="${RESULTS_ROOT}/${YEAR}"
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
  --start-year "${YEAR}" \
  --end-year "${YEAR}" \
  --skip-heterogeneity
