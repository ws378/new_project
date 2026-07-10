#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

CONDA_ENV_NAME="${MAPTOOLS_CONDA_ENV:-maptools}"
VENV_DIR="${MAPTOOLS_VENV_DIR:-.venv}"

usage() {
    cat <<EOF
Usage: $0 [--venv|--conda] [maptools arguments...]

Run the maptools/main.py application entry from an isolated Python environment.
This script refuses to use the system/global Python environment.

After setup, start the editor with:
  ./run_maptools.sh

Default environment resolution:
  1) use local venv at ${VENV_DIR} if available
  2) otherwise use conda environment ${CONDA_ENV_NAME} if available
  3) otherwise prompt to run ./setup_env.sh

If no environment exists yet, run:
  ./setup_env.sh
EOF
}

conda_env_exists() {
    command -v conda >/dev/null 2>&1 && conda run -n "$CONDA_ENV_NAME" python --version >/dev/null 2>&1
}

check_tkinter() {
    local env_label="$1"
    shift

    if "$@" - <<'PY' >/dev/null 2>&1
import tkinter
PY
    then
        return 0
    fi

    cat >&2 <<EOF
Error: ${env_label} Python cannot import tkinter/_tkinter.

maptools is a Tkinter GUI application, so the selected Python runtime must include Tk support.
This is not a pip requirements issue.

Fix hints:
  macOS Homebrew Python 3.10:
    brew install python-tk@3.10
    ./setup_env.sh venv

  conda:
    conda install -n ${CONDA_ENV_NAME} tk
    ./setup_env.sh conda
EOF
    exit 1
}

run_venv() {
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        echo "Error: venv not found at ${VENV_DIR}. Run: ./setup_env.sh venv" >&2
        exit 1
    fi
    check_tkinter "venv at ${VENV_DIR}" "${VENV_DIR}/bin/python"
    exec "${VENV_DIR}/bin/python" -m maptools.main "$@"
}

run_conda() {
    if ! conda_env_exists; then
        echo "Error: conda environment '${CONDA_ENV_NAME}' not found. Run: ./setup_env.sh conda" >&2
        exit 1
    fi
    check_tkinter "conda environment ${CONDA_ENV_NAME}" conda run -n "$CONDA_ENV_NAME" python
    exec conda run -n "$CONDA_ENV_NAME" python -m maptools.main "$@"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ "${1:-}" == "--venv" ]]; then
    shift
    run_venv "$@"
fi

if [[ "${1:-}" == "--conda" ]]; then
    shift
    run_conda "$@"
fi

if [[ -x "${VENV_DIR}/bin/python" ]]; then
    run_venv "$@"
fi

if conda_env_exists; then
    run_conda "$@"
fi

cat >&2 <<EOF
Error: no project virtual environment was found.

This project must run in conda or venv, not the system/global Python environment.
Run ./setup_env.sh and choose conda or venv for the first setup.
EOF
exit 1
