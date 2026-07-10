#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_VERSION="3.10"
CONDA_ENV_NAME="${MAPTOOLS_CONDA_ENV:-maptools}"
VENV_DIR="${MAPTOOLS_VENV_DIR:-.venv}"

usage() {
    cat <<EOF
Usage: $0 [conda|venv]

Install map-tools-beiguo dependencies into an isolated Python ${PYTHON_VERSION} environment.
Do not install this project into the system/global Python environment.

Options:
  conda    Create/update conda environment: ${CONDA_ENV_NAME}
  venv     Create/update local venv: ${VENV_DIR}
EOF
}

choose_mode() {
    cat >&2 <<EOF
No environment type was specified.

Choose the environment type to create/update:
  1) conda (${CONDA_ENV_NAME}, Python ${PYTHON_VERSION})
  2) venv  (${VENV_DIR}, Python ${PYTHON_VERSION})
EOF
    printf "Selection [1/2]: " >&2
    read -r selection
    case "$selection" in
        1) echo "conda" ;;
        2) echo "venv" ;;
        *) echo "Invalid selection: ${selection}" >&2; exit 2 ;;
    esac
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
  macOS Homebrew Python ${PYTHON_VERSION}:
    brew install python-tk@${PYTHON_VERSION}
    $0 venv

  conda:
    conda install -n ${CONDA_ENV_NAME} tk
    $0 conda
EOF
    exit 1
}

ensure_conda() {
    if ! command -v conda >/dev/null 2>&1; then
        echo "Error: conda was not found. Install Miniforge/Miniconda, or run: $0 venv" >&2
        exit 1
    fi

    if conda run -n "$CONDA_ENV_NAME" python --version >/dev/null 2>&1; then
        echo "Using existing conda environment: ${CONDA_ENV_NAME}"
    else
        echo "Creating conda environment: ${CONDA_ENV_NAME} (Python ${PYTHON_VERSION})"
        conda create -n "$CONDA_ENV_NAME" "python=${PYTHON_VERSION}" -y
    fi

    conda run -n "$CONDA_ENV_NAME" python -m pip install --upgrade pip
    conda run -n "$CONDA_ENV_NAME" python -m pip install -r requirements.txt
    check_tkinter "conda environment ${CONDA_ENV_NAME}" conda run -n "$CONDA_ENV_NAME" python
    echo "Done. Run with: ./run_maptools.sh --conda"
}

ensure_venv() {
    if ! command -v "python${PYTHON_VERSION}" >/dev/null 2>&1; then
        echo "Error: python${PYTHON_VERSION} was not found. Install Python ${PYTHON_VERSION}, or run: $0 conda" >&2
        exit 1
    fi

    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "Using existing venv: ${VENV_DIR}"
    else
        echo "Creating venv: ${VENV_DIR} (Python ${PYTHON_VERSION})"
        "python${PYTHON_VERSION}" -m venv "$VENV_DIR"
    fi

    "${VENV_DIR}/bin/python" -m pip install --upgrade pip
    "${VENV_DIR}/bin/python" -m pip install -r requirements.txt
    check_tkinter "venv at ${VENV_DIR}" "${VENV_DIR}/bin/python"
    echo "Done. Run with: ./run_maptools.sh --venv"
}

MODE="${1:-}"
case "$MODE" in
    -h|--help)
        usage
        exit 0
        ;;
    "")
        MODE="$(choose_mode)"
        ;;
esac

case "$MODE" in
    conda|--conda)
        ensure_conda
        ;;
    venv|--venv)
        ensure_venv
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
