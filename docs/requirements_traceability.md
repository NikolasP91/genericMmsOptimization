# Requirements Traceability Matrix

This matrix maps accepted project work to the two governing local PDF sources:

- `512811 ΔΙΑΚΗΡΥΞΗ - ΚΗΜΔΗΣ (2) -w_o comments.pdf`
- `κώδικας-διαχείρισης-μδν-4η-έκδοση-3ος-2022.pdf`

The project scope covers RDAS/DS-style optimization support, dispatch instruction
preparation, reserve reporting, RES curtailment reporting, validation, and
benchmark evidence. Real-Time Dispatch (RTD) is explicitly out of scope and must
not be implemented in this project.

| ID | Source | Requirement Theme | Project Response | Status | Code / Artifact |
| --- | --- | --- | --- | --- | --- |
| MMS-001 | Tender Part C, MMS overview and application list | MMS includes Master File, RDAS, DS, reporting, publishing, communications, and real-time logging concepts. | Keep the optimizer as a scheduling kernel and add MMS-style report artifacts around it. | In progress | `mms/`, `runs/latest/*.json` |
| DS-001 | Tender Part C 5.3 Dispatch Scheduling | DS prepares schedules and dispatch instructions from reported data and forecasts. | Add `dispatch_instructions.json` derived from solved unit schedules, commitment, reserves, and setpoints. | In progress | `mms/reports.py`, `runs/latest/dispatch_instructions.json` |
| DS-002 | MDN Code Articles 115-123 | Dispatch procedure uses collected data, produces dispatch program results, and issues dispatch instructions. | Report per-period unit instructions with source, period, active power, commitment action, reserve assignment, and setpoint when available. | In progress | `mms/reports.py` |
| RES-001 | Tender Part C 5.3 | DS should maximize energy absorption from RES/CHP while preserving secure operation and minimizing cost. | Add `res_curtailment_report.json` with available, dispatched, curtailed, and curtailed share values. | In progress | `mms/reports.py`, `runs/latest/res_curtailment_report.json` |
| RES-002 | MDN Code Articles 108, 208, 209 and Appendix A transitional RES setpoint rules | RES forecasts, RES limits, and reserve needs from non-dispatchable RES must be visible and auditable. | Report RES/PV curtailment by unit and period, including setpoints when provided by the optimization output. | In progress | `mms/reports.py` |
| RSV-001 | MDN Code Article 109 | Active power reserve requirements account for load, largest online unit, and RES/CHP variability; requirements may be system-wide or by zone. | Add `reserve_monitoring_report.json` using the same deterministic reserve-sizing expressions used by the MIP. | In progress | `mms/reports.py` |
| RSV-002 | Tender EMS/AGC reserve monitoring requirements | Reserve monitoring should compare available/provided reserve against required reserve and expose deficiencies. | Report required, provided, surplus/shortfall, and requirement method breakdown for primary, secondary, and tertiary reserves. | In progress | `mms/reports.py`, `runs/latest/reserve_monitoring_report.json` |
| VAL-001 | Tender MMS validation/common services and MDN record-keeping articles | Data collection, validation, records, and notifications must be reproducible. | Preserve input/output snapshots and add report tests/benchmark cases. | In progress | `artifacts.py`, `tests/`, `benchmarks/` |
| BEN-001 | Accepted roadmap item #10 | Benchmark cases should demonstrate requirements-driven behavior. | Add focused tests for dispatch instructions, reserve reporting, RES curtailment, and RTD exclusion. | In progress | `tests/test_mms_reports.py`, `tests/test_input_validation.py` |
| BEN-002 | Accepted roadmap item #10 | Full DS execution should be protected against accidental formulation or artifact regressions. | Add a full-run biomass-case regression covering solver status, objective value, model size, validation status, and required artifacts. | Implemented | `tests/test_full_run_regression.py` |
| MOD-001 | Accepted roadmap item #2 | The implementation should be maintainable as an MMS-oriented software module, not only a single script. | Split active algebra, workflow orchestration, post-solve processing, and reports into `mms/model/`, `mms/pipeline.py`, `mms/postsolve.py`, and `mms/reports.py`. | Implemented | `mms/`, `RV_genericMmsOptimization.py` |
| LOG-001 | Tender MMS common services / record-keeping theme | Runs should leave auditable execution evidence. | Mirror Python/application output to `run_log.txt`, write native HiGHS logs to `solver_log.txt`, and write structured lifecycle events to `run_events.jsonl`. | Implemented | `mms/logging_utils.py`, `main.py`, `runs/latest/run_events.jsonl` |
| SCOPE-001 | User direction, 2026-06-13 | RTD will not be developed in this project. | Reject `run_mode: "RTD"` during input validation and document RTD as excluded. | In progress | `input_validation.py`, `docs/model_notes.md` |
