#!/bin/bash
set -euo pipefail

N_REPS="$1"
SEED="$2"
OUTPUT_PATH="$3"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then
  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "$(dirname "${OUTPUT_PATH}")"

"${PYTHON_BIN}" scripts/bootstrap_delay_models.py \
  --n-reps "${N_REPS}" \
  --seed "${SEED}" \
  --output "${OUTPUT_PATH}"
