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

Useful options:

```powershell
.\.venv\Scripts\python.exe main.py --solver highs
.\.venv\Scripts\python.exe main.py --time-limit 300
.\.venv\Scripts\python.exe main.py -o my_result.json
.\.venv\Scripts\python.exe main.py --artifacts-dir runs/experiment_001
```

Each run writes reproducibility metadata into the output JSON and artifact
directory, including input hash, git commit, package versions, solver settings,
model size, objective value, big-M value, and validation results.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover input validation, known-answer validation fixtures, output
validation failure modes, constraint-section naming, and stable run metadata
hashing.

## Notes

See `docs/model_notes.md` for formulation notes, validation checks, numerical
settings, and the remaining research-grade improvement roadmap.
