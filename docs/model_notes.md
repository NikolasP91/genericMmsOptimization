# Dispatch Scheduling Model Notes

This project builds a deterministic mixed-integer linear optimization model for
dispatch scheduling / unit commitment with thermal units, RES/PV units, reserve
requirements, operating-state logic, ramping, availability limits, and
high-penalty relaxation variables.

## Current Strengths

- MILP structure with binary commitment/state variables and continuous dispatch.
- Explicit startup/shutdown, min/max generation, ramping, reserve, and RES/PV
  dispatch constraints.
- High-cost relaxation variables for diagnosing infeasibility instead of failing
  without a useful solution trace.
- Native HiGHS solver support through PuLP/highspy.
- Automatic post-solve validation through `solution_validation.py`.

## Automatic Validation Checks

The runner now validates the input before building the optimization model and
validates the output after solution.

Input validation checks include:

- Required top-level JSON sections.
- Load horizon consistency.
- Required generating-unit fields.
- Forecast and availability array lengths.
- Nonnegative physical limits and reserve capacities.
- Unique `gen_id` values, with a warning when IDs are not contiguous.
- Solver, time-limit, and big-M parameter validity.

The repository also contains a high-level JSON Schema at
`schemas/input_schema.json` for documentation and tool integration.

Post-solve validation checks include:

- Solver status is `Optimal` unless `require_optimal` is disabled.
- Output unit count matches filtered input unit count.
- Per-period arrays have the expected length.
- Load balance is respected after reported load curtailment.
- Reported load curtailment is zero within tolerance.
- Dispatch does not exceed input availability.
- Units do not produce power while reported off.
- State, startup, and shutdown outputs are binary within tolerance.
- Startup and shutdown outputs match consecutive state changes.
- Reserve arrays have the expected shape and are nonnegative.
- Reserve outputs do not exceed unit reserve capability.
- Reported APR violation arrays are zero within tolerance.

The validation report is embedded under the `Validation` key in the output JSON.

Run the validation unit tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Numerical Settings

The JSON file supports:

```json
"optimization_parameters": {
  "solver": "highs",
  "require_optimal": true,
  "big_m": "auto",
  "highs_options": {
    "user_objective_scale": -4
  },
  "early_stopping": {
    "time_limit": null
  }
}
```

`user_objective_scale` is a HiGHS option used to improve numerical conditioning
when the objective has very large penalty coefficients.

`big_m` can be a number or `"auto"`. In automatic mode the code estimates a
scenario-scaled value from load, availability, reserve, operating-state, and
transition-cost magnitudes. This is tighter than a fixed global constant while
still allowing explicit override when a larger instance needs it.

The model assigns stable names to anonymous PuLP constraints by build section
before the MPS file is written, for example `mms_load_balance_000001`. The solve
metadata also records the number of constraints and variables added by each
section. This improves MPS inspection and makes solver diagnostics less opaque
than default `_C1234` names.

## Reproducibility Artifacts

By default, `main.py` writes run artifacts to `runs/latest`:

- `input_snapshot.json`
- `output_snapshot.json`
- `run_metadata.json`
- `solve_metadata.json`
- `validation_report.json`
- `example_model.mps`

These are ignored by git because they are generated per run.

The output JSON includes:

- `Solve_Metadata`: objective, solver, big-M value, model size, constraint
  section statistics, and solve time.
- `Run_Metadata`: input hash, git commit, git dirty flag, Python version,
  platform, and package versions.

## Benchmark Fixtures

`benchmarks/known_answer_cases.json` contains small hand-checkable validation
cases. They are intentionally tiny, so they can run quickly in unit tests and
catch regressions in the accounting logic before larger optimization cases are
added.

## Research-Grade Improvements Still To Do

- Replace broad big-M constants with constraint-specific tight bounds.
- Add full optimization benchmark cases with known optimal schedules and
  objective values.
- Continue splitting the monolithic model-building file into separate modules by
  constraint family. The build is now section-tracked and support code is
  modularized, but moving the algebra itself should be done incrementally to
  avoid changing the formulation by accident.
- Add equation-level documentation for each constraint family.
- Add deeper tests that compare ramping and operating-state behavior against
  hand-computed expectations.
- Stochastic renewables, network constraints, and CI were intentionally left out
  of this implementation batch.
