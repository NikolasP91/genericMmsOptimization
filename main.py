#!/usr/bin/env python
import argparse
import json
import sys
import traceback
from time import perf_counter
from pathlib import Path

from artifacts import prepare_artifact_dir, write_json, write_run_artifacts
from input_validation import (
    InputValidationError,
    assert_valid_input,
    format_input_validation_report,
)
from mms.diagnostics import build_diagnostics_report, build_warning_report
from mms.logging_utils import JsonEventLogger, tee_output
from mms.reports import build_mms_reports
from run_metadata import build_run_metadata
from mms.pipeline import parse_and_execute_optimization
from solution_validation import format_validation_report, validate_solution


DEFAULT_CONFIG_FILE = "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json"
DEFAULT_OUTPUT_FILE = "optimization_output.json"


def parse_args():
    parser = argparse.ArgumentParser(description="Run the MMS dispatch scheduling optimization.")
    parser.add_argument(
        "config",
        nargs="?",
        default=DEFAULT_CONFIG_FILE,
        help=f"Input scenario JSON file. Defaults to {DEFAULT_CONFIG_FILE}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output JSON file. Defaults to {DEFAULT_OUTPUT_FILE}.",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="Optional solver time limit in seconds. Overrides optimization_parameters.early_stopping.time_limit.",
    )
    parser.add_argument(
        "--solver",
        choices=("highs", "cbc"),
        default="highs",
        help="MILP solver to use. Defaults to highs.",
    )
    parser.add_argument(
        "--validation-tolerance",
        type=float,
        default=1e-3,
        help="Numerical tolerance for post-solve validation checks. Defaults to 1e-3.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="runs/latest",
        help="Directory for input/output/metadata/error artifacts. Defaults to runs/latest.",
    )
    parser.add_argument(
        "--skip-input-validation",
        action="store_true",
        help="Skip pre-solve input validation.",
    )
    parser.add_argument(
        "--log-file",
        default="run_log.txt",
        help="Plain text run log that mirrors console output. Use an empty value to disable.",
    )
    parser.add_argument(
        "--solver-log-file",
        default=None,
        help=(
            "Native solver log file. Defaults to solver_log.txt under the artifacts "
            "directory for HiGHS runs."
        ),
    )
    return parser.parse_args()


def run(args):
    run_start = perf_counter()
    performance_stages = []

    def record_stage(stage, started_at):
        performance_stages.append(
            {
                "stage": stage,
                "seconds": round(perf_counter() - started_at, 6),
            }
        )

    config_path = Path(args.config)
    output_path = Path(args.output)
    artifact_dir = prepare_artifact_dir(args.artifacts_dir)
    event_log_path = artifact_dir / "run_events.jsonl" if artifact_dir is not None else None
    events = JsonEventLogger(event_log_path)

    events.event(
        "run_started",
        config_path=str(config_path),
        output_path=str(output_path),
        artifact_dir=str(artifact_dir) if artifact_dir is not None else None,
        solver=args.solver,
    )
    print(f"Loading configuration from: {config_path}")
    input_load_start = perf_counter()
    with config_path.open("r", encoding="utf-8") as f:
        input_data = json.load(f)
    record_stage("input_load", input_load_start)

    if args.time_limit is not None:
        input_data.setdefault("optimization_parameters", {}).setdefault("early_stopping", {})[
            "time_limit"
        ] = args.time_limit
        print(f"Using solver time limit: {args.time_limit} seconds")
    input_data.setdefault("optimization_parameters", {})["solver"] = args.solver
    if args.solver == "highs":
        solver_log_file = args.solver_log_file
        if solver_log_file is None and artifact_dir is not None:
            solver_log_file = str(artifact_dir / "solver_log.txt")
        if solver_log_file:
            input_data.setdefault("optimization_parameters", {}).setdefault(
                "highs_options", {}
            ).setdefault("log_file", solver_log_file)
            events.event("solver_log_configured", solver_log_file=solver_log_file)
    print(f"Using solver: {args.solver}")

    if not args.skip_input_validation:
        input_validation_start = perf_counter()
        try:
            input_validation = assert_valid_input(input_data)
        except InputValidationError as e:
            error_report = {
                "status": "failed",
                "stage": "input_validation",
                "errors": e.errors,
                "warnings": e.warnings,
            }
            events.event("input_validation_failed", errors=len(e.errors), warnings=len(e.warnings))
            diagnostics_report = build_diagnostics_report(
                input_data, error_report=error_report, tolerance=args.validation_tolerance
            )
            write_run_artifacts(
                artifact_dir,
                input_data,
                error_report=error_report,
                diagnostics_report=diagnostics_report,
                log_file=args.log_file,
            )
            print(format_input_validation_report(error_report))
            return 1
        record_stage("input_validation", input_validation_start)
        print(format_input_validation_report(input_validation))
        events.event(
            "input_validation_passed",
            warnings=len(input_validation.get("warnings", [])),
        )

    try:
        optimization_start = perf_counter()
        result = parse_and_execute_optimization(input_data)
        record_stage("optimization_pipeline", optimization_start)
    except Exception as e:
        print(f"\nError during optimization: {e}")
        traceback_text = traceback.format_exc()
        print(traceback_text)
        error_report = {
            "stage": "optimization",
            "error": str(e),
            "traceback": traceback_text,
        }
        diagnostics_report = build_diagnostics_report(
            input_data, error_report=error_report, tolerance=args.validation_tolerance
        )
        write_run_artifacts(
            artifact_dir,
            input_data,
            error_report=error_report,
            diagnostics_report=diagnostics_report,
            log_file=args.log_file,
        )
        events.event("optimization_failed", error=str(e))
        return 1

    solution_validation_start = perf_counter()
    validation = validate_solution(input_data, result, tolerance=args.validation_tolerance)
    record_stage("solution_validation", solution_validation_start)
    result["Validation"] = validation

    report_start = perf_counter()
    result.update(build_mms_reports(input_data, result, tolerance=args.validation_tolerance))
    record_stage("mms_report_building", report_start)

    diagnostics_start = perf_counter()
    result["Warning_Report"] = build_warning_report(
        input_data, result, validation, tolerance=args.validation_tolerance
    )
    result["Diagnostics_Report"] = build_diagnostics_report(
        input_data, result, validation, tolerance=args.validation_tolerance
    )
    record_stage("diagnostics_building", diagnostics_start)

    metadata_start = perf_counter()
    result["Run_Metadata"] = build_run_metadata(input_data, config_path, output_path, args.solver)
    record_stage("run_metadata", metadata_start)
    events.event(
        "optimization_finished",
        solution_status=result.get("Solution_Status", "Unknown"),
        objective_value=result.get("Solve_Metadata", {}).get("objective_value"),
        num_constraints=result.get("Solve_Metadata", {}).get("num_constraints"),
        num_variables=result.get("Solve_Metadata", {}).get("num_variables"),
    )
    events.event("validation_finished", validation_status=validation.get("status"))

    pipeline_profile = result.get("Performance_Profile", {})

    def refresh_performance_profile():
        result["Performance_Profile"] = {
            "total_seconds": round(perf_counter() - run_start, 6),
            "stages": performance_stages,
            "pipeline": pipeline_profile,
        }

    output_write_start = perf_counter()
    refresh_performance_profile()
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    record_stage("output_write", output_write_start)

    solution_status = result.get("Solution_Status", "Unknown")
    print(f"\nOptimization finished with status: {solution_status}")
    print(format_validation_report(validation))
    print(f"Output written to: {output_path}")
    if artifact_dir is not None:
        print(f"Artifacts written to: {artifact_dir}")
    sys.stdout.flush()
    sys.stderr.flush()
    events.event("artifacts_writing", artifact_dir=str(artifact_dir) if artifact_dir is not None else None)
    artifact_write_start = perf_counter()
    refresh_performance_profile()
    write_run_artifacts(artifact_dir, input_data, output_data=result, log_file=args.log_file)
    record_stage("artifact_write", artifact_write_start)
    events.event("artifacts_written", artifact_dir=str(artifact_dir) if artifact_dir is not None else None)
    refresh_performance_profile()
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    if artifact_dir is not None:
        write_json(artifact_dir / "output_snapshot.json", result)
        write_json(artifact_dir / "performance_profile.json", result["Performance_Profile"])
    return 0


def main():
    args = parse_args()
    with tee_output(args.log_file):
        return run(args)


if __name__ == "__main__":
    sys.exit(main())
