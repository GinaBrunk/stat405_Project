#!/bin/bash
set -euo pipefail

PAIRS_DIR="${1:-processed/pairs}"
RESULTS_DIR="${2:-results/full_sample}"
FIGURES_DIR="${3:-results/full_sample/figures}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then
  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${RESULTS_DIR}" "${FIGURES_DIR}"

"${PYTHON_BIN}" scripts/fit_delay_models.py \
  --pairs-dir "${PAIRS_DIR}" \
  --results-dir "${RESULTS_DIR}" \
  --figures-dir "${FIGURES_DIR}"
