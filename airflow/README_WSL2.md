# Airflow orchestration in WSL2

This setup runs Airflow inside WSL2 and uses it to execute:

1. `main.py`
2. `dashboard.py`

The recommended layout uses two Python virtual environments:

- `~/airflow/airflow_venv` for Apache Airflow
- the project `.venv-wsl` for MMS dependencies such as `pulp` and `highspy`

Airflow officially supports Linux/POSIX systems and Windows usage through WSL2.
Install Airflow with its release constraints file so dependency resolution is
repeatable.

## 1. Open WSL2 Ubuntu

From PowerShell:

```powershell
wsl -d Ubuntu
```

If Ubuntu is not installed yet:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if WSL asks you to.

## 2. Install system packages in WSL

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
```

## 3. Create the Airflow environment

```bash
mkdir -p ~/airflow
cd ~/airflow

python3 -m venv airflow_venv
source airflow_venv/bin/activate
python -m pip install --upgrade pip

AIRFLOW_VERSION=3.3.1
PYTHON_VERSION="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}"
```

## 4. Prepare the MMS project environment in WSL

If you keep the project in its current Windows location, WSL sees it at:

```bash
/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization
```

Create a Linux venv inside the project:

```bash
cd /mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization
python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py --time-limit 60
python dashboard.py
deactivate
```

For better WSL performance, you can instead copy or clone the project under
your Linux home directory, for example `~/projects/genericMmsOptimization`, and
use that path in the environment variables below.

## 5. Configure Airflow paths

Activate Airflow again:

```bash
source ~/airflow/airflow_venv/bin/activate
```

Set the Airflow home and DAG folder:

```bash
export AIRFLOW_HOME=~/airflow
export AIRFLOW__CORE__DAGS_FOLDER=/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization/airflow/dags
```

Set MMS-specific variables used by the DAG:

```bash
export MMS_PROJECT_DIR=/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization
export MMS_PROJECT_PYTHON=/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization/.venv-wsl/bin/python
export MMS_CONFIG_FILE=new_json_test.json
export MMS_SOLVER=highs
```

Optional time limit:

```bash
export MMS_TIME_LIMIT=300
```

## 6. Start Airflow

For a local single-machine setup:

```bash
airflow standalone
```

Airflow prints the webserver URL, username, and password in the terminal.
Open the URL in your browser, usually:

```text
http://localhost:8080
```

Enable and trigger the DAG named:

```text
mms_optimization_dashboard
```

## 7. Outputs

Each Airflow run writes files under:

```text
runs/airflow
```

Important outputs:

- `optimization_output_latest.json`
- `dashboard_latest.html`
- run-specific `optimization_output_<run_id>.json`
- run-specific `dashboard_<run_id>.html`
- run-specific artifacts under `artifacts_<run_id>`

From PowerShell, open the latest dashboard:

```powershell
Start-Process .\runs\airflow\dashboard_latest.html
```

## 8. Validate the DAG from WSL

```bash
source ~/airflow/airflow_venv/bin/activate
export AIRFLOW_HOME=~/airflow
export AIRFLOW__CORE__DAGS_FOLDER=/mnt/c/Users/nickp/OneDrive/Desktop/MMS/genericMmsOptimization/airflow/dags

airflow dags list | grep mms_optimization_dashboard
airflow dags test mms_optimization_dashboard 2026-01-01
```
