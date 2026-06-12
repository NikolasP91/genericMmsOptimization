# Benchmarks

Benchmark fixtures should be small, auditable cases tied to the governing
requirements in `docs/requirements_traceability.md`.

Current benchmark coverage:

- `known_answer_cases.json`: solution-validation accounting checks.
- `tests/test_mms_reports.py`: dispatch instruction, reserve monitoring, and
  RES curtailment report checks.
- `tests/test_full_run_regression.py`: full accepted biomass-case optimization
  regression for solver status, objective value, model size, validation status,
  and artifact creation.

Recommended next benchmark fixtures:

- Additional DS cases with one thermal unit and one RES unit where curtailment is forced by
  technical minimum generation.
- A reserve-shortage case that produces a nonzero APR violation.
- A commitment-transition case with an expected synchronization/desynchronization
  instruction sequence.
- A RES setpoint case with expected proportional curtailment.

RTD benchmark cases are intentionally excluded from this project.
