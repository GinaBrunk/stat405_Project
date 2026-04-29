#!/bin/bash
set -euo pipefail

PARTITION_PATH="$1"
OUTPUT_DIR="${2:-processed/pairs}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

if [[ -d "${PROJECT_ROOT}/python_deps" ]]; then
  export PYTHONPATH="${PROJECT_ROOT}/python_deps${PYTHONPATH:+:${PYTHONPATH}}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p "${OUTPUT_DIR}"

"${PYTHON_BIN}" scripts/build_pairs_one_partition.py --partition "${PARTITION_PATH}" --output-dir "${OUTPUT_DIR}"
