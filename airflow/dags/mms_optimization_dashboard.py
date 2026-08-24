"""Airflow DAG for running the MMS optimization and dashboard generation."""

from __future__ import annotations

import os
import shlex
from datetime import datetime, timedelta

try:
    from airflow.sdk import DAG
except ImportError:  # Airflow 2 compatibility.
    from airflow import DAG

from airflow.operators.bash import BashOperator


PROJECT_DIR = os.environ.get(
    "MMS_PROJECT_DIR",
    "/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization",
)
PROJECT_PYTHON = os.environ.get("MMS_PROJECT_PYTHON", f"{PROJECT_DIR}/.venv-wsl/bin/python")
CONFIG_FILE = os.environ.get("MMS_CONFIG_FILE", "new_json_test.json")
RUN_DIR = os.environ.get("MMS_AIRFLOW_RUN_DIR", "runs/airflow")
SOLVER = os.environ.get("MMS_SOLVER", "highs")
TIME_LIMIT = os.environ.get("MMS_TIME_LIMIT")


def q(value: str) -> str:
    return shlex.quote(value)


def project_command(command: str) -> str:
    return f"set -euo pipefail; cd {q(PROJECT_DIR)}; {command}"


run_id = "{{ dag_run.run_id | replace(':', '_') | replace('+', '_') | replace('.', '_') }}"
output_json = f"{RUN_DIR}/optimization_output_{run_id}.json"
dashboard_html = f"{RUN_DIR}/dashboard_{run_id}.html"
artifact_dir = f"{RUN_DIR}/artifacts_{run_id}"
log_file = f"{RUN_DIR}/run_log_{run_id}.txt"
solver_log_file = f"{artifact_dir}/solver_log.txt"

time_limit_arg = f" --time-limit {q(TIME_LIMIT)}" if TIME_LIMIT else ""


default_args = {
    "owner": "mms",
    "retries": 0,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="mms_optimization_dashboard",
    description="Run MMS optimization, then generate the HTML dashboard.",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["mms", "optimization", "dashboard"],
) as dag:
    prepare_run_directory = BashOperator(
        task_id="prepare_run_directory",
        bash_command=project_command(f"mkdir -p {q(RUN_DIR)} {q(artifact_dir)}"),
    )

    run_optimization = BashOperator(
        task_id="run_optimization",
        bash_command=project_command(
            f"{q(PROJECT_PYTHON)} main.py {q(CONFIG_FILE)} "
            f"--solver {q(SOLVER)} "
            f"--output {q(output_json)} "
            f"--artifacts-dir {q(artifact_dir)} "
            f"--log-file {q(log_file)} "
            f"--solver-log-file {q(solver_log_file)}"
            f"{time_limit_arg}"
        ),
    )

    generate_dashboard = BashOperator(
        task_id="generate_dashboard",
        bash_command=project_command(
            f"{q(PROJECT_PYTHON)} dashboard.py {q(output_json)} -o {q(dashboard_html)} "
            f"&& cp {q(output_json)} {q(RUN_DIR)}/optimization_output_latest.json "
            f"&& cp {q(dashboard_html)} {q(RUN_DIR)}/dashboard_latest.html"
        ),
    )

    prepare_run_directory >> run_optimization >> generate_dashboard
