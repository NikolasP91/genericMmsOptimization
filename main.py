#!/usr/bin/env python
import argparse
import json
import sys
from pathlib import Path

from RV_genericMmsOptimization import parse_and_execute_optimization
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
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)
    output_path = Path(args.output)

    print(f"Loading configuration from: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        input_data = json.load(f)

    if args.time_limit is not None:
        input_data.setdefault("optimization_parameters", {}).setdefault("early_stopping", {})[
            "time_limit"
        ] = args.time_limit
        print(f"Using solver time limit: {args.time_limit} seconds")
    input_data.setdefault("optimization_parameters", {})["solver"] = args.solver
    print(f"Using solver: {args.solver}")

    try:
        result = parse_and_execute_optimization(input_data)
    except Exception as e:
        print(f"\nError during optimization: {e}")
        import traceback

        traceback.print_exc()
        return 1

    validation = validate_solution(input_data, result, tolerance=args.validation_tolerance)
    result["Validation"] = validation

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    solution_status = result.get("Solution_Status", "Unknown")
    print(f"\nOptimization finished with status: {solution_status}")
    print(format_validation_report(validation))
    print(f"Output written to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
