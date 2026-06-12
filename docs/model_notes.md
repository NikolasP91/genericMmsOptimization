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

The runner now validates:

- Solver status is `Optimal` unless `require_optimal` is disabled.
- Output unit count matches filtered input unit count.
- Per-period arrays have the expected length.
- Load balance is respected after reported load curtailment.
- Reported load curtailment is zero within tolerance.
- Dispatch does not exceed input availability.
- Units do not produce power while reported off.
- Reserve arrays have the expected shape and are nonnegative.
- Reported APR violation arrays are zero within tolerance.

The validation report is embedded under the `Validation` key in the output JSON.

## Numerical Settings

The JSON file supports:

```json
"optimization_parameters": {
  "solver": "highs",
  "require_optimal": true,
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

## Research-Grade Improvements Still To Do

- Replace broad big-M constants with constraint-specific tight bounds.
- Add small benchmark cases with known optimal schedules and objective values.
- Split the monolithic model-building file into named modules by constraint
  family.
- Add equation-level documentation for each constraint family.
- Add tests that compare post-solve balances, reserves, ramping, startup, and
  shutdown behavior against hand-computed expectations.
- Consider stochastic/robust renewable treatment if forecast uncertainty is in
  scope for the study.
