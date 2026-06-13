THERMAL_PREFIX = "Therm"
COST_CURVE_FIELD = "var_gen_cost(euro/MW)"
DEFAULT_COST_TIME_UNIT = "euro_per_mw_per_minute"


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_list(value):
    if not isinstance(value, list):
        return None
    if any(not _is_number(item) for item in value):
        return None
    return [float(item) for item in value]


def _max_positive(value):
    if isinstance(value, list):
        numeric_values = [float(item) for item in value if _is_number(item)]
        return max(numeric_values) if numeric_values else 0.0
    if _is_number(value):
        return max(0.0, float(value))
    return 0.0


def _unit_path(index):
    return f"Generating_Units[{index}].{COST_CURVE_FIELD}"


def _add_issue(issues, severity, code, message, unit_index, gen_id=None, **fields):
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
        "unit_index": unit_index,
        "gen_id": gen_id,
    }
    issue.update({key: value for key, value in fields.items() if value is not None})
    issues.append(issue)


def _unit_status(issues):
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _report_status(issues):
    severities = {issue["severity"] for issue in issues}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _cost_at_breakpoints(base_cost, segment_slopes, segment_widths):
    costs = [base_cost]
    running_cost = base_cost
    for slope, width in zip(segment_slopes, segment_widths):
        running_cost += slope * width
        costs.append(running_cost)
    return [round(value, 6) for value in costs]


def is_non_decreasing(values, tolerance=1e-6):
    return all(right + tolerance >= left for left, right in zip(values, values[1:]))


def cost_curve_time_multiplier(input_data):
    """Return the multiplier applied to cost-curve coefficients in the objective.

    The legacy input data has historically multiplied thermal coefficients by
    Time_granularity directly. For academically standard EUR/MWh slopes, set
    optimization_parameters.cost_curve_time_unit to "euro_per_mwh".
    """

    parameters = input_data.get("optimization_parameters", {})
    if _is_number(parameters.get("cost_curve_time_multiplier")):
        return float(parameters["cost_curve_time_multiplier"])

    time_granularity = input_data.get("Time_granularity", 1.0)
    time_granularity = float(time_granularity) if _is_number(time_granularity) else 1.0
    unit = parameters.get("cost_curve_time_unit", DEFAULT_COST_TIME_UNIT)

    if unit == "euro_per_mwh":
        return time_granularity / 60.0
    if unit == "euro_per_dispatch_period":
        return 1.0
    return time_granularity


def parse_thermal_cost_curve(unit):
    curve = unit.get(COST_CURVE_FIELD, [[], []])
    if not isinstance(curve, list) or len(curve) != 2:
        return [], [], [], None
    breakpoints = _numeric_list(curve[0]) or []
    coefficients = _numeric_list(curve[1]) or []
    if len(breakpoints) < 2 or len(coefficients) != len(breakpoints):
        return breakpoints, coefficients, [], None
    widths = [right - left for left, right in zip(breakpoints, breakpoints[1:])]
    slopes = coefficients[1:]
    return breakpoints, coefficients, widths, is_non_decreasing(slopes)


def _as_list(value):
    return value if isinstance(value, list) else []


def _value_at(values, index, default=0.0):
    if isinstance(values, list) and index < len(values) and _is_number(values[index]):
        return float(values[index])
    return default


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


def _period_count(output_data):
    units = output_data.get("Generating_Units", [])
    if not units:
        return 0
    return max(len(_as_list(unit.get("Power"))) for unit in units)


def _segment_dispatch(power, state, breakpoints, widths):
    remaining = max(0.0, power - breakpoints[0] * state)
    dispatch = []
    for width in widths:
        segment_mw = min(max(0.0, width), remaining)
        dispatch.append(segment_mw)
        remaining -= segment_mw
    return dispatch, max(0.0, remaining)


def build_thermal_cost_report(input_data, output_data):
    input_units = _filtered_input_units(input_data)
    output_units = output_data.get("Generating_Units", [])
    periods = _period_count(output_data)
    multiplier = cost_curve_time_multiplier(input_data)
    entries = []
    summary = {"thermal_cost": 0.0, "unpriced_mw": 0.0}

    for unit_index, input_unit in enumerate(input_units):
        comments = input_unit.get("comments", "")
        if not isinstance(comments, str) or not comments.startswith(THERMAL_PREFIX):
            continue
        if unit_index >= len(output_units):
            continue

        output_unit = output_units[unit_index]
        breakpoints, coefficients, widths, is_convex = parse_thermal_cost_curve(input_unit)
        if not breakpoints or len(coefficients) != len(breakpoints):
            continue

        slopes = coefficients[1:]
        for period in range(periods):
            power = _value_at(output_unit.get("Power"), period)
            state = _value_at(output_unit.get("State"), period)
            segment_dispatch, unpriced_mw = _segment_dispatch(power, state, breakpoints, widths)
            base_cost = coefficients[0] * state * multiplier
            segments = []
            segment_cost_total = 0.0
            for segment_index, (segment_mw, slope, width) in enumerate(
                zip(segment_dispatch, slopes, widths),
                start=1,
            ):
                segment_cost = segment_mw * slope * multiplier
                segment_cost_total += segment_cost
                segments.append(
                    {
                        "segment": segment_index,
                        "width_mw": round(max(0.0, width), 6),
                        "dispatch_mw": round(segment_mw, 6),
                        "marginal_cost": round(slope, 6),
                        "cost": round(segment_cost, 6),
                    }
                )

            total_cost = base_cost + segment_cost_total
            summary["thermal_cost"] += total_cost
            summary["unpriced_mw"] += unpriced_mw
            entries.append(
                {
                    "period": period + 1,
                    "unit_index": unit_index,
                    "gen_id": output_unit.get("gen_id", input_unit.get("gen_id", unit_index)),
                    "state": round(state, 6),
                    "power_mw": round(power, 6),
                    "formulation": "convex_incremental_pwl"
                    if is_convex
                    else "nonconvex_incremental_pwl",
                    "base_cost": round(base_cost, 6),
                    "segments": segments,
                    "unpriced_mw": round(unpriced_mw, 6),
                    "total_cost": round(total_cost, 6),
                }
            )

    summary["thermal_cost"] = round(summary["thermal_cost"], 6)
    summary["unpriced_mw"] = round(summary["unpriced_mw"], 6)
    return {
        "report_type": "thermal_cost_report",
        "cost_time_multiplier": round(multiplier, 6),
        "summary": summary,
        "entries": entries,
    }


def audit_thermal_cost_curves(input_data, tolerance=1e-6):
    """Audit thermal-unit PWL production-cost curves used by the MIP.

    The current formulation expects var_gen_cost(euro/MW) = [breakpoints, costs],
    where costs[0] is the base cost at the first breakpoint and costs[1:] are
    marginal segment costs for consecutive breakpoint intervals.
    """

    units = []
    issues = []

    for unit_index, unit in enumerate(input_data.get("Generating_Units", [])):
        comments = unit.get("comments", "")
        if not isinstance(comments, str) or not comments.startswith(THERMAL_PREFIX):
            continue

        gen_id = unit.get("gen_id", unit_index)
        unit_issues = []
        curve = unit.get(COST_CURVE_FIELD)
        unit_record = {
            "unit_index": unit_index,
            "gen_id": gen_id,
            "comments": comments,
            "status": "passed",
            "field": _unit_path(unit_index),
            "formulation": "incremental_piecewise_linear",
            "recommended_model": None,
            "quadratic_source_coefficients_present": False,
            "quadratic_source_verified": False,
            "breakpoints_mw": [],
            "base_cost_coefficient": None,
            "segment_slopes": [],
            "segments": [],
            "cost_at_breakpoints": [],
        }

        quadratic_coefficients = unit.get("quadratic_cost_coefficients") or unit.get(
            "quadratic_cost(euro)"
        )
        if isinstance(quadratic_coefficients, dict):
            unit_record["quadratic_source_coefficients_present"] = all(
                key in quadratic_coefficients for key in ("a", "b", "c")
            )

        if not isinstance(curve, list) or len(curve) != 2:
            _add_issue(
                unit_issues,
                "error",
                "missing_or_malformed_cost_curve",
                f"{_unit_path(unit_index)} must contain [breakpoints, cost_coefficients].",
                unit_index,
                gen_id,
            )
            unit_record["status"] = _unit_status(unit_issues)
            unit_record["issues"] = unit_issues
            units.append(unit_record)
            issues.extend(unit_issues)
            continue

        breakpoints = _numeric_list(curve[0])
        costs = _numeric_list(curve[1])
        if breakpoints is None or costs is None:
            _add_issue(
                unit_issues,
                "error",
                "non_numeric_cost_curve",
                f"{_unit_path(unit_index)} breakpoints and coefficients must be numeric lists.",
                unit_index,
                gen_id,
            )
            unit_record["status"] = _unit_status(unit_issues)
            unit_record["issues"] = unit_issues
            units.append(unit_record)
            issues.extend(unit_issues)
            continue

        unit_record["breakpoints_mw"] = [round(value, 6) for value in breakpoints]
        unit_record["base_cost_coefficient"] = round(costs[0], 6) if costs else None
        unit_record["segment_slopes"] = [round(value, 6) for value in costs[1:]]

        if len(breakpoints) < 2:
            _add_issue(
                unit_issues,
                "error",
                "too_few_cost_breakpoints",
                f"{_unit_path(unit_index)} must have at least two breakpoints.",
                unit_index,
                gen_id,
            )
        if len(costs) != len(breakpoints):
            _add_issue(
                unit_issues,
                "error",
                "cost_curve_length_mismatch",
                f"{_unit_path(unit_index)} coefficients must match breakpoint count.",
                unit_index,
                gen_id,
                breakpoint_count=len(breakpoints),
                coefficient_count=len(costs),
            )

        segment_widths = []
        if len(breakpoints) >= 2:
            for segment_index, (left, right) in enumerate(zip(breakpoints, breakpoints[1:])):
                width = right - left
                segment_widths.append(width)
                if width <= tolerance:
                    _add_issue(
                        unit_issues,
                        "error",
                        "non_increasing_cost_breakpoints",
                        "Thermal cost-curve breakpoints must be strictly increasing.",
                        unit_index,
                        gen_id,
                        segment_index=segment_index,
                        left_mw=left,
                        right_mw=right,
                    )

        for cost_index, coefficient in enumerate(costs):
            if coefficient < -tolerance:
                _add_issue(
                    unit_issues,
                    "error",
                    "negative_cost_coefficient",
                    "Thermal cost-curve coefficients must be nonnegative.",
                    unit_index,
                    gen_id,
                    coefficient_index=cost_index,
                    value=coefficient,
                )

        if len(costs) >= 2:
            slopes = costs[1:]
            unit_record["recommended_model"] = (
                "convex_incremental_pwl"
                if is_non_decreasing(slopes, tolerance=tolerance)
                else "nonconvex_incremental_pwl"
            )
            for segment_index, (left, right) in enumerate(zip(slopes, slopes[1:]), start=1):
                if right + tolerance < left:
                    _add_issue(
                        unit_issues,
                        "warning",
                        "nonconvex_marginal_costs",
                        (
                            "PWL marginal costs decrease between adjacent segments; "
                            "this is not a convex quadratic-cost approximation."
                        ),
                        unit_index,
                        gen_id,
                        segment_index=segment_index,
                        previous_slope=left,
                        next_slope=right,
                    )

        if breakpoints:
            min_power = _max_positive(unit.get("min_power(MW)"))
            if abs(breakpoints[0] - min_power) > tolerance:
                _add_issue(
                    unit_issues,
                    "warning",
                    "first_breakpoint_differs_from_min_power",
                    "First thermal cost-curve breakpoint differs from unit minimum power.",
                    unit_index,
                    gen_id,
                    first_breakpoint_mw=breakpoints[0],
                    min_power_mw=min_power,
                )

            max_power = _max_positive(unit.get("max_power(MW)"))
            if breakpoints[-1] + tolerance < max_power:
                _add_issue(
                    unit_issues,
                    "warning",
                    "cost_curve_does_not_cover_max_power",
                    (
                        "Last thermal cost-curve breakpoint is below the unit's declared "
                        "maximum power. Production-cost curves should normally cover the "
                        "full technical dispatch range, while availability limits should "
                        "remain period-specific constraints."
                    ),
                    unit_index,
                    gen_id,
                    last_breakpoint_mw=breakpoints[-1],
                    declared_max_power_mw=max_power,
                )
            max_availability = _max_positive(unit.get("availability"))
            if breakpoints[-1] + tolerance < max_availability:
                _add_issue(
                    unit_issues,
                    "warning",
                    "cost_curve_does_not_cover_availability",
                    (
                        "Last thermal cost-curve breakpoint is below the unit's maximum "
                        "available power in this input scenario, so dispatch above the "
                        "curve endpoint would be impossible or unpriced."
                    ),
                    unit_index,
                    gen_id,
                    last_breakpoint_mw=breakpoints[-1],
                    max_available_power_mw=max_availability,
                )

        if len(breakpoints) >= 2 and len(costs) == len(breakpoints):
            slopes = costs[1:]
            positive_widths = [max(0.0, width) for width in segment_widths]
            unit_record["cost_at_breakpoints"] = _cost_at_breakpoints(
                costs[0], slopes, positive_widths
            )
            for segment_index, (left, right, slope, width) in enumerate(
                zip(breakpoints, breakpoints[1:], slopes, positive_widths),
                start=1,
            ):
                unit_record["segments"].append(
                    {
                        "segment": segment_index,
                        "from_mw": round(left, 6),
                        "to_mw": round(right, 6),
                        "width_mw": round(width, 6),
                        "marginal_cost": round(slope, 6),
                    }
                )

        unit_record["status"] = _unit_status(unit_issues)
        unit_record["issues"] = unit_issues
        units.append(unit_record)
        issues.extend(unit_issues)

    return {
        "report_type": "thermal_cost_curve_audit",
        "status": _report_status(issues),
        "tolerance": tolerance,
        "thermal_unit_count": len(units),
        "issue_count": len(issues),
        "warning_count": len([issue for issue in issues if issue["severity"] == "warning"]),
        "error_count": len([issue for issue in issues if issue["severity"] == "error"]),
        "interpretation": (
            "The active MIP uses an incremental piecewise-linear production-cost "
            "formulation for thermal units. The audit verifies the supplied PWL "
            "data and checks whether marginal segment costs are consistent with a "
            "convex quadratic-cost approximation."
        ),
        "units": units,
        "issues": issues,
    }
