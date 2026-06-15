"""Operating-state variables, transition arcs, and active timing constraints."""

import copy

import pulp as pl


def create_operating_states_power_levels_constraints(input_data, prob, objective_terms, power, state, data, intervals, CONV, RES, PV, M):
    """Create operating-state binaries and link selected states to power limits."""
    u_2_dict = {}
    shutdown_states = {}

    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isShutdown']:
                if gen_id not in shutdown_states:
                    shutdown_states[gen_id] = []
                shutdown_states[gen_id].append(operating_state_id)

            for t in intervals:
                key = (gen_id, t, operating_state_id)
                u_2_dict[key] = pl.LpVariable(
                    name=f'u_2_{key[0] + 1}_{key[1]}_{key[2]}',
                    lowBound=0,
                    upBound=1,
                    cat='Binary',
                )

    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isEnabled']:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 1
            else:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 0

            for t in intervals[1:]:
                objective_terms += (
                        operating_state['enabled-cost']
                        * u_2_dict[(gen_id, t, operating_state_id)]
                        * input_data["Time_granularity"]
                )

    for gen in data:
        gen_id = gen['gen_id']
        for t in intervals[1:]:
            prob += power[gen_id][t] <= pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['max-power'][t - 1]
                for operating_state in gen['operating-states']
            )
            prob += power[gen_id][t] >= pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['min-power'][t - 1]
                for operating_state in gen['operating-states']
            )
            prob += pl.lpSum(
                u_2_dict[(gen_id, t, operating_state['id'])]
                for operating_state in gen['operating-states']
            ) == 1
            prob += state[gen_id][t] == 1 - pl.lpSum(
                u_2_dict[(gen_id, t, oper_id)]
                for oper_id in shutdown_states[gen_id]
            )

    return prob, objective_terms, u_2_dict, shutdown_states


def create_allowed_operating_states_transition_constraints(prob, obj, data, intervals, u_2_dict, M):
    """Add allowed operating-state transition arcs and transition costs."""
    transition_arc = {}
    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = {
                to_oper_state_data['id']: to_oper_state_data.get('transition-cost', 0)
                for to_oper_state_data in allowed_transition['transitions']
            }
            to_oper_states.setdefault(from_oper_state_id, 0)

            for t in intervals[1:]:
                arcs_from_state = []
                for to_oper_state_id, transition_cost in to_oper_states.items():
                    key = (gen_id, t, from_oper_state_id, to_oper_state_id)
                    transition_arc[key] = pl.LpVariable(
                        name=f'transition_arc_{gen_id + 1}_{t}_{from_oper_state_id}_{to_oper_state_id}',
                        lowBound=0,
                        upBound=1,
                    )
                    arcs_from_state.append(transition_arc[key])
                    prob += transition_arc[key] <= u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                    prob += transition_arc[key] <= u_2_dict[(gen_id, t, to_oper_state_id)]
                    prob += transition_arc[key] >= (
                            u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                            + u_2_dict[(gen_id, t, to_oper_state_id)]
                            - 1
                    )
                    obj += transition_cost * transition_arc[key]

                prob += pl.lpSum(arcs_from_state) == u_2_dict[(gen_id, t - 1, from_oper_state_id)]

    return prob, obj


def _finite_max_time(value, dispatch_period_count):
    """Return finite max-time limits that can bind inside the modeled horizon."""
    if value == float('inf'):
        return None
    limit = int(value)
    if limit <= 0 or limit >= dispatch_period_count:
        return None
    return limit


def create_operating_state_max_transition_time_between_states_constraints_b(
    prob, objective_terms, input_data, data, u_2_dict, IntervalCount, intervals
):
    """Add soft B-side maximum destination-state timing for operating-state transitions."""
    s_max_oper_state_time_b_left = {}
    s_max_oper_state_time_b_1 = {}
    dispatch_period_count = len(intervals) - 1

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            for next_state in allowed_transition['transitions']:
                next_state_id = next_state['id']
                if from_oper_state_id == next_state_id:
                    continue

                max_time_left = _finite_max_time(
                    next_state.get('max-transition-time-left_b', 100000000000),
                    dispatch_period_count,
                )
                max_time = _finite_max_time(
                    next_state.get('max-transition-time_b', 100000000000),
                    dispatch_period_count,
                )
                if max_time_left is None and max_time is None:
                    continue

                for t in intervals:
                    key = (gen_id, from_oper_state_id, next_state_id, t)
                    if max_time_left is not None:
                        s_max_oper_state_time_b_left[key] = pl.LpVariable(
                            name=f's_max_oper_state_time_b_left_{gen_id + 1}_{from_oper_state_id}_{next_state_id}_{t}',
                            lowBound=0,
                            upBound=1,
                            cat='Binary',
                        )
                    if max_time is not None:
                        s_max_oper_state_time_b_1[key] = pl.LpVariable(
                            name=f's_max_oper_state_time_b_1_{gen_id + 1}_{from_oper_state_id}_{next_state_id}_{t}',
                            lowBound=0,
                            upBound=1,
                            cat='Binary',
                        )

    last_period = intervals[-1]
    for gen in data:
        gen_id = gen['gen_id']
        state_by_id = {
            operating_state['id']: operating_state
            for operating_state in gen['operating-states']
        }
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            for next_state in allowed_transition['transitions']:
                next_state_id = next_state['id']
                if from_oper_state_id == next_state_id:
                    continue

                max_time_left = _finite_max_time(
                    next_state.get('max-transition-time-left_b', 100000000000),
                    dispatch_period_count,
                )
                max_time = _finite_max_time(
                    next_state.get('max-transition-time_b', 100000000000),
                    dispatch_period_count,
                )

                if max_time_left is not None and state_by_id[next_state_id]["isEnabled"]:
                    violation_period = max_time_left + 1
                    if violation_period <= last_period:
                        prob += (
                                pl.lpSum(
                                    u_2_dict[(gen_id, t, next_state_id)]
                                    for t in intervals[1:violation_period + 1]
                                )
                                <= max_time_left
                                + s_max_oper_state_time_b_left[
                                    (gen_id, from_oper_state_id, next_state_id, violation_period)
                                ]
                        )

                if max_time is not None:
                    for tt in intervals[1:]:
                        violation_period = tt + max_time
                        if violation_period > last_period:
                            continue
                        prob += (
                                pl.lpSum(
                                    u_2_dict[(gen_id, t, next_state_id)]
                                    for t in intervals[tt:violation_period + 1]
                                )
                                <= max_time + 1 - u_2_dict[(gen_id, tt - 1, from_oper_state_id)]
                                + s_max_oper_state_time_b_1[
                                    (gen_id, from_oper_state_id, next_state_id, violation_period)
                                ]
                        )

                for t in intervals[1:]:
                    key = (gen_id, from_oper_state_id, next_state_id, t)
                    if key in s_max_oper_state_time_b_left:
                        objective_terms += (
                                s_max_oper_state_time_b_left[key]
                                * input_data["Cost_parameters"]["x_max_oper_state_time_b_left"]
                        )
                    if key in s_max_oper_state_time_b_1:
                        objective_terms += (
                                s_max_oper_state_time_b_1[key]
                                * input_data["Cost_parameters"]["x_max_oper_state_time_b"]
                        )

    return prob, objective_terms


def create_min_transition_time_between_states_constraints_a(prob, objective_terms, input_data, data, u_2_dict, intervals):
    """Add source-side minimum-time constraints for operating-state transitions."""
    s_min_a_left = [
        [pl.LpVariable(name=f's_min_a_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_a_1 = [
        [pl.LpVariable(name=f's_min_a_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])
            to_oper_states.append({'id': from_oper_state_id})

            for next_state in to_oper_states:
                next_state_id = next_state['id']
                min_time_left = next_state.get('min-transition-time-left_a', 0)
                for t in intervals[1:min_time_left + 1]:
                    if (gen_id, t, next_state_id) in u_2_dict:
                        prob += (
                                u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                                + u_2_dict[(gen_id, t, next_state_id)]
                                <= 1 + s_min_a_left[gen_id][t]
                        )

            for t in intervals[1:]:
                entered_state_now = (
                        u_2_dict[(gen_id, t, from_oper_state_id)]
                        - u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                )
                for next_state in to_oper_states:
                    next_state_id = next_state['id']
                    min_time = int(next_state.get('min-transition-time_a', 0))
                    for t_prime in intervals[t:t + min_time]:
                        if (gen_id, t_prime, next_state_id) in u_2_dict:
                            prob += (
                                    u_2_dict[(gen_id, t_prime - 1, from_oper_state_id)]
                                    + u_2_dict[(gen_id, t_prime, next_state_id)]
                                    <= 2 - entered_state_now + s_min_a_1[gen_id][t_prime]
                            )

        for t in intervals[1:]:
            objective_terms += (
                    s_min_a_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a_left"]
                    + s_min_a_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a"]
            )

    return prob, objective_terms


def create_min_transition_time_between_states_constraints_b(prob, objective_terms, input_data, data, u_2_dict, intervals):
    """Add destination-side minimum-time constraints for operating-state transitions."""
    s_min_b_left = [
        [pl.LpVariable(name=f's_min_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_b_1 = [
        [pl.LpVariable(name=f's_min_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])
            to_oper_states.append({'id': from_oper_state_id})

            for next_state in to_oper_states:
                next_state_id = next_state['id']
                min_time_left = next_state.get('min-transition-time-left_b', 0)
                for t in intervals[1:min_time_left + 1]:
                    if (gen_id, t, next_state_id) in u_2_dict:
                        prob += u_2_dict[(gen_id, t, next_state_id)] + s_min_b_left[gen_id][t] >= 1

            for t in intervals[1:]:
                for next_state in to_oper_states:
                    next_state_id = next_state['id']
                    entered_state_now = (
                            u_2_dict[(gen_id, t, next_state_id)]
                            + u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                    )
                    min_time = int(next_state.get('min-transition-time_b', 0))
                    for t_prime in intervals[t:t + min_time]:
                        if (gen_id, t_prime, next_state_id) in u_2_dict:
                            prob += (
                                    u_2_dict[(gen_id, t_prime, next_state_id)]
                                    + s_min_b_1[gen_id][t_prime]
                                    >= entered_state_now - 1
                            )

        for t in intervals[1:]:
            objective_terms += (
                    s_min_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b_left"]
                    + s_min_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b"]
            )

    return prob, objective_terms


def create_state_min_time_constraints(prob, objective_terms, input_data, data, state, intervals, startup, shutdown):
    """Add unit-level minimum on/off-time constraints using startup/shutdown variables."""
    s_min_state_b_left = [
        [pl.LpVariable(name=f's_min_state_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]
    s_min_state_b_1 = [
        [pl.LpVariable(name=f's_min_state_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
        for i, _ in enumerate(data)
    ]

    for gen in data:
        gen_id = gen['gen_id']
        for allowed_transition in gen['state-transitions']:
            from_state_value = allowed_transition['from']
            to_state_value = copy.deepcopy(allowed_transition['transitions'])
            min_time_left = int(to_state_value.get('min-transition-time-left', 0))
            min_time = int(to_state_value.get('min-transition-time', 0))

            for t in intervals[1:min_time_left + 1]:
                if from_state_value == 0:
                    prob += state[gen_id][t] + s_min_state_b_left[gen_id][t] >= 1
                else:
                    prob += state[gen_id][t] - s_min_state_b_left[gen_id][t] <= 0

            if from_state_value == 0:
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += startup[gen_id][t] <= state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]
            else:
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += shutdown[gen_id][t] <= 1 - state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]

        for t in intervals[1:]:
            objective_terms += (
                    s_min_state_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states_left"]
                    + s_min_state_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states"]
            )

    return prob, objective_terms
