"""RDAS/DS time-resolution preprocessing for sub-period operating-state behavior."""

import copy
import math


STATE_MIN_TIME_FIELDS = (
    "min-time-enabled",
    "min-time-enabled-left",
)
STATE_MAX_TIME_FIELDS = (
    "max-time-enabled",
    "max-time-enabled-left",
)
OPERATING_TRANSITION_TIME_FIELDS = (
    "min-transition-time_a",
    "min-transition-time-left_a",
    "min-transition-time_b",
    "min-transition-time-left_b",
    "max-transition-time_b",
    "max-transition-time-left_b",
)
DEFAULT_TRANSIENT_ROLES = {
    "transient",
    "synchronization",
    "desynchronization",
    "startup",
    "shutdown",
    "rampup",
    "rampdown",
}
LARGE_TIME_SENTINEL = 100000000000


def _is_number(value):
    """Return whether a value is a non-boolean numeric scalar."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_positive_minutes(value):
    """Return finite positive minute values and ignore open-ended sentinel values."""
    if not _is_number(value) or value <= 0 or value >= LARGE_TIME_SENTINEL:
        return None
    if value == float("inf") or math.isinf(float(value)):
        return None
    return float(value)


def _time_resolution_options(input_data):
    """Read optional policy switches controlling transient-state embedding."""
    options = input_data.get("optimization_parameters", {}).get("time_resolution", {})
    if not isinstance(options, dict):
        options = {}
    return {
        "policy": options.get("subperiod_operating_state_policy", "embed_transient"),
        "transient_roles": set(options.get("transient_state_roles", DEFAULT_TRANSIENT_ROLES)),
        "allow_initial_state_embedding": bool(options.get("allow_initial_state_embedding", False)),
        "allow_operational_state_embedding": bool(options.get("allow_operational_state_embedding", False)),
        "allow_shutdown_state_embedding": bool(options.get("allow_shutdown_state_embedding", False)),
    }


def _state_role(operating_state):
    """Normalize the state_role marker used to identify transient states."""
    return str(operating_state.get("state_role", "")).strip().lower()


def _is_explicit_transient_state(operating_state, options):
    """Return whether input data explicitly marks a state as transient."""
    return (
        operating_state.get("isTransient") is True
        or operating_state.get("time_resolution_class") == "transient"
        or _state_role(operating_state) in options["transient_roles"]
    )


def _timing_values_from_state(operating_state):
    """Collect finite timing values declared directly on an operating state."""
    values = []
    for field in STATE_MIN_TIME_FIELDS + STATE_MAX_TIME_FIELDS:
        value = _finite_positive_minutes(operating_state.get(field))
        if value is not None:
            values.append((field, value))
    return values


def _transition_groups_by_from(unit):
    """Index transition groups by their source operating-state id."""
    groups = {}
    for transition_group in unit.get("operating-state-transitions", []):
        groups[transition_group.get("from")] = transition_group
    return groups


def _incoming_transition_values(unit, state_id):
    """Collect timing values on arcs entering a candidate transient state."""
    values = []
    for transition_group in unit.get("operating-state-transitions", []):
        from_state = transition_group.get("from")
        for transition in transition_group.get("transitions", []):
            if transition.get("id") != state_id:
                continue
            for field in OPERATING_TRANSITION_TIME_FIELDS:
                value = _finite_positive_minutes(transition.get(field))
                if value is not None:
                    values.append((field, value, from_state, state_id))
    return values


def _outgoing_transition_values(unit, state_id):
    """Collect timing values on arcs leaving a candidate transient state."""
    values = []
    transition_group = _transition_groups_by_from(unit).get(state_id, {})
    for transition in transition_group.get("transitions", []):
        to_state = transition.get("id")
        for field in OPERATING_TRANSITION_TIME_FIELDS:
            value = _finite_positive_minutes(transition.get(field))
            if value is not None:
                values.append((field, value, state_id, to_state))
    return values


def _timing_values_for_state(unit, operating_state):
    """Collect all state and transition durations attached to one state."""
    state_id = operating_state.get("id")
    values = [(field, value, state_id, state_id) for field, value in _timing_values_from_state(operating_state)]
    values.extend(_incoming_transition_values(unit, state_id))
    values.extend(_outgoing_transition_values(unit, state_id))
    return values


def _transition_cost(transition):
    """Read a transition cost as a number, defaulting missing costs to zero."""
    value = transition.get("transition-cost", 0)
    return float(value) if _is_number(value) else 0.0


def _without_timing_fields(transition):
    """Copy a transition while removing period-level timing fields."""
    cleaned = {
        key: copy.deepcopy(value)
        for key, value in transition.items()
        if key not in OPERATING_TRANSITION_TIME_FIELDS
    }
    for field in OPERATING_TRANSITION_TIME_FIELDS:
        cleaned.pop(field, None)
    return cleaned


def _merge_embedded_transition(incoming, outgoing, transient_state, timing_values):
    """Create a direct arc that carries the skipped transient state's metadata."""
    merged = _without_timing_fields(outgoing)
    merged["id"] = outgoing["id"]
    total_cost = _transition_cost(incoming) + _transition_cost(outgoing)
    if total_cost:
        merged["transition-cost"] = total_cost
    elif "transition-cost" in merged:
        merged["transition-cost"] = 0

    metadata = {
        "id": transient_state["id"],
        "state_role": transient_state.get("state_role"),
        "isOperational": transient_state.get("isOperational"),
        "isShutdown": transient_state.get("isShutdown"),
        "timing_minutes": [
            {
                "field": field,
                "value": value,
                "from": from_state,
                "to": to_state,
            }
            for field, value, from_state, to_state in timing_values
        ],
    }
    merged.setdefault("embedded_transient_states", [])
    merged["embedded_transient_states"].append(metadata)
    return merged


def _transition_exists(transitions, target_id):
    """Return whether a target arc is already present in a transition list."""
    return any(transition.get("id") == target_id for transition in transitions)


def _embed_state(unit, transient_state, timing_values):
    """Remove one sub-period transient state and replace paths through it with direct arcs."""
    transient_id = transient_state["id"]
    groups_by_from = _transition_groups_by_from(unit)
    outgoing_group = groups_by_from.get(transient_id)
    if not outgoing_group:
        return False, []
    outgoing_transitions = [
        transition
        for transition in outgoing_group.get("transitions", [])
        if transition.get("id") != transient_id
    ]
    if not outgoing_transitions:
        return False, []

    added_arcs = []
    new_transition_groups = []
    for transition_group in unit.get("operating-state-transitions", []):
        from_state = transition_group.get("from")
        if from_state == transient_id:
            continue

        next_transitions = []
        for transition in transition_group.get("transitions", []):
            if transition.get("id") != transient_id:
                next_transitions.append(transition)
                continue

            for outgoing in outgoing_transitions:
                target_id = outgoing.get("id")
                if target_id == from_state or _transition_exists(next_transitions, target_id):
                    continue
                merged = _merge_embedded_transition(transition, outgoing, transient_state, timing_values)
                next_transitions.append(merged)
                added_arcs.append(
                    {
                        "from": from_state,
                        "to": target_id,
                        "embedded_state_id": transient_id,
                        "transition_cost": merged.get("transition-cost", 0),
                    }
                )

        transition_group = copy.deepcopy(transition_group)
        transition_group["transitions"] = next_transitions
        new_transition_groups.append(transition_group)

    unit["operating-state-transitions"] = new_transition_groups
    unit["operating-states"] = [
        operating_state
        for operating_state in unit.get("operating-states", [])
        if operating_state.get("id") != transient_id
    ]
    return True, added_arcs


def _add_issue(report, severity, code, message, **fields):
    """Append a structured time-resolution issue record to a report."""
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    issue.update({key: value for key, value in fields.items() if value is not None})
    report["issues"].append(issue)


def _record_subperiod_timing_issues(report, unit, time_granularity):
    """Report timing data shorter than the active RDAS/DS dispatch period."""
    for operating_state in unit.get("operating-states", []):
        state_id = operating_state.get("id")
        for field, value in _timing_values_from_state(operating_state):
            if value >= time_granularity:
                continue
            severity = "warning" if field in STATE_MAX_TIME_FIELDS else "info"
            code = "subperiod_state_max_time" if field in STATE_MAX_TIME_FIELDS else "subperiod_state_min_time"
            _add_issue(
                report,
                severity,
                code,
                f"{field}={value:g} min is shorter than the DS/RDAS dispatch period.",
                unit_index=unit.get("gen_id"),
                operating_state_id=state_id,
                field=field,
                value_minutes=value,
            )

    for transition_group in unit.get("operating-state-transitions", []):
        from_state = transition_group.get("from")
        for transition in transition_group.get("transitions", []):
            to_state = transition.get("id")
            for field in OPERATING_TRANSITION_TIME_FIELDS:
                value = _finite_positive_minutes(transition.get(field))
                if value is None or value >= time_granularity:
                    continue
                severity = "warning" if field.startswith("max-") else "info"
                code = "subperiod_transition_max_time" if field.startswith("max-") else "subperiod_transition_min_time"
                _add_issue(
                    report,
                    severity,
                    code,
                    f"{field}={value:g} min is shorter than the DS/RDAS dispatch period.",
                    unit_index=unit.get("gen_id"),
                    from_operating_state_id=from_state,
                    operating_state_id=to_state,
                    field=field,
                    value_minutes=value,
                )


def prepare_operating_state_time_resolution(input_data):
    """Classify and embed eligible sub-period transient states before time discretization."""
    time_granularity = input_data.get("Time_granularity")
    report = {
        "report_type": "time_resolution",
        "scope": "RDAS_DS",
        "status": "passed",
        "dispatch_period_minutes": time_granularity,
        "policy": "embed_transient",
        "embedded_state_count": 0,
        "embedded_states": [],
        "issues": [],
    }

    if not _is_number(time_granularity) or time_granularity <= 0:
        report["status"] = "failed"
        _add_issue(
            report,
            "error",
            "invalid_time_granularity",
            "Time_granularity must be a positive number before time-resolution preprocessing.",
        )
        _add_issue_counts(report)
        input_data["Time_Resolution_Report"] = report
        return input_data

    options = _time_resolution_options(input_data)
    report["policy"] = options["policy"]
    if options["policy"] != "embed_transient":
        for unit in input_data.get("Generating_Units", []):
            _record_subperiod_timing_issues(report, unit, time_granularity)
        report["status"] = _status_from_issues(report)
        _add_issue_counts(report)
        input_data["Time_Resolution_Report"] = report
        return input_data

    for unit in input_data.get("Generating_Units", []):
        state_by_id = {
            operating_state.get("id"): operating_state
            for operating_state in unit.get("operating-states", [])
        }
        for operating_state in list(state_by_id.values()):
            if not isinstance(operating_state, dict) or "id" not in operating_state:
                continue
            if not _is_explicit_transient_state(operating_state, options):
                continue

            timing_values = _timing_values_for_state(unit, operating_state)
            positive_durations = [value for _, value, _, _ in timing_values]
            if not positive_durations:
                _add_issue(
                    report,
                    "info",
                    "transient_state_without_duration",
                    "Explicit transient state has no positive timing data, so it remains period-level.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            if max(positive_durations) >= time_granularity:
                _add_issue(
                    report,
                    "info",
                    "transient_state_not_subperiod",
                    "Explicit transient state has timing at least as long as the dispatch period, so it remains period-level.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                    max_duration_minutes=max(positive_durations),
                )
                continue
            if operating_state.get("isEnabled") and not options["allow_initial_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "initial_transient_state_not_embedded",
                    "Initial enabled operating state cannot be embedded safely in an hourly DS/RDAS model.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            if operating_state.get("isOperational") and not options["allow_operational_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "operational_transient_state_not_embedded",
                    "Operational transient state was not embedded because it may carry reserve/dispatch capability.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue
            if operating_state.get("isShutdown") and not options["allow_shutdown_state_embedding"]:
                _add_issue(
                    report,
                    "warning",
                    "shutdown_transient_state_not_embedded",
                    "Shutdown transient state was not embedded because it is part of the offline state set.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue

            embedded, added_arcs = _embed_state(unit, operating_state, timing_values)
            if not embedded:
                _add_issue(
                    report,
                    "warning",
                    "transient_state_not_embeddable",
                    "Transient state could not be embedded because it lacks usable incoming/outgoing transition paths.",
                    unit_index=unit.get("gen_id"),
                    operating_state_id=operating_state["id"],
                )
                continue

            report["embedded_states"].append(
                {
                    "unit_index": unit.get("gen_id"),
                    "operating_state_id": operating_state["id"],
                    "state_role": operating_state.get("state_role"),
                    "max_duration_minutes": max(positive_durations),
                    "added_transition_arcs": added_arcs,
                }
            )
            _add_issue(
                report,
                "info",
                "transient_state_embedded",
                "Sub-period transient operating state was embedded into allowed transition arcs.",
                unit_index=unit.get("gen_id"),
                operating_state_id=operating_state["id"],
            )

        _record_subperiod_timing_issues(report, unit, time_granularity)

    report["embedded_state_count"] = len(report["embedded_states"])
    report["status"] = _status_from_issues(report)
    _add_issue_counts(report)
    input_data["Time_Resolution_Report"] = report
    return input_data


def _status_from_issues(report):
    """Derive report status from warning/error severities."""
    severities = {issue.get("severity") for issue in report.get("issues", [])}
    if "error" in severities:
        return "failed"
    if "warning" in severities:
        return "warning"
    return "passed"


def _add_issue_counts(report):
    """Attach issue severity counters to the time-resolution report."""
    issues = report.get("issues", [])
    report["issue_count"] = len(issues)
    report["warning_count"] = sum(1 for issue in issues if issue.get("severity") == "warning")
    report["error_count"] = sum(1 for issue in issues if issue.get("severity") == "error")
    report["info_count"] = sum(1 for issue in issues if issue.get("severity") == "info")
