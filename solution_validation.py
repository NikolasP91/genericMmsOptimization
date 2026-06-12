def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_list(value):
    return value if isinstance(value, list) else []


def _max_abs(values):
    numeric_values = [abs(value) for value in values if _is_number(value)]
    return max(numeric_values) if numeric_values else 0.0


def _filtered_input_units(input_data):
    units = []
    for unit in input_data.get("Generating_Units", []):
        availability = unit.get("availability", 0)
        if isinstance(availability, list):
            if any(value != 0 for value in availability):
                units.append(unit)
        elif availability != 0:
            units.append(unit)
    return units


def _add_check(checks, name, passed, detail, severity="error"):
    checks.append(
        {
            "name": name,
            "status": "passed" if passed else "failed",
            "severity": severity,
            "detail": detail,
        }
    )


def validate_solution(input_data, output_data, tolerance=1e-3):
    checks = []
    output_units = output_data.get("Generating_Units", [])
    input_units = _filtered_input_units(input_data)
    load_forecast = input_data.get("Load_forecast", [])
    expected_periods = max(len(load_forecast) - 1, 0)

    solution_status = output_data.get("Solution_Status", "Unknown")
    _add_check(
        checks,
        "solver_status",
        solution_status == "Optimal",
        f"Solution status is {solution_status}.",
    )

    _add_check(
        checks,
        "unit_count",
        len(output_units) == len(input_units),
        f"Output has {len(output_units)} units; filtered input has {len(input_units)} units.",
    )

    length_errors = []
    for index, unit in enumerate(output_units):
        for field in ("Power", "State", "Startup", "Shutdown"):
            values = unit.get(field)
            if isinstance(values, list) and len(values) != expected_periods:
                length_errors.append(
                    f"unit {index} field {field} has {len(values)} values, expected {expected_periods}"
                )
    _add_check(
        checks,
        "period_lengths",
        not length_errors,
        "; ".join(length_errors) if length_errors else f"All period arrays have {expected_periods} values.",
    )

    load_curtailment = output_data.get("Load_Cutrailment", [])
    if isinstance(load_curtailment, list):
        load_residuals = []
        for period in range(min(expected_periods, len(load_curtailment))):
            total_power = sum(
                unit.get("Power", [])[period]
                for unit in output_units
                if len(unit.get("Power", [])) > period and _is_number(unit.get("Power", [])[period])
            )
            target_load = load_forecast[period + 1]
            residual = total_power + load_curtailment[period] - target_load
            load_residuals.append(residual)
        max_load_residual = _max_abs(load_residuals)
        _add_check(
            checks,
            "load_balance",
            max_load_residual <= tolerance,
            f"Maximum absolute load-balance residual is {max_load_residual:.6g} MW.",
        )
        max_load_curtailment = _max_abs(load_curtailment)
        _add_check(
            checks,
            "load_curtailment",
            max_load_curtailment <= tolerance,
            f"Maximum reported load curtailment is {max_load_curtailment:.6g} MW.",
            severity="warning",
        )
    else:
        _add_check(
            checks,
            "load_balance",
            not input_data.get("constraints", {}).get("load_production_balance_constraint", False),
            "Load curtailment output is unavailable.",
        )
        max_load_residual = None

    availability_violations = []
    state_power_violations = []
    for index, unit in enumerate(output_units):
        input_unit = input_units[index] if index < len(input_units) else {}
        availability = _as_list(input_unit.get("availability", []))
        powers = _as_list(unit.get("Power", []))
        states = _as_list(unit.get("State", []))
        for period, power in enumerate(powers):
            if not _is_number(power):
                continue
            if power < -tolerance:
                availability_violations.append(
                    f"unit {index} period {period + 1} has negative power {power}"
                )
            if period < len(availability) and power - availability[period] > tolerance:
                availability_violations.append(
                    f"unit {index} period {period + 1} power {power} exceeds availability {availability[period]}"
                )
            if period < len(states) and _is_number(states[period]):
                if abs(states[period]) <= tolerance and power > tolerance:
                    state_power_violations.append(
                        f"unit {index} period {period + 1} has state {states[period]} and power {power}"
                    )
    _add_check(
        checks,
        "availability_bounds",
        not availability_violations,
        "; ".join(availability_violations[:10])
        if availability_violations
        else "Power values are nonnegative and do not exceed availability.",
    )
    _add_check(
        checks,
        "state_power_consistency",
        not state_power_violations,
        "; ".join(state_power_violations[:10])
        if state_power_violations
        else "No unit produces power while reported off.",
    )

    reserve_errors = []
    for unit_index, unit in enumerate(output_units):
        for reserve_field in (
            "Primary_Active_Power_Reserves(MW)",
            "Secondary_Active_Power_Reserves(MW)",
            "Tertiary_Active_Power_Reserves(MW)",
        ):
            reserve_pair = unit.get(reserve_field, [])
            if not isinstance(reserve_pair, list):
                continue
            for direction_index, values in enumerate(reserve_pair):
                if not isinstance(values, list):
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] is not a list"
                    )
                    continue
                if len(values) != expected_periods:
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] has {len(values)} values"
                    )
                negative_values = [value for value in values if _is_number(value) and value < -tolerance]
                if negative_values:
                    reserve_errors.append(
                        f"unit {unit_index} {reserve_field}[{direction_index}] has negative values"
                    )
    _add_check(
        checks,
        "reserve_outputs",
        not reserve_errors,
        "; ".join(reserve_errors[:10]) if reserve_errors else "Reserve outputs are shaped correctly and nonnegative.",
    )

    violation_fields = [
        "primary_upwards_APRV",
        "primary_downwards_APRV",
        "secondary_upwards_APRV",
        "secondary_downwards_APRV",
        "tertiary_upwards_APRV",
        "tertiary_downwards_APRV",
    ]
    max_reported_violation = 0.0
    for field in violation_fields:
        max_reported_violation = max(max_reported_violation, _max_abs(_as_list(output_data.get(field))))
    _add_check(
        checks,
        "reported_apr_violations",
        max_reported_violation <= tolerance,
        f"Maximum reported APR violation is {max_reported_violation:.6g} MW.",
        severity="warning",
    )

    failed_errors = [check for check in checks if check["status"] == "failed" and check["severity"] == "error"]
    failed_warnings = [check for check in checks if check["status"] == "failed" and check["severity"] == "warning"]
    if failed_errors:
        report_status = "failed"
    elif failed_warnings:
        report_status = "warning"
    else:
        report_status = "passed"

    return {
        "status": report_status,
        "tolerance": tolerance,
        "max_load_balance_residual": max_load_residual,
        "max_reported_apr_violation": max_reported_violation,
        "checks": checks,
    }


def format_validation_report(report):
    lines = [f"Validation status: {report['status']}"]
    for check in report["checks"]:
        marker = "OK" if check["status"] == "passed" else check["severity"].upper()
        lines.append(f"[{marker}] {check['name']}: {check['detail']}")
    return "\n".join(lines)
