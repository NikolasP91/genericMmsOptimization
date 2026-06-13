def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_list(value):
    return value if isinstance(value, list) else []


def _max_abs(values):
    numeric_values = [abs(value) for value in values if _is_number(value)]
    return max(numeric_values) if numeric_values else 0.0


def _sum_positive(values, tolerance):
    return sum(value for value in values if _is_number(value) and value > tolerance)


def _add_warning(warnings, code, message, severity="warning", **fields):
    record = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    record.update({key: value for key, value in fields.items() if value is not None})
    warnings.append(record)


def _error_message(error_report):
    if error_report.get("error"):
        return error_report["error"]
    errors = error_report.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(error) for error in errors[:5])
    return "Execution failed."


def build_warning_report(input_data, output_data, validation_report=None, tolerance=1e-3):
    warnings = []

    load_curtailment = _as_list(output_data.get("Load_Cutrailment"))
    for period, value in enumerate(load_curtailment, start=1):
        if _is_number(value) and abs(value) > tolerance:
            _add_warning(
                warnings,
                "load_curtailment",
                "Load curtailment or augmentation is nonzero.",
                period=period,
                value_mw=value,
            )

    for field in (
        "primary_upwards_APRV",
        "primary_downwards_APRV",
        "secondary_upwards_APRV",
        "secondary_downwards_APRV",
        "tertiary_upwards_APRV",
        "tertiary_downwards_APRV",
    ):
        for period, value in enumerate(_as_list(output_data.get(field)), start=1):
            if _is_number(value) and abs(value) > tolerance:
                _add_warning(
                    warnings,
                    "reserve_requirement_violation",
                    f"{field} is nonzero.",
                    period=period,
                    field=field,
                    value_mw=value,
                )

    reserve_report = output_data.get("Reserve_Monitoring_Report", {})
    for period_record in reserve_report.get("periods", []):
        period = period_record.get("period")
        for reserve_name, directions in period_record.get("reserves", {}).items():
            for direction, metrics in directions.items():
                if metrics.get("status") == "shortfall":
                    _add_warning(
                        warnings,
                        "reserve_shortfall",
                        f"{reserve_name} {direction} reserve shortfall.",
                        period=period,
                        reserve=reserve_name,
                        direction=direction,
                        required_mw=metrics.get("required_mw"),
                        provided_mw=metrics.get("provided_mw"),
                        shortfall_mw=metrics.get("shortfall_mw"),
                    )

    if validation_report:
        for check in validation_report.get("checks", []):
            if check.get("status") == "failed":
                _add_warning(
                    warnings,
                    f"validation_{check.get('name', 'check')}",
                    check.get("detail", "Validation check failed."),
                    severity=check.get("severity", "error"),
                )

    return {
        "status": "passed" if not warnings else "warning",
        "tolerance": tolerance,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def build_diagnostics_report(input_data, output_data=None, validation_report=None, error_report=None, tolerance=1e-3):
    output_data = output_data or {}
    validation_report = validation_report or {}
    solve_metadata = output_data.get("Solve_Metadata", {})
    warning_report = output_data.get("Warning_Report") or build_warning_report(
        input_data, output_data, validation_report, tolerance
    )
    solver_status = output_data.get("Solution_Status")

    issue_records = []
    if error_report:
        issue_records.append(
            {
                "stage": error_report.get("stage", "unknown"),
                "severity": "error",
                "message": _error_message(error_report),
            }
        )
    if solver_status and solver_status != "Optimal":
        issue_records.append(
            {
                "stage": "solve",
                "severity": "error",
                "message": f"Solver status is {solver_status}.",
            }
        )

    for check in validation_report.get("checks", []):
        if check.get("status") == "failed":
            issue_records.append(
                {
                    "stage": "validation",
                    "severity": check.get("severity", "error"),
                    "name": check.get("name"),
                    "message": check.get("detail"),
                }
            )

    slack_summary = {
        "max_load_curtailment_mw": _max_abs(_as_list(output_data.get("Load_Cutrailment"))),
        "max_reported_apr_violation_mw": max(
            _max_abs(_as_list(output_data.get(field)))
            for field in (
                "primary_upwards_APRV",
                "primary_downwards_APRV",
                "secondary_upwards_APRV",
                "secondary_downwards_APRV",
                "tertiary_upwards_APRV",
                "tertiary_downwards_APRV",
            )
        ),
        "total_positive_res_curtailment_mwh": 0.0,
    }
    curtailment_report = output_data.get("RES_Curtailment_Report", {})
    if curtailment_report:
        slack_summary["total_positive_res_curtailment_mwh"] = curtailment_report.get(
            "summary", {}
        ).get("curtailed_mwh", 0.0)

    bottleneck_sections = sorted(
        solve_metadata.get("constraint_sections", []),
        key=lambda row: row.get("build_seconds", 0),
        reverse=True,
    )[:5]

    status = (
        "failed"
        if error_report or solver_status not in (None, "Optimal") or validation_report.get("status") == "failed"
        else "passed"
    )
    if status == "passed" and warning_report.get("warning_count", 0) > 0:
        status = "warning"

    return {
        "status": status,
        "solver_status": output_data.get("Solution_Status"),
        "validation_status": validation_report.get("status"),
        "tolerance": tolerance,
        "issue_count": len(issue_records),
        "issues": issue_records,
        "slack_summary": slack_summary,
        "warning_summary": {
            "status": warning_report.get("status"),
            "warning_count": warning_report.get("warning_count", 0),
        },
        "model_summary": {
            "solver": solve_metadata.get("solver"),
            "objective_value": solve_metadata.get("objective_value"),
            "big_m": solve_metadata.get("big_m"),
            "num_constraints": solve_metadata.get("num_constraints"),
            "num_variables": solve_metadata.get("num_variables"),
        },
        "slowest_constraint_sections": bottleneck_sections,
    }
