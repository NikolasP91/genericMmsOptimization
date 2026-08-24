#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${MMS_PROJECT_DIR:-/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization}"
AIRFLOW_HOME_DIR="${AIRFLOW_HOME:-$HOME/airflow}"
AIRFLOW_VERSION="${AIRFLOW_VERSION:-3.3.1}"

cd "$PROJECT_DIR"

python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m py_compile main.py dashboard.py airflow/dags/mms_optimization_dashboard.py
deactivate

mkdir -p "$AIRFLOW_HOME_DIR"
cd "$AIRFLOW_HOME_DIR"

python3 -m venv airflow_venv
source airflow_venv/bin/activate
python -m pip install --upgrade pip

PYTHON_VERSION="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "$CONSTRAINT_URL"

export AIRFLOW_HOME="$AIRFLOW_HOME_DIR"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJECT_DIR/airflow/dags"
export MMS_PROJECT_DIR="$PROJECT_DIR"
export MMS_PROJECT_PYTHON="$PROJECT_DIR/.venv-wsl/bin/python"
export MMS_CONFIG_FILE="${MMS_CONFIG_FILE:-new_json_test.json}"
export MMS_SOLVER="${MMS_SOLVER:-highs}"

mkdir -p "$AIRFLOW_HOME_DIR/dags"
ln -sfn "$PROJECT_DIR/airflow/dags/mms_optimization_dashboard.py" \
  "$AIRFLOW_HOME_DIR/dags/mms_optimization_dashboard.py"

airflow dags list | grep mms_optimization_dashboard

cat <<EOF

Airflow environment is ready.

Use these commands in WSL to start Airflow:

source "$AIRFLOW_HOME_DIR/airflow_venv/bin/activate"
export AIRFLOW_HOME="$AIRFLOW_HOME_DIR"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJECT_DIR/airflow/dags"
export MMS_PROJECT_DIR="$PROJECT_DIR"
export MMS_PROJECT_PYTHON="$PROJECT_DIR/.venv-wsl/bin/python"
export MMS_CONFIG_FILE="${MMS_CONFIG_FILE:-new_json_test.json}"
export MMS_SOLVER="${MMS_SOLVER:-highs}"
airflow standalone

EOF
