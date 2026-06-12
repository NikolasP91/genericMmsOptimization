# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling kernel.

import numpy as np
import pandas as pd
import pulp as pl


def create_operating_states_power_levels_constraints(input_data, prob, objective_terms, power, state, data, intervals, CONV, RES, PV, M):
    # defines in which thermal state we are and how it is connected to the respective power levels
    # u_2 = [[[pl.LpVariable(name=f'u_2_{i + 1}_{t}_{s_2_index}', lowBound=0, upBound=1, cat='Binary') for s_2_index, _ in
    #          enumerate(gen['operating-states'])] for t in intervals] for i, gen in enumerate(data)]

    u_2_dict = {}
    shutdown_states = {}
    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            # Create a unique tuple key
            if operating_state['isShutdown']:  # 'isShutdown' is the key for the  state that corresponds to off state
                # Add the operating_state to the list for this gen_id
                if gen_id not in shutdown_states:
                    shutdown_states[gen_id] = []
                else:
                    pass
                shutdown_states[gen_id].append(operating_state_id)
            else:
                pass
            # At this point, 'shutdown_states' contains the desired mapping
            for t in intervals:
                key = (gen_id, t, operating_state_id)
                # Define the LpVariable and assign it to the key in the dictionary
                u_2_dict[key] = pl.LpVariable(name=f'u_2_{key[0]+1}_{key[1]}_{key[2]}', lowBound=0, upBound=1, cat='Binary')
    # Now u_2_dict contains all our variables, accessible by the unique tuple keys


    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            # transition to new execution of the scheduling program
            if operating_state['isEnabled']:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 1
            else:
                prob += u_2_dict[(gen_id, 0, operating_state_id)] == 0
            for t in intervals[1:]:
                objective_terms += operating_state['enabled-cost'] * u_2_dict[(gen_id, t, operating_state_id)] * input_data["Time_granularity"]

    for gen in data:
        gen_id = gen['gen_id']
        for t in intervals[1:]:
            # M = 10000
            # power levels
            prob += power[gen_id][t] <= pl.lpSum(u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['max-power'][t-1] for operating_state in gen['operating-states'])
            prob += power[gen_id][t] >= pl.lpSum(u_2_dict[(gen_id, t, operating_state['id'])] * operating_state['min-power'][t-1] for operating_state in gen['operating-states'])
            # each unit is each hour in only 1 operating state
            prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state['id'])]for operating_state in gen['operating-states']) == 1
            prob += state[gen_id][t] == 1 - pl.lpSum(u_2_dict[(gen_id, t, oper_id)] for oper_id in shutdown_states[gen_id])

    return prob, objective_terms, u_2_dict, shutdown_states


def create_allowed_operating_states_transition_constraints(prob, obj, data, intervals, u_2_dict, M):
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

                # If the unit was in this state at t-1, exactly one allowed/stay
                # transition must be selected at t.
                prob += pl.lpSum(arcs_from_state) == u_2_dict[(gen_id, t - 1, from_oper_state_id)]

    # print(data)
    return prob, obj


def create_operating_state_max_time_constraints(prob, data, u_2_dict, IntervalCount, intervals, CONV, RES):

    #  περιορισμός μέγιστου συνεχόμενου χρόνου λειτουργίας στην αρχή του 24ώρου/15λέπτου κλπ
    for gen in data:
        gen_id = gen['gen_id']
        if gen_id in CONV+RES:
            for operating_state in gen['operating-states']:
                operating_state_id = operating_state['id']
                # print(operating_state["max-time-enabled-left"])
                # print(u_2_dict[(gen_id, t, operating_state_id)])
                prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in intervals[1:operating_state["max-time-enabled-left"] + operating_state["isEnabled"] + 1]) <= operating_state["max-time-enabled-left"]
                # print(operating_state["max-time-enabled-left"])

                #  prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in
                #                  intervals[1:int(operating_state["max-time-enabled-left"]) + 2]) <= int(             ## * operating_state["isEnabled"]
                #     operating_state["max-time-enabled-left"]) * 100 u_2_dict[(gen_id, t, operating_state_id
            # if operating_state["max-time-enabled"]
                for tt in intervals[1:-operating_state["max-time-enabled"]]:
                    prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in intervals[tt: tt + operating_state["max-time-enabled"] + 1]) <= operating_state["max-time-enabled"]
    return prob


def create_operating_state_min_time_constraints(prob, data, u_2_dict, IntervalCount, intervals):
    # for gen in data:
    #     for s_2_index, _ in enumerate(data[i]["Therm_state_min_time_on"]):
    for gen in data:
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']

            prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in
                             intervals[1:int(operating_state["min-time-enabled-left"]) + 1]) >= int(operating_state["min-time-enabled-left"]) * operating_state['isEnabled']

        #     Διαχρονικός περιορισμός λειτουργίας
        # for s_2_index, _ in enumerate(data[i]["Therm_state_min_time_on"]):
            for tt in intervals[int(operating_state["min-time-enabled-left"] + 1):(IntervalCount - operating_state["min-time-enabled"] + 1)]:
                prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in intervals[tt:(tt + operating_state["min-time-enabled"])]) >= \
                        operating_state["min-time-enabled"] * (u_2_dict[(gen_id, tt, operating_state_id)] - u_2_dict[(gen_id, tt-1, operating_state_id)])

        # for s_2_index, _ in enumerate(data[i]["Therm_state_min_time_on"]):
        #     for tt in intervals[(intervalCount - data[i]["Therm_state_min_time_on"][s_2_index] + 1):]:
        #         prob += pl.lpSum(u_2[i][t][s_2_index] for t in intervals[tt:]) >= u_2[i][tt][s_2_index] - \
        #                 u_2[i][tt - 1][s_2_index]

            #     Διαχρονικός περιορισμός λειτουργίας στo τέλος του 24ώρου

            for tt in intervals[(IntervalCount - operating_state["min-time-enabled"] + 1):]:
                prob += pl.lpSum(u_2_dict[(gen_id, t, operating_state_id)] for t in intervals[tt:]) >= (u_2_dict[(gen_id, tt, operating_state_id)] - u_2_dict[(gen_id, tt-1, operating_state_id)]) * (IntervalCount - tt + 1)
    return prob


def create_min_transition_time_between_states_constraints_a(prob, objective_terms, input_data, data, u_2_dict, intervals):
    s_min_a_left = [[pl.LpVariable(name=f's_min_a_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    s_min_a_1 = [[pl.LpVariable(name=f's_min_a_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]

    import copy
    for gen in data:
        # print(gen)
        gen_id = gen['gen_id']
        # print('')
        # print('gen_id: ', gen_id)
        # for t in intervals[1:]:
        #     print('gen_id: ', gen_id)
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
            to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state

            # print('from: ', from_oper_state_id, 'to: ', to_oper_states)

            # at this point we have 1 'from' id and 1 or more 'to' ids
            # for the start of the scheduling period
            for next_state in to_oper_states:
                next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state ['min-transition-time']
                min_time_left = next_state.get('min-transition-time-left_a', 0)  # if min-time key does not exist, use 0 as the default value for min-time
                # print(next_state_id, min_time_left)

                # Ensure minimum time in current state before transitioning to next state
                for t in intervals[1:min_time_left + 1]:
                    if (gen_id, t, next_state_id) in u_2_dict:
                        # we cannot transition to the specific next_state before min transition time elapses
                        prob += u_2_dict[(gen_id, t-1, from_oper_state_id)] + u_2_dict[(gen_id, t, next_state_id)] <= 1 + s_min_a_left[gen_id][t]
                        # objective_terms += s_min_a_left[gen_id][t] * (min_time_left - t + 1) * 1000000

            for t in intervals[1:]:  # Start from 1 as we compare with the previous interval
                # Check if the generator entered the state at this interval
                entered_state_now = (u_2_dict[(gen_id, t, from_oper_state_id)] - u_2_dict[(gen_id, t-1, from_oper_state_id)])
                for next_state in to_oper_states:  # there must be an operating state id when we define the "to" state
                    next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
                    min_time = int(next_state.get('min-transition-time_a', 0))  # Convert to int, if min-time key does not exist, use 0 as the default value for min-time
                    # Ensure minimum time in current state before transitioning to next state
                    for t_prime in intervals[t:t + min_time]:
                        if (gen_id, t_prime, next_state_id) in u_2_dict:
                            # we cannot transition to the specific next_state before min transition time elapses
                            prob += u_2_dict[(gen_id, t_prime-1, from_oper_state_id)] + u_2_dict[(gen_id, t_prime, next_state_id)] <= 2 - entered_state_now + s_min_a_1[gen_id][t_prime]
                            # objective_terms += s_min_a_1[gen_id][t_prime] * (min_time - (t_prime - t)) * 1000000

        for t in intervals[1:]:
            objective_terms += s_min_a_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a_left"] + s_min_a_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_a"]


    return prob, objective_terms


def create_min_transition_time_between_states_constraints_b(prob,  objective_terms, input_data, data, u_2_dict, intervals):
    s_min_b_left = [[pl.LpVariable(name=f's_min_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    s_min_b_1 = [[pl.LpVariable(name=f's_min_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    import copy
    for gen in data:
        # print(gen)
        gen_id = gen['gen_id']
        # print('')
        # print('gen_id: ', gen_id)
        # for t in intervals[1:]:
        #     print('gen_id: ', gen_id)
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
            to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state
            # print('from: ', from_oper_state_id, 'to: ', to_oper_states)
            # at this point we have 1 'from' id and 1 or more 'to' ids
            # for the start of the scheduling period
            for next_state in to_oper_states:
                next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state ['min-transition-time']
                min_time_left = next_state.get('min-transition-time-left_b', 0)  # if min-time key does not exist, use 0 as the default value for min-time
                # print(next_state_id, min_time_left)
                # Ensure minimum time in current state before transitioning to next state
                for t in intervals[1:min_time_left + 1]:
                    if (gen_id, t, next_state_id) in u_2_dict:
                        # we must remain in next_state until min_time_left time elapses
                        prob += u_2_dict[(gen_id, t, next_state_id)] + s_min_b_left[gen_id][t] >= 1
                        # objective_terms += s_min_b_left[gen_id, t] * 1000000

            for t in intervals[1:]:  # Start from 1 as we compare with the previous interval
                # Check if the generator entered the state at this interval
                for next_state in to_oper_states:
                    next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
                    entered_state_now = (u_2_dict[(gen_id, t, next_state_id)] + u_2_dict[(gen_id, t - 1, from_oper_state_id)])
                    min_time = int(next_state.get('min-transition-time_b', 0))  # Convert to int, if min-time key does not exist, use 0 as the default value for min-time
                    # Ensure minimum time in next state
                    for t_prime in intervals[t:t + min_time]:
                        if (gen_id, t_prime, next_state_id) in u_2_dict:
                            # we must remain in next_state until min_time time elapses
                            prob += u_2_dict[(gen_id, t_prime, next_state_id)] + s_min_b_1[gen_id][t_prime] >= entered_state_now - 1
                            # objective_terms += s_min_b_1[gen_id][t_prime] * 1000000
        for t in intervals[1:]:
            objective_terms += s_min_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b_left"] + s_min_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_oper_states_b"]
    return prob,  objective_terms


def create_max_transition_time_between_states_constraints_b(prob, objective_terms, input_data, data, u_2_dict, IntervalCount, intervals):
    s_max_b_left = [[pl.LpVariable(name=f's_max_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    s_max_b_1 = [[pl.LpVariable(name=f's_max_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    import copy
    for gen in data:
        gen_id = gen['gen_id']
        # print('')
        # print('gen_id: ', gen_id)
        # for t in intervals[1:]:
        # print('gen_id: ', gen_id)
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
            to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state
            # transition_data.append([from_oper_state_id, to_oper_states])
            # print(transition_data)
            # print('from: ', from_oper_state_id, 'to: ', to_oper_states)
            # at this point we have 1 from id and 1 or more to ids

            for next_state in to_oper_states:
                next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
                # print('id:', next_state_id)
                if from_oper_state_id == next_state_id:
                    pass
                else:
                    max_time_left = next_state.get('max-transition-time-left_b', float('inf'))  # if max-time key does not exist, use a very large number as the default value for max-time
                    # Convert infinity to a large number for integer operations
                    max_time_left = int(min(max_time_left, len(intervals))) if max_time_left != float('inf') else len(intervals)
                    # if for any given time period in the beginning of the schedule we are in an operating state for more consecutive periods than max-time-left for
                    # transition defines, then we cannot transit to that next specific operating state
                    if (gen_id, max_time_left+1, next_state_id) in u_2_dict:

                        prob += pl.lpSum(u_2_dict[(gen_id, t_prime, next_state_id)] for t_prime in intervals[1:max_time_left+2]) - max_time_left - s_max_b_left[gen_id][max_time_left+1] <= 0
                        # we do not know for how many dispatch periods the respective constraint will be violated, we only know if it was violated or not at t = max_time_left + 1
                        # objective_terms += s_max_b_left[gen_id][max_time_left+1] * 1000000
                    # else:
                    #     prob += pl.lpSum(u_2_dict[(gen_id, t_prime, next_state_id)] for t_prime in intervals[1:t + 2]) - t <= 0

            for tt in intervals[1:]:  # Start from 1 as we compare with the previous interval
                # Check if the generator entered the state at this interval
                # entered_state_now = (u_2_dict[(gen_id, t, from_oper_state_id)] - u_2_dict[(gen_id, t-1, from_oper_state_id)])
                for next_state in to_oper_states:  # there must be an operating state id when we define the "to" state
                    next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
                    if from_oper_state_id == next_state_id:
                        pass
                    else:
                        max_time = next_state.get('max-transition-time_b', float('inf'))  # if max-time key does not exist, use a very large number as the default value for max-time
                        # Convert infinity to a large number for integer operations
                        max_time = int(min(max_time, len(intervals))) if max_time != float('inf') else len(intervals)
                        if (gen_id, tt + max_time, next_state_id) in u_2_dict:  # if tt + max_time + 1 exceeds our time horizon do not enforce any relative constraint
                            # print(tt + max_time + 1)
                            # print(IntervalCount)
                            # if we remain at a specific operational state ('to') more than max_time consecutive periods
                            # then we can transit to this 'from' another specific state

                            # we do not know for how many dispatch periods the respective constraint will be violated, we only know if it was violated or not at t = tt + max_time_left
                            prob += (max_time + 1) - pl.lpSum(u_2_dict[(gen_id, t, next_state_id)] for t in intervals[tt: tt + max_time + 1]) >= u_2_dict[(gen_id, tt - 1, from_oper_state_id)] - s_max_b_1[gen_id][tt + max_time]
                            # objective_terms += s_max_b_1[gen_id][tt + max_time] * 1000000
                        else:
                            pass

        for t in intervals[1:]:
            objective_terms += s_max_b_left[gen_id][t] * input_data["Cost_parameters"]["x_max_transition_oper_states_b_left"] + s_max_b_1[gen_id][t] * input_data["Cost_parameters"]["x_max_transition_oper_states_b"]

    return prob, objective_terms


def create_min_time_states_constraints_states(prob, objective_terms, input_data, data, state, intervals, startup, shutdown):
    s_min_state_b_left = [[pl.LpVariable(name=f's_min_state_b_left_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    s_min_state_b_1 = [[pl.LpVariable(name=f's_min_state_b_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    import copy
    for gen in data:
        # print(gen)
        gen_id = gen['gen_id']
        # print('')
        # print('gen_id: ', gen_id)
        # for t in intervals[1:]:
        #     print('gen_id: ', gen_id)
        for allowed_transition in gen['state-transitions']:
            from_state_value = allowed_transition['from']
            to_state_value = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
            min_time_left = int(to_state_value.get('min-transition-time-left', 0))  # Convert to int, if min-time key does not exist, use 0 as the default value for min-time
            min_time = int(to_state_value.get('min-transition-time', 0))  # Convert to int, if min-time key does not exist, use 0 as the default value for min-time
            # print(next_state_id, min_time_left)
            # IF WE GO FROM A --> B, we have to stay in B for at least 'min-time-left' intervals
            for t in intervals[1:min_time_left + 1]:
                if from_state_value == 0:
                    prob += state[gen_id][t] + s_min_state_b_left[gen_id][t] >= 1
                else:  # if  from_state_value == 1
                    prob += state[gen_id][t] - s_min_state_b_left[gen_id][t] <= 0
                # objective_terms += s_min_state_b_left[gen_id][t] * 1000000 * (min_time_left - t + 1)

            # IF WE GO FROM A --> B, we have to stay in B for at least 'min-time' intervals
            if from_state_value == 0:
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += startup[gen_id][t] <= state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]
                        # objective_terms += s_min_state_b_1[gen_id][t_prime] * 1000000
            else:
                for t in intervals[1:]:
                    for t_prime in intervals[t:t + min_time]:
                        prob += shutdown[gen_id][t] <= 1 - state[gen_id][t_prime] + s_min_state_b_1[gen_id][t_prime]
                        # objective_terms += s_min_state_b_1[gen_id][t] * 1000000

        for t in intervals[1:]:
            objective_terms += s_min_state_b_left[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states_left"] + s_min_state_b_1[gen_id][t] * input_data["Cost_parameters"]["x_min_transition_states"]



    return prob, objective_terms

