# Extracted from RV_genericMmsOptimization.py. Keep behavior-compatible with the original scheduling data preparation.

def unit_categories(input_data, data):
    CONV = []
    RES = []
    PV = []
    Partially_Controllable = []
    on_AGC = []
    for i, _ in enumerate(data):
        #     print(i['comments'])
        if data[i]['comments'][:5] == 'Therm':
            CONV.append(i)
        elif data[i]['comments'][:2] == 'PV':
            PV.append(i)
        elif "Partially Controllable" in data[i]['comments']:
            Partially_Controllable.append(i)
        else:
            RES.append(i)

    RES_SP = []
    RES_no_SP = []
    PV_SP = []
    PV_no_SP = []
    # print(input_data['Generating_Units'])
    for i in RES+PV:
        if i in RES:
            if input_data["Generating_Units"][i]['Accepts_SP'] == 1:
                RES_SP.append(i)
            else:
                RES_no_SP.append(i)
        elif i in PV:
            if input_data["Generating_Units"][i]["Accepts_SP"] == 1:
                PV_SP.append(i)
            else:
                PV_no_SP.append(i)
    if input_data["Other_coefficients"]["include_PV"]:
        UNITS = CONV + RES + PV
    else:
        UNITS = CONV + RES
    print("Units:", UNITS)

    return UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, Partially_Controllable

def filter_generating_units(data):
    # Filters out generating units with no availability in every dispatch period.
    filtered_units = []
    for unit in data:
        availability = unit.get("availability", 0)
        if isinstance(availability, list):
            if any(value != 0 for value in availability):
                filtered_units.append(unit)
        elif availability != 0:
            filtered_units.append(unit)
    return filtered_units

def round_to_best(a, b):
    if a == float('inf'):
        return 100000000000
    else:
        if a % b == 0:
            return round(a / b)
        else:
            return int(a / b) + 1

def time_granularity(data, time_gran):
    # Iterate over each generating unit in the data
    for gen_unit in data["Generating_Units"]:
        for operating_state in gen_unit["operating-states"]:
            operating_state["min-time-enabled"] = round_to_best(operating_state.get("min-time-enabled", 0), time_gran)
            operating_state["max-time-enabled"] = round_to_best(operating_state.get("max-time-enabled", float('inf')), time_gran)
            # gen_unit["min_time_off"] = round_to_best(gen_unit["min_time_off"], time_gran)
            operating_state["min-time-enabled-left"] = round_to_best(operating_state.get("min-time-enabled-left", 0), time_gran)
            operating_state["max-time-enabled-left"] = round_to_best(operating_state.get("max-time-enabled-left", float('inf')), time_gran)

        for allowed_transition in gen_unit['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = allowed_transition['transitions']  # all allowed states to transition to
            # to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state

            # at this point we have 1 'from' id and 1 or more 'to' ids

            # for the start of the scheduling period
            for next_state in to_oper_states:
                next_state['min-transition-time-left_a'] = round_to_best(next_state.get('min-transition-time-left_a', 0), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
                next_state['min-transition-time_a'] = round_to_best(next_state.get('min-transition-time_a', 0), time_gran)
                next_state['max-transition-time-left_a'] = round_to_best(next_state.get('max-transition-time-left_a', float('inf')), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
                next_state['max-transition-time_a'] = round_to_best(next_state.get('max-transition-time_a', float('inf')), time_gran)
                next_state['min-transition-time_b'] = round_to_best(next_state.get('min-transition-time_b', 0), time_gran)
                next_state['min-transition-time-left_b'] = round_to_best(next_state.get('min-transition-time-left_b', 0), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time next_state['max-transition-time'] = round_to_best(next_state.get('max-transition-time', float('inf')),time_gran)
                next_state['max-transition-time-left_b'] = round_to_best(next_state.get('max-transition-time-left_b', float('inf')), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
                next_state['max-transition-time_b'] = round_to_best(next_state.get('max-transition-time_b', float('inf')), time_gran)
            # gen_unit["time_Off_left"] = round_to_best(gen_unit["time_Off_left"], time_gran)

            # operating_state["Therm_state_min_time_on"] = [round_to_best(t, time_gran) for t in operating_state["Therm_state_min_time_on"]]
            # operating_state["Therm_state_min_time_on_left"] = [round_to_best(t, time_gran) for t in operating_state["Therm_state_min_time_on_left"]]

        for allowed_transition in gen_unit['state-transitions']:
            # from_oper_state_id = allowed_transition['from']
            to_oper_states = allowed_transition['transitions']  # all allowed states to transition to
            # to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state

            # at this point we have 1 'from' id and 1 or more 'to' ids

            # for the start of the scheduling period

            to_oper_states['min-transition-time-left'] = round_to_best(to_oper_states.get('min-transition-time-left', 0), time_gran)  # if min-time key does not exist, use 0 as the default value for min-time
            to_oper_states['min-transition-time'] = round_to_best(to_oper_states.get('min-transition-time', 0), time_gran)

    # print(data)
    return data

