# Generic MMS Optimization

Mixed-integer dispatch scheduling / unit-commitment prototype for thermal,
RES, and PV generating units.

## Setup

Create or activate a Python environment, then install dependencies:

```powershell
pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe main.py
```

By default the runner uses:

- input: `v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json`
- solver: HiGHS through PuLP/highspy
- output: `optimization_output.json`
- post-solve validation: enabled
- run artifacts: `runs/latest`
- plain text run log: `run_log.txt`
- structured event log: `runs/latest/run_events.jsonl`
- native HiGHS solver log: `runs/latest/solver_log.txt`
- structured warning/diagnostics reports: `runs/latest/warning_report.json`,
  `runs/latest/diagnostics_report.json`
- thermal cost-curve audit: `runs/latest/thermal_cost_curve_audit.json`
- thermal cost reconstruction: `runs/latest/thermal_cost_report.json`
- penalty hierarchy audit: `runs/latest/penalty_hierarchy_audit.json`
- objective cost breakdown: `runs/latest/objective_breakdown_report.json`
- performance profile: `runs/latest/performance_profile.json`

Useful options:

```powershell
.\.venv\Scripts\python.exe main.py --solver highs
.\.venv\Scripts\python.exe main.py --time-limit 300
.\.venv\Scripts\python.exe main.py -o my_result.json
.\.venv\Scripts\python.exe main.py --artifacts-dir runs/experiment_001
.\.venv\Scripts\python.exe main.py --log-file runs/experiment_001/run_log.txt
.\.venv\Scripts\python.exe main.py --solver-log-file runs/experiment_001/solver_log.txt
```

Each run writes reproducibility metadata into the output JSON and artifact
directory, including input hash, git commit, package versions, solver settings,
model size, objective value, big-M value, validation results, plain text logs,
native solver logs, structured warning/diagnostics reports, thermal cost-curve
audit/generation results, cost-reconstruction results, penalty hierarchy audit,
objective cost breakdown, performance timings, and structured run events.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover input validation, hand-checkable benchmark fixtures, output
validation failure modes, structured diagnostics, thermal cost-curve audits and
quadratic-to-PWL generation, penalty hierarchy audits, objective breakdown
reconciliation, constraint-section naming, local big-M bound helpers, stable run
metadata hashing, logging utilities, report builders, module boundaries, and a
full biomass-case optimization regression.

## Notes

See `docs/model_notes.md` for formulation notes, validation checks, numerical
settings, and the remaining research-grade improvement roadmap.
