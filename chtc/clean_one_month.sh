#!/bin/bash
set -euo pipefail

INPUT_PATH="$1"
OUTPUT_DIR="${2:-processed/monthly_clean}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then
  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${OUTPUT_DIR}"

"${PYTHON_BIN}" scripts/clean_one_month.py --input "${INPUT_PATH}" --output-dir "${OUTPUT_DIR}"
