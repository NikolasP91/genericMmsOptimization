# first create the .mps file through pulp

import numpy as np
import pandas as pd
import pulp as pl
# from highspy import Highs
import highspy
import json
import time
import re
from highspy import HighsSolution
# import xml.etree.ElementTree as ET


from pulp.apis.highs_api import HiGHS_CMD
from mip_utils import ConstraintBuildTracker, estimate_big_m, name_auto_constraints
# def read_sol_file(file_path):
#     with open(file_path, 'r') as file:
#         lines = file.readlines()
#
#     # Initialize sections
#     variables_section = False
#     variable_names = []
#     variable_values = []
#
#     # Parse the file
#     for line in lines:
#         line = line.strip()
#         if line.startswith('# Columns'):
#             variables_section = True
#             continue
#         elif line.startswith('# Rows'):
#             variables_section = False
#             break
#
#         if variables_section:
#             if line.isdigit():
#                 continue  # Skip the number of columns line
#             parts = line.split()
#             variable_names.append(parts[0])
#             variable_values.append(float(parts[1]))
#
#     return variable_names, variable_values

# Function to extract the unit, t, and n from the variable name
def extract_numbers_4(item):
    match = re.search(r'_(\d+)_(\d+)_(\d+)', item[0])
    generator_number = int(match.group(1))
    hour = int(match.group(2))
    n = int(match.group(3))
    return generator_number, hour, n


# mult_values = []
def extract_numbers(item):
    match = re.search(r'_(\d+)_(\d+)$', item[0])
    generator_number = int(match.group(1)) if match else 0
    hour = int(match.group(2)) if match else 0
    return generator_number, hour


def extract_single_value(item):
    match = re.search(r'_(\d+)$', item[0])
    value = int(match.group(1)) if match else 0
    return value

    # # Extract the hour from the variable name
    # def extract_numbers_2(item):
    #     match = re.search(r'_(\d+)_(\d+)$', item[0])
    #     hour = int(match.group(2)) if match else 0
    #     return hour

    # Extract the unit, hour, and power level from the variable name


def extract_numbers_3(item):
    match = re.search(r'_(\d+)_(\d+)_(\d+)_(\d+)$', item[0])
    unit = int(match.group(2)) if match else 0
    hour = int(match.group(3)) if match else 0
    level = int(match.group(4)) if match else 0
    return unit, hour, level


def extract_numbers_2(item):
    match = re.search(r'(\d+)_(\d+)$', item[0])
    unit = int(match.group(1)) if match else 0
    hour = int(match.group(2)) if match else 0
    return unit, hour


# Extract generator ID and hour from variable names and add them as new columns
def extract_gen_hour(df):
    df['Generator'], df['Hour'] = zip(*df['Variable'].map(lambda x: map(int, re.findall(r'\d+', x))))
    return df


def pivot_df(df):
    return df.pivot(index='Generator', columns='Hour', values='Value')





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

def create_global_variables(prob, data, intervals):
    # Power output for each generator for each hour
    power = [[pl.LpVariable(name=f'power_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]
    # State for each generator for each hour
    state = [[pl.LpVariable(name=f'state_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _
             in
             enumerate(data)]
    # total PV + RES production for each hour
    RES_sum = [pl.LpVariable(name=f'RES_sum_{t}', lowBound=0, upBound=None) for t in intervals]
    # Startup variables
    startup = [[pl.LpVariable(name=f'startup_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for
               i, _
               in enumerate(data)]
    # Shutdown variables
    shutdown = [[pl.LpVariable(name=f'shutdown_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
                for i
                in range(len(data))]
    for i, gen in enumerate(data):
        prob += state[i][0] == gen['state']  # the state value of the hour = 0 (the last hour before our day starts)
        prob += 100 * power[i][0] == 100 * gen['current_Power(MW)']  # the energy production of the hour = 0
    return prob, power, state, RES_sum, startup, shutdown

def find_N_1_N_2_thermal_units(prob,  CONV, RES, PV, state, data, M, intervals):
    N_1 = [[pl.LpVariable(name=f'N_1_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, gen in enumerate(data)]
    N_2 = [[pl.LpVariable(name=f'N_2_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, gen in enumerate(data)]

    y_0 = [pl.LpVariable(name=f'y_0_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    y_1 = [pl.LpVariable(name=f'y_1_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    y_2 = [pl.LpVariable(name=f'y_2_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]

    count_on = [pl.LpVariable(name=f'count_on_{t}', lowBound=0, cat='Integer') for t in intervals]
    n = len(CONV)

    for t in intervals[1:]:
        #       Find the 1st and 2nd active conventional units with the highest available power
        # prob += pl.lpSum(N_1[i][t] + s_N_1[i][t] for i in CONV) == 1
        # prob += pl.lpSum(N_2[i][t] + s_N_2[i][t] for i in CONV) == 1

        prob += count_on[t] == pl.lpSum(state[i][t] for i in CONV)

       #  calculate the values of y binary variables that define how many units are On every dispatch period

        # C1
        prob += y_0[t] + y_1[t] + y_2[t] == 1
        # C2
        prob += y_0[t] >= 1 - count_on[t]
        # C3
        prob += n * y_0[t] <= n - count_on[t]
        # C4
        prob += n * y_2[t] >= count_on[t] - 1
        # C5
        prob += 2 * y_2[t] <= count_on[t]

        # tie y binaries with N_1 & N_2
        prob += pl.lpSum(N_1[i][t] for i in CONV) == y_1[t] + y_2[t]
        prob += pl.lpSum(N_2[i][t] for i in CONV) == y_2[t]

        for i in RES + PV:
            prob += N_1[i][t] == 0
            prob += N_2[i][t] == 0

        for i in CONV:
            prob += N_1[i][t] <= state[i][t]
            prob += N_2[i][t] <= state[i][t]
            prob += N_1[i][t] + N_2[i][t] <= 1


            for j in CONV:
                if i != j:
                    # Largest unit comparison using Big-M method
                    prob += N_1[i][t] * data[i]['availability'][t-1] >= state[j][t] * data[j]['availability'][t-1] - M * (1 - N_1[i][t])
                    # Second-largest unit comparison using Big-M method
                    prob += N_2[i][t] * data[i]['availability'][t-1] >= state[j][t] * data[j]['availability'][t-1] - M * (N_1[j][t] + (1 - N_2[i][t]))
           # objective_terms += s_N_1[i][t] * 10000 + s_N_2[i][t] * 10000
    return N_1, N_2


def produce_min_max_t(data, intervals):
    k = len(intervals)-1

    for i, _ in enumerate(data):
        data[i]["max_power(MW)"] = k * [data[i]["max_power(MW)"]]
        data[i]["min_power(MW)"] = k * [data[i]["min_power(MW)"]]
        for operating_states in data[i]["operating-states"]:
            operating_states["max-power"] = k * [operating_states["max-power"]]
            operating_states["min-power"] = k * [operating_states["min-power"]]
    return data


def min_max_handling(prob, data, input_data, CONV, Partially_Controllable, on_AGC, intervals, u_1, state, power):

    if input_data["constraints"]["min_max_constraint"]:
        # only for dispatchable units check 5.2.4.4 Constraints paragraph in "Διακήρυξη" pdf
        for gen in data:
            gen_id = gen['gen_id']
            if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
                for operating_state in data[gen_id]["operating-states"]:
                    if operating_state["isOperational"]:
                        for t in intervals[1:]:
                            # if constraint enabled -- we cannot go to the zone above technical maximum
                            # prob += u_1[gen_id][t][-1] == 0
                            operating_state["max-power"][t-1] = operating_state["user_max_power"]
                            operating_state["min-power"][t-1] = operating_state["user_min_power"]
                    else:
                        pass
    else:
        # for gen in data:
        #     gen_id = gen['gen_id']
        #     if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
        #         for operating_state in data[gen_id]["operating-states"]:
        #             if operating_state["isOperational"]:
        #                 for t in intervals[1:]:
        #                     operating_state["max-power"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
        #                     operating_state["min-power"][t-1] = 0
        #             else:
        #                 for t in intervals[1:]:
        #                     operating_state["max-power"][t-1] = operating_state["min-power"][t-1] = 0
        #         for t in intervals[1:]:
        #             data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
        #             data[gen_id]["min_power(MW)"][t-1] = 0
        #     else:
        pass

    for i, _ in enumerate(data):
        # these units can provide secondary reserves - regulation
        # for i in CONV:
        agc_configuration = data[i].get("agc_configuration", {})
        if agc_configuration.get("isConnected", 0) == 1:
            on_AGC.append(i)
            for operating_states in data[i]["operating-states"]:
                if operating_states["isOperational"]:
                    for t in intervals[1:]:
                        operating_states["max-power"][t-1] = min(agc_configuration.get("maxLoad", operating_states["max-power"][t-1]), operating_states["max-power"][t-1])
                        operating_states["min-power"][t-1] = max(agc_configuration.get("minLoad", operating_states["min-power"][t-1]), operating_states["min-power"][t-1])
                else:
                    pass
        else:
            pass
    #
    # for i, _ in enumerate(data):
    #     if i in Partially_Controllable:
    #         print("Partially_Controllable Unit:", i)
    #         for t in intervals[1:]:
    #             for operating_states in data[i]["operating-states"]:
    #                 if operating_states["isOperational"]:
    #                     if operating_states["max-power"][t-1] > data[i]["production_program"][t-1]:
    #                         if operating_states["min-power"][t-1] > data[i]["production_program"][t-1]:
    #                             for operating_states_2 in data[i]["operating-states"]:
    #                                 operating_states_2["max-power"][t - 1] = operating_states_2["min-power"][t-1] = 0
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[gen_id]["min_power(MW)"][t - 1] = 0
    #                             prob += state[gen_id][t] == 0
    #                         else:
    #                             operating_states["max-power"][t - 1] = data[i]["production_program"][t-1]
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #                     else:
    #                         if data[gen_id]["max_power(MW)"][t - 1] < data[i]["production_program"][t-1]:
    #                             pass
    #                         else:
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #                 else:
    #                     pass
    # print(data[5])
    # print(data)

    return prob, data, on_AGC


def create_res_sum_calculation_constraint(prob, power, intervals, RES_sum, RES, PV, Partially_Controllable):
    # Create RES_sum[t] calculation constraint
    for t in intervals[0:]:
        prob += RES_sum[t] == pl.lpSum(power[i][t] for i in RES + PV + Partially_Controllable)
    return prob


def create_production_load_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV,
                                              x_load):
    # decision variables generation
    # production - load balance relaxation variable (need to increase load)
    s_load_plus = [pl.LpVariable(name=f's_load_plus_{t}', lowBound=0, upBound=None) for t in intervals]
    # production - load balance relaxation variable (need to decrease load)
    s_load_minus = [pl.LpVariable(name=f's_load_minus_{t}', lowBound=0, upBound=None) for t in intervals]
    # respective constraint
    for t in intervals[1:]:
        # Total generation must be equal to the load forecast for each hour
        prob += pl.lpSum(power[i][t] for i in range(len(data))) - s_load_plus[t] + s_load_minus[t] == Load_forecast[t]
        prob += s_load_plus[t] == 0
        # prob += s_load_minus[t] == 0
        # for i in CONV:
        objective_terms += s_load_plus[t] * x_load + s_load_minus[t] * x_load
    return prob, objective_terms, s_load_minus, s_load_plus

def create_primary_active_power_reserves_constraint(prob, input_data, objective_terms, power, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M,  PV, N_1, N_2):
    # epsilon = 0.001
    # M=10000
    # decision variables generation
    primary_ActPR_plus = [[pl.LpVariable(name=f'primary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    primary_ActPR_minus = [[pl.LpVariable(name=f'primary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    # primary_y_plus = [[pl.LpVariable(name=f'primary_y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    # primary_y_minus = [[pl.LpVariable(name=f'primary_y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    primary_APRR = [[pl.LpVariable(name=f'primary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in intervals]
    s_primary_APR_upwards = [pl.LpVariable(name=f's_primary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_primary_APR_downwards = [pl.LpVariable(name=f's_primary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]

    binary_primary = [[[pl.LpVariable(name=f'binary_primary_{t}_{n}_{m}', lowBound=0, upBound=1, cat='Binary') for m in range(6)] for n in [0, 1]] for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:

                for t in intervals[1:]:
                    if gen['availability'][t-1] == 0:
                        prob += primary_ActPR_plus[i][t] == 0
                        prob += primary_ActPR_minus[i][t] == 0

                    else:

                        if input_data["constraints"]["min_max_constraint"]:

                            prob += primary_ActPR_plus[i][t] <= min(gen['availability'][t-1], operating_state['user_max_power']) - power[i][t]
                            prob += primary_ActPR_plus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][0]

                            prob += primary_ActPR_minus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += primary_ActPR_minus[i][t] <= power[i][t] - operating_state['user_min_power'] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])

                            prob += primary_ActPR_plus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += primary_ActPR_minus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]

                        else:
                            prob += primary_ActPR_plus[i][t] <= gen['availability'][t - 1] - power[i][t]
                            prob += primary_ActPR_plus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][0]

                            prob += primary_ActPR_minus[i][t] <= gen["Primary_Active_Power_Reserves(MW)"][1] + M * (
                                        1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += primary_ActPR_minus[i][t] <= power[i][t] - gen['min_power(MW)'][t - 1] + M * (
                                        1 - u_2_dict[(gen_id, t, operating_state_id)])

                            prob += primary_ActPR_plus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += primary_ActPR_minus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]



        for t in intervals[1:]:  # calculate the cost of APR only for this time horizon
            objective_terms += primary_ActPR_plus[i][t] * gen['Primary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + primary_ActPR_minus[i][t] * gen['Primary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]
    for t in intervals[1:]:
        prob += pl.lpSum(primary_ActPR_minus[i][t] for i in range(len(data))) == primary_APRR[t][1] - s_primary_APR_downwards[t]
        prob += pl.lpSum(primary_ActPR_plus[i][t] for i in range(len(data))) == primary_APRR[t][0] - s_primary_APR_upwards[t]


        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += primary_APRR[t][0] >= (input_data["Other_coefficients"]["primary_upwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += pl.lpSum(binary_primary[t][0][m] for m in range(6)) == 1


        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0] + M * (1 - binary_primary[t][0][0])
        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1] + M * (1 - binary_primary[t][0][1])
        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0] + M * (1 - binary_primary[t][0][2])
        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1] + M * (1 - binary_primary[t][0][3])
        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2] + M * (1 - binary_primary[t][0][4])
        prob += primary_APRR[t][0] <= (input_data["Other_coefficients"]["primary_upwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3] + M * (1 - binary_primary[t][0][5])



        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += primary_APRR[t][1] >= (input_data["Other_coefficients"]["primary_downwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        prob += pl.lpSum(binary_primary[t][1][m] for m in range(6)) == 1

        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0] + M * (1 - binary_primary[t][1][0])
        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1] + M * (1 - binary_primary[t][1][1])
        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0] + M * (1 - binary_primary[t][1][2])
        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1] + M * (1 - binary_primary[t][1][3])
        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2] + M * (1 - binary_primary[t][1][4])
        prob += primary_APRR[t][1] <= (input_data["Other_coefficients"]["primary_downwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3] + M * (1 - binary_primary[t][1][5])

        objective_terms += s_primary_APR_upwards[t] * input_data["Cost_parameters"]["x_primary_APR_up"] + s_primary_APR_downwards[t] * input_data["Cost_parameters"]["x_primary_APR_down"]
    return prob, objective_terms, primary_ActPR_plus, primary_ActPR_minus, primary_APRR, s_primary_APR_upwards, s_primary_APR_downwards


def create_secondary_active_power_reserves_constraint(prob, input_data, objective_terms, power, primary_ActPR_plus, primary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, N_1, N_2):
    secondary_ActPR_plus = [[pl.LpVariable(name=f'secondary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    secondary_ActPR_minus = [[pl.LpVariable(name=f'secondary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
    y_plus = [[pl.LpVariable(name=f'y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    y_minus = [[pl.LpVariable(name=f'y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    secondary_APRR = [[pl.LpVariable(name=f'secondary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in intervals]
    s_secondary_APR_upwards = [pl.LpVariable(name=f's_secondary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_secondary_APR_downwards = [pl.LpVariable(name=f's_secondary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]
    binary_secondary = [[[pl.LpVariable(name=f'binary_secondary_{t}_{n}_{m}', lowBound=0, upBound=1, cat='Binary') for m in range(6)] for n in [0, 1]] for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:

                for t in intervals[1:]:
                    if i in on_AGC:  # provision of secondary reserves
                        if gen['availability'][t-1] == 0:
                            prob += secondary_ActPR_plus[i][t] == 0
                            prob += secondary_ActPR_minus[i][t] == 0
                        else:

                            prob += secondary_ActPR_plus[i][t] <= min(operating_state["max-power"][t-1], gen['availability'][t-1]) - (power[i][t] + primary_ActPR_plus[i][t]) + M * y_plus[i][t]

                            prob += secondary_ActPR_plus[i][t] <= gen["Secondary_Active_Power_Reserves(MW)"][0] + M * y_plus[i][t]


                            prob += secondary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]

                            prob += secondary_ActPR_minus[i][t] <= gen["Secondary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]



#                                   ########################### if y_plus==1 --> secondary_ActPR_plus == 0

                            prob += (power[i][t] + primary_ActPR_plus[i][t]) - operating_state["max-power"][t - 1] >= - M * (1 - y_plus[i][t])
                            prob += (power[i][t] + primary_ActPR_plus[i][t]) - operating_state["max-power"][t - 1] <= M * y_plus[i][t]
                            prob += secondary_ActPR_plus[i][t] <= M * (1 - y_plus[i][t])

#                                                             # if y_minus==1 --> secondary_ActPR_minus == 0
                            prob += (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] <= M * (1 - y_minus[i][t])
                            prob += (power[i][t] - primary_ActPR_minus[i][t]) - operating_state["min-power"][t - 1] >= - M * y_minus[i][t]
                            prob += secondary_ActPR_minus[i][t] <= M * (1 - y_minus[i][t])

#                                    #########################

                            prob += secondary_ActPR_minus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]  # power[i][t] - gen['min_power(MW)'] < 0 ---> primary_ActPR_minus[i][t] == 0
                            prob += secondary_ActPR_plus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]  # power[i][t] - gen['min_power(MW)'] < 0 ---> primary_ActPR_plus[i][t] == 0
                    else:  # no provision of secondary reserves
                        prob += secondary_ActPR_plus[i][t] == 0
                        prob += secondary_ActPR_minus[i][t] == 0
                        # prob += secondary_y_plus[i][t] == 0
                        # prob += secondary_y_minus[i][t] == 0
        for t in intervals[1:]:
            objective_terms += secondary_ActPR_plus[i][t] * gen['Secondary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + secondary_ActPR_minus[i][t] * gen['Secondary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]

    for t in intervals[1:]:
        prob += pl.lpSum(secondary_ActPR_minus[i][t] for i in range(len(data))) == secondary_APRR[t][1] - s_secondary_APR_downwards[t]
        prob += pl.lpSum(secondary_ActPR_plus[i][t] for i in range(len(data))) == secondary_APRR[t][0] - s_secondary_APR_upwards[t]

        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += secondary_APRR[t][0] >= (input_data["Other_coefficients"]["secondary_upwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += pl.lpSum(binary_secondary[t][0][m] for m in range(6)) == 1

        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0] + M * (1 - binary_secondary[t][0][0])
        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1] + M * (1 - binary_secondary[t][0][1])
        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0] + M * (1 - binary_secondary[t][0][2])
        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1] + M * (1 - binary_secondary[t][0][3])
        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2] + M * (1 - binary_secondary[t][0][4])
        prob += secondary_APRR[t][0] <= (input_data["Other_coefficients"]["secondary_upwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3] + M * (1 - binary_secondary[t][0][5])


        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += secondary_APRR[t][1] >= (input_data["Other_coefficients"]["secondary_downwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        prob += pl.lpSum(binary_secondary[t][1][m] for m in range(6)) == 1

        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0] + M * (1 - binary_secondary[t][1][0])
        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1] + M * (1 - binary_secondary[t][1][1])
        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0] + M * (1 - binary_secondary[t][1][2])
        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1] + M * (1 - binary_secondary[t][1][3])
        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2] + M * (1 - binary_secondary[t][1][4])
        prob += secondary_APRR[t][1] <= (input_data["Other_coefficients"]["secondary_downwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3] + M * (1 - binary_secondary[t][1][5])


        # objective_terms += (secondary_APRR[t][0] + secondary_APRR[t][1]) * 100

        # prob += secondary_APRR[t][0] == 0.1 * RES_sum[t] + 0.04 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        # prob += secondary_APRR[t][1] == 0.1 * RES_sum[t] + 0.04 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        objective_terms += s_secondary_APR_upwards[t] * input_data["Cost_parameters"]["x_secondary_APR_up"] + s_secondary_APR_downwards[t] * input_data["Cost_parameters"]["x_secondary_APR_up"]
    return prob, objective_terms, y_plus, y_minus, secondary_ActPR_plus, secondary_ActPR_minus, secondary_APRR, s_secondary_APR_upwards, s_secondary_APR_downwards


def create_tertiary_active_power_reserves_constraint(prob, input_data, objective_terms, y_plus, y_minus, power, primary_ActPR_plus, primary_ActPR_minus, secondary_ActPR_plus, secondary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, N_1, N_2):
    tertiary_ActPR_plus = [
        [pl.LpVariable(name=f'tertiary_ActPR_plus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen
        in
        enumerate(data)]
    tertiary_ActPR_minus = [
        [pl.LpVariable(name=f'tertiary_ActPR_minus{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen
        in
        enumerate(data)]
    # tertiary_y_plus = [[pl.LpVariable(name=f'tertiary_y_plus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    # tertiary_y_minus = [[pl.LpVariable(name=f'tertiary_y_minus_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    tertiary_APRR = [[pl.LpVariable(name=f'tertiary_APRR_{t}_{n}', lowBound=0, upBound=None) for n in [0, 1]] for t in
                     intervals]
    s_tertiary_APR_upwards = [pl.LpVariable(name=f's_tertiary_APR_upwards_{t}', lowBound=0, upBound=None) for t in intervals]
    s_tertiary_APR_downwards = [pl.LpVariable(name=f's_tertiary_APR_downwards_{t}', lowBound=0, upBound=None) for t in intervals]
    binary_tertiary = [[[pl.LpVariable(name=f'binary_tertiary_{t}_{n}_{m}', lowBound=0, upBound=1, cat='Binary') for m in range(6)]for n in [0, 1]] for t in intervals]

    for i, gen in enumerate(data):
        gen_id = gen['gen_id']
        for operating_state in gen['operating-states']:
            operating_state_id = operating_state['id']
            if operating_state['isOperational']:
                for t in intervals[1:]:
                    if i in on_AGC:
                        if gen['availability'][t - 1] == 0:
                            prob += tertiary_ActPR_plus[i][t] == 0
                            prob += tertiary_ActPR_minus[i][t] == 0
                        else:

                            prob += tertiary_ActPR_plus[i][t] <= min(operating_state['max-power'][t-1], gen['availability'][t-1]) - (power[i][t] + primary_ActPR_plus[i][t] + secondary_ActPR_plus[i][t]) + M * y_plus[i][t]
                            prob += tertiary_ActPR_plus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][0] + M * y_plus[i][t]

                            prob += tertiary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t] - secondary_ActPR_minus[i][t]) - operating_state['min-power'][t - 1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]
                            prob += tertiary_ActPR_minus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)]) + M * y_minus[i][t]

###########################################################

                            prob += tertiary_ActPR_plus[i][t] <= M * (1 - y_plus[i][t])

                            prob += tertiary_ActPR_minus[i][t] <= M * (1 - y_minus[i][t])

##########################################################
                            # take into account only spinning active power reserves (for now)
                            prob += tertiary_ActPR_plus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += tertiary_ActPR_minus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]
                    else:
                        if gen['availability'][t - 1] == 0:
                            prob += tertiary_ActPR_plus[i][t] == 0
                            prob += tertiary_ActPR_minus[i][t] == 0
                        else:


                            prob += tertiary_ActPR_plus[i][t] <= min(gen['availability'][t-1], operating_state["max-power"][t-1]) - (power[i][t] + primary_ActPR_plus[i][t] + secondary_ActPR_plus[i][t])
                            prob += tertiary_ActPR_plus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][0]


                            prob += tertiary_ActPR_minus[i][t] <= (power[i][t] - primary_ActPR_minus[i][t] - secondary_ActPR_minus[i][t]) - operating_state["min-power"][t-1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])
                            prob += tertiary_ActPR_minus[i][t] <= gen["Tertiary_Active_Power_Reserves(MW)"][1] + M * (1 - u_2_dict[(gen_id, t, operating_state_id)])


                            # take into account only spinning active power reserves (for now)
                            prob += tertiary_ActPR_plus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]
                            prob += tertiary_ActPR_minus[i][t] <= M * u_2_dict[(gen_id, t, operating_state_id)]

        for t in intervals[1:]:  # calculate the cost of APR only for this time horizon (2nd dispatch period up to the first of the next time horizon)
            objective_terms += tertiary_ActPR_plus[i][t] * gen['Tertiary_APR_Cost(euro/MW)'][0] * input_data["Time_granularity"] + tertiary_ActPR_minus[i][t] * gen['Tertiary_APR_Cost(euro/MW)'][1] * input_data["Time_granularity"]

    for t in intervals[1:]:
        prob += pl.lpSum(tertiary_ActPR_minus[i][t] for i in range(len(data))) == tertiary_APRR[t][1] - s_tertiary_APR_downwards[t]
        prob += pl.lpSum(tertiary_ActPR_plus[i][t] for i in range(len(data))) == tertiary_APRR[t][0] - s_tertiary_APR_upwards[t]

        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2]
        prob += tertiary_APRR[t][0] >= (input_data["Other_coefficients"]["tertiary_upwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3]

        prob += pl.lpSum(binary_tertiary[t][0][m] for m in range(6)) == 1

        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][0] + M * (1 - binary_tertiary[t][0][0])
        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][0][1] + M * (1 - binary_tertiary[t][0][1])
        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][0] + M * (1 - binary_tertiary[t][0][2])
        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][1][1] + M * (1 - binary_tertiary[t][0][3])
        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][2] + M * (1 - binary_tertiary[t][0][4])
        prob += tertiary_APRR[t][0] <= (input_data["Other_coefficients"]["tertiary_upwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_upwards"][3] + M * (1 - binary_tertiary[t][0][5])


        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][0][0]/100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][0][1]/100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][1][0]/100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][1][1]/100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][2]/100) * pl.lpSum(N_1[i][t] * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2]
        prob += tertiary_APRR[t][1] >= (input_data["Other_coefficients"]["tertiary_downwards"][3]/100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t-1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3]

        prob += pl.lpSum(binary_tertiary[t][1][m] for m in range(6)) == 1

        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][0][0] / 100) * pl.lpSum(power[i][t] for i in range(len(data))) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][0] + M * (1 - binary_tertiary[t][1][0])
        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][0][1] / 100) * (pl.lpSum(power[i][t] for i in range(len(data))) - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][0][1] + M * (1 - binary_tertiary[t][1][1])
        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][1][0] / 100) * RES_sum[t] * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][0] + M * (1 - binary_tertiary[t][1][2])
        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][1][1] / 100) * (RES_sum[t] - pl.lpSum(power[i][t] for i in PV)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][1][1] + M * (1 - binary_tertiary[t][1][3])
        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][2] / 100) * pl.lpSum(N_1[i][t] * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][2] + M * (1 - binary_tertiary[t][1][4])
        prob += tertiary_APRR[t][1] <= (input_data["Other_coefficients"]["tertiary_downwards"][3] / 100) * pl.lpSum((N_1[i][t] + N_2[i][t]) * gen['availability'][t - 1] for i, gen in enumerate(data)) * input_data["constraints"]["APRR_calculations"]["calculation-method_downwards"][3] + M * (1 - binary_tertiary[t][1][5])



        # objective_terms += (tertiary_APRR[t][0] + tertiary_APRR[t][1]) * 100
        objective_terms += s_tertiary_APR_upwards[t] * input_data["Cost_parameters"]["x_tertiary_APR_up"] + s_tertiary_APR_downwards[t] * input_data["Cost_parameters"]["x_tertiary_APR_down"]
        # prob += tertiary_APRR[t][0] == 0.2 * RES_sum[t] + 0.08 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
        # prob += tertiary_APRR[t][1] == 0.2 * RES_sum[t] + 0.08 * pl.lpSum(power[i][t] for i in range(len(data)))  # Load_forecast[t]
    return prob, objective_terms, tertiary_ActPR_plus, tertiary_ActPR_minus, tertiary_APRR, s_tertiary_APR_upwards, s_tertiary_APR_downwards


def create_forbidden_zones_constraint(prob, objective_terms, input_data, power, data, intervals, CONV, M):
    y_zone = [[[pl.LpVariable(f'y_zone_{i + 1}_{t}_{idx}', 0, 1, cat='Binary') for idx, _ in
                enumerate(gen["forbidden_zones"])] for t in intervals] for i, gen in enumerate(data)]
    s_forbidden_zones_plus = [[pl.LpVariable(name=f's_forbidden_zones_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]
    s_forbidden_zones_minus = [[pl.LpVariable(name=f's_forbidden_zones_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in
             enumerate(data)]

    # M = 10000
    for i, gen in enumerate(data):
        for t in intervals[1:]:
            if i in CONV:
                if data[i]["forbidden_zones"] == []:
                    pass  # Do nothing if there are no forbidden zones
                else:
                    for idx, zone in enumerate(data[i]["forbidden_zones"]):
                        # if len(zone) == 2:
                        # print(zone[0])
                        # print(zone[1])
                        lower_bound = zone[0]  # Unpack the bounds of the forbidden zone
                        upper_bound = zone[1]
                        prob += power[i][t] - s_forbidden_zones_minus[i][t] <= lower_bound + M * y_zone[i][t][idx]  # prob += power[i][t] <= lower_bound - 0.001 + M * y_zone[i][t][idx]
                        prob += power[i][t] + s_forbidden_zones_plus[i][t] >= upper_bound - M * (1 - y_zone[i][t][idx])  # prob += power[i][t] >= upper_bound + 0.001 - M * (1 - y_zone[i][t][idx])
                        # else:
                        #
                        #     print(f"Warning: Skipping invalid forbidden zone {zone} for unit {i}"
                    objective_terms += s_forbidden_zones_plus[i][t] * input_data["Cost_parameters"]["x_forbidden_zones"] + s_forbidden_zones_minus[i][t] * input_data["Cost_parameters"]["x_forbidden_zones"]
    return prob, objective_terms, y_zone, s_forbidden_zones_plus, s_forbidden_zones_minus


def create_ramp_up_down_constraints(input_data, prob, power, data, intervals, objective_terms):
    ramp_relax = [[pl.LpVariable(name=f'ramp_relax_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]

    for i, gen in enumerate(data):
        for t in intervals[1:]:
            prob += power[i][t] - power[i][t - 1] <= gen['ramp_up_rate(kW/min)'] * (input_data["Time_granularity"]/1000) + ramp_relax[i][t]
            prob += power[i][t - 1] - power[i][t] <= gen['ramp_down_rate(kW/min)'] * (input_data["Time_granularity"]/1000) + ramp_relax[i][t]
            # prob += ramp_relax[i][t] == 0
            objective_terms += ramp_relax[i][t] * input_data["Cost_parameters"]["x_ramp"]
    return prob, ramp_relax, objective_terms


def create_mustRun_constraints(prob, objective_terms, input_data, data, intervals, state):
    s_must_run = [[pl.LpVariable(name=f's_must_run_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
    for gen in data:
        gen_id = gen["gen_id"]
        for t in intervals[1:]:
            if data[gen_id]["mustRun"][t - 1] == 1:
                prob += state[gen_id][t] + s_must_run[gen_id][t] == 1
                #  >= data[i]["mustRun"][t - 1] constraint changed to explicit from implicit
            objective_terms += s_must_run[gen_id][t] * input_data["Cost_parameters"]["x_must_run"]
    return prob, objective_terms, s_must_run


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
    import copy
    transition_cost = {}
    y_dict = {}
    transition_data = []
    for gen in data:
        gen_id = gen['gen_id']
        for t in intervals:
            key = (gen_id, t)
            # Define the LpVariable and assign it to the key in the dictionary
            transition_cost[key] = pl.LpVariable(name=f'transition_cost_{key[0] + 1}_{key[1]}', lowBound=0, upBound=None)
            # Now transition_cost contains all our variables, accessible by the unique tuple keys
            for allowed_transition in gen['operating-state-transitions']:
                from_oper_state_id = allowed_transition['from']
                key2 = (gen_id, t, from_oper_state_id)
                y_dict[key2] = pl.LpVariable(name=f'y_dict_{key2[0] + 1}_{key2[1]}_{key2[2]}', lowBound=0, upBound=None)
    for gen in data:
        gen_id = gen['gen_id']
        # print('')
        # print('gen_id: ', gen_id)
        # for t in intervals[1:]:
        #     print('gen_id: ', gen_id)
        for allowed_transition in gen['operating-state-transitions']:
            from_oper_state_id = allowed_transition['from']
            to_oper_states = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
            to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state
            # transition_data.append([from_oper_state_id, to_oper_states])
            # print(transition_data)
            # print('from: ', from_oper_state_id, 'to: ', to_oper_states)
            for t in intervals[1:]:
                prob += pl.lpSum(u_2_dict[(gen_id, t, to_oper_state_data['id'])] for to_oper_state_data in to_oper_states) >= u_2_dict[(gen_id, t - 1, from_oper_state_id)]
                # the generator can remain in the same operating state, and can also change state as the json file defines ("operating-state-transitions")
                # Conditional constraints using big-M
                prob += y_dict[(gen_id, t, from_oper_state_id)] <= pl.lpSum(u_2_dict[(gen_id, t, to_oper_state_data['id'])] * to_oper_state_data.get('transition-cost', 0) for to_oper_state_data in to_oper_states) + M * (1 - u_2_dict[(gen_id, t-1, from_oper_state_id)])  # a = Sum if y = 1
                prob += y_dict[(gen_id, t, from_oper_state_id)] >= pl.lpSum(u_2_dict[(gen_id, t, to_oper_state_data['id'])] * to_oper_state_data.get('transition-cost', 0) for to_oper_state_data in to_oper_states) - M * (1 - u_2_dict[(gen_id, t-1, from_oper_state_id)])  # a = Sum if y = 1
                prob += y_dict[(gen_id, t, from_oper_state_id)] <= 0 + M * u_2_dict[(gen_id, t-1, from_oper_state_id)]  # a = 0 if y = 0
                prob += y_dict[(gen_id, t, from_oper_state_id)] >= 0 - M * u_2_dict[(gen_id, t-1, from_oper_state_id)]  # a = 0 if y = 0

            #  to_oper_states.clear()
            #  at t-1 we were ate state -- from, at t we are at state -- to
    # print(transition_data)
    obj += pl.lpSum(y_dict[(gen['gen_id'], t, allowed_transition['from'])] for gen in data for allowed_transition in gen['operating-state-transitions'] for t in intervals[1:])

    # print(data)
    return prob, obj


# def create_variable_cost_curve_calculation_constraints(input_data, prob, objective_terms, power, data, intervals, M):
#     # M = 10000
#     u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index in
#              range(0, len(gen['var_gen_cost(euro/MW)'][0])+1)] for t in intervals] for i, gen in enumerate(data)]
#
#     lambda_ = [[[pl.LpVariable(name=f'lambda_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0])+2)] for t in intervals] for i, gen in enumerate(data)]
#     unit_cost = [[pl.LpVariable(name=f'unit_cost_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]
#
#     for i, gen in enumerate(data):
#         p_int = gen['var_gen_cost(euro/MW)'][0][:]
#         p_int.append(gen['max_power(MW)'])
#         p_int.insert(0, 0)
#         u_c = gen['var_gen_cost(euro/MW)'][1][:]
#         u_c.append(u_c[-1])
#         u_c.insert(0, u_c[0])
#         u_c = [p_int[k]*u_c[k] for k in range(len(p_int))]
#
#         n = len(p_int)
#         for t in intervals[1:]:
#             prob += power[i][t] == pl.lpSum(p_int[s_index] * lambda_[i][t][s_index] for s_index in range(n))
#             prob += unit_cost[i][t] == pl.lpSum(u_c[s_index] * lambda_[i][t][s_index] for s_index in range(n))
#             prob += pl.lpSum(lambda_[i][t][s_index] for s_index in range(n)) == 1
#             # prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]) + 1)) == 1
#             prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(n-1)) == 1
#
#             prob += lambda_[i][t][0] <= u_1[i][t][0]
#             prob += lambda_[i][t][-1] <= u_1[i][t][-1]
#
#             for j in range(1, n-1):
#                 prob += lambda_[i][t][j] <= u_1[i][t][j-1] + u_1[i][t][j]
#
#             objective_terms += unit_cost[i][t] * input_data["Time_granularity"]
#     # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
#     # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
#     #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
#     #             prob += z_1[i][t][s_index] <= power[i][t]
#     #         # definition of the level (βαθμίδας) of operation of unit g, t hour
#     #         # the u variable that will take value = 1, will give us the info of what level are we in
#     #         # so that we will be able to calculate the respective cost of power generation
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         # for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
#
#     #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
#     #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
#     #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
#     #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
#     #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
#     #             #     variable in the MILP model.
#     #             if s_index > 0:
#     #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
#     #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
#     #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
#     #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
#         # M = 10000
#     # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
#     #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
#     # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
#     # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
#     #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]
#
#     # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
#     # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
#     #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
#     #             prob += z_1[i][t][s_index] <= power[i][t]
#     #         # definition of the level (βαθμίδας) of operation of unit g, t hour
#     #         # the u variable that will take value = 1, will give us the info of what level are we in
#     #         # so that we will be able to calculate the respective cost of power generation
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
#     #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
#     #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
#     #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
#     #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
#     #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
#     #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
#     #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
#     #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
#     #             #     variable in the MILP model.
#     #             if s_index > 0:
#     #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
#     #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
#             # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
#             # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
#
#     #     # M = 10000
#     # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
#     #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
#     # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
#     # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
#     #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]
#     #
#     # # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
#     # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
#     #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
#     #             prob += z_1[i][t][s_index] <= power[i][t]
#     #         # definition of the level (βαθμίδας) of operation of unit g, t hour
#     #         # the u variable that will take value = 1, will give us the info of what level are we in
#     #         # so that we will be able to calculate the respective cost of power generation
#     # for i, gen in enumerate(data):
#     #     for t in intervals[1:]:
#     #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
#     #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
#     #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
#     #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
#     #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
#     #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
#     #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
#     #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
#     #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
#     #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
#     #             #     variable in the MILP model.
#     #             if s_index > 0:
#     #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
#     #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
#     #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
#     #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
#     return prob, objective_terms, u_1


def create_variable_cost_curve_calculation_constraints(input_data, prob, objective_terms, power, data, intervals, M, state, CONV):
    # M = 10000
    u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index in
             range(0, len(gen['var_gen_cost(euro/MW)'][0])-1)] for t in intervals] for i, gen in enumerate(data)]

    delta_ = [[[pl.LpVariable(name=f'delta_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0])-1)] for t in intervals] for i, gen in enumerate(data)]
   # unit_cost = [[pl.LpVariable(name=f'unit_cost_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, gen in enumerate(data)]

    for i, gen in enumerate(data):
        p_int = gen['var_gen_cost(euro/MW)'][0][:]
        # p_int.append(gen['max_power(MW)'])
        # p_int.insert(0, 0)
        u_c = gen['var_gen_cost(euro/MW)'][1][:]
        # u_c.append(u_c[-1])
        # u_c.insert(0, u_c[0])
        # u_c = [p_int[k]*u_c[k] for k in range(len(p_int))]
        if i in CONV:
            n = len(p_int)
            for t in intervals[1:]:
                prob += power[i][t] == pl.lpSum(delta_[i][t][s_index] for s_index in range(n-1)) + p_int[0] * state[i][t]

                for s_index in range(n-1):
                    if s_index == 0:

                        prob += (p_int[s_index + 1] - p_int[s_index]) * u_1[i][t][s_index] <= delta_[i][t][s_index]

                        prob += (p_int[s_index + 1] - p_int[s_index]) * state[i][t] >= delta_[i][t][s_index]

                    elif s_index == n-2:

                        prob += (p_int[s_index + 1] - p_int[s_index]) * u_1[i][t][s_index - 1] >= delta_[i][t][s_index]

                    else:

                        prob += (p_int[s_index + 1] - p_int[s_index]) * u_1[i][t][s_index] <= delta_[i][t][s_index]

                        prob += (p_int[s_index + 1] - p_int[s_index]) * u_1[i][t][s_index - 1] >= delta_[i][t][s_index]



                objective_terms += (pl.lpSum(u_c[s_index + 1] * delta_[i][t][s_index] for s_index in range(n-1)) + u_c[0] * state[i][t]) * input_data["Time_granularity"]
    # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         # for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):

    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
    #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
    #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
        # M = 10000
    # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
    #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
    # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
    # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
    #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]

    # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
    #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
            # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
            # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed

    #     # M = 10000
    # u_1 = [[[pl.LpVariable(name=f'u_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=1, cat='Binary') for s_index, _ in
    #          enumerate(gen['var_gen_cost(euro/MW)'][0])] for t in intervals] for i, gen in enumerate(data)]
    # # in which level of the variable cost curve we are u_1 (and z_1 = power[i][t] * u_1[i][t][s])
    # z_1 = [[[pl.LpVariable(f'z_1_{i + 1}_{t}_{s_index}', lowBound=0, upBound=None) for s_index in
    #          range(0, len(gen['var_gen_cost(euro/MW)'][0]))] for t in intervals] for i, gen in enumerate(data)]
    #
    # # These constraints (following) are used to ensure that z_1[i][t][s_index] takes the value of power[i][t]
    # # when u_1[i][t][s_index] is 1 and takes the value 0 otherwise.
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         for s_index, _ in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             prob += z_1[i][t][s_index] <= u_1[i][t][s_index] * M
    #             prob += z_1[i][t][s_index] >= power[i][t] - M * (1 - u_1[i][t][s_index])
    #             prob += z_1[i][t][s_index] <= power[i][t]
    #         # definition of the level (βαθμίδας) of operation of unit g, t hour
    #         # the u variable that will take value = 1, will give us the info of what level are we in
    #         # so that we will be able to calculate the respective cost of power generation
    # for i, gen in enumerate(data):
    #     for t in intervals[1:]:
    #         prob += pl.lpSum(u_1[i][t][s_index] for s_index in range(0, len(gen['var_gen_cost(euro/MW)'][0]))) == 1
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    #             objective_terms += s * z_1[i][t][s_index] * input_data["Time_granularity"]
    #         for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][0]):
    #             # if power[i][t] belongs to level s_index, it should be less than or equal to max power of this level
    #             prob += power[i][t] <= gen['var_gen_cost(euro/MW)'][0][s_index] + M * (
    #                         1 - u_1[i][t][s_index]) - 0.002  # i can replace 0.002 with a parameter
    #             #     The following code block is consistent with Mixed Integer Linear Programming (MILP), and the use of the conditional statement here is not a problem.
    #             #     The reason is that the conditional statement if s_index > 0: is not introducing any non-linearity or conditional constraints within the MILP model itself.
    #             #     Instead, it's controlling whether a certain constraint is added to the problem based on the value of s_index, which is an index in the loop, not a decision
    #             #     variable in the MILP model.
    #             if s_index > 0:
    #                 # if power[i][t] belongs to level s_index, it should be greater than or equal to max power of this the previous level
    #                 prob += power[i][t] >= gen['var_gen_cost(euro/MW)'][0][s_index - 1] - M * (1 - u_1[i][t][s_index])
    #         # Constraint: if power[i][t] == 0, then u_1[i][t][0] must be 1
    #         # prob += u_1[i][t][0] >= 1 - M * power[i][t]  # probably not needed
    return prob, objective_terms, u_1

def create_ensure_variables_correctness_constraint(prob, data, intervals, state, startup, shutdown):
    for i, gen in enumerate(data):
        for t in intervals[1:]:
            # we ensure the correctness of startup & shutdown values
            prob += startup[i][t] >= state[i][t] - state[i][
                t - 1]  # If the generator switches on, this will enforce startup[i][t] to be 1.
            prob += startup[i][t] <= 1 - state[i][
                t - 1]  # If the generator was on at t-1, this will enforce startup[i][t] to be 0.
            prob += startup[i][t] <= state[i][
                t]  # If the generator is off at t, this will enforce startup[i][t] to be 0.
            prob += shutdown[i][t] >= state[i][t - 1] - state[i][
                t]  # If the generator switches off, this will enforce shutdown[i][t] to be 1.
            prob += shutdown[i][t] <= 1 - state[i][
                t]  # If the generator is on at t, this will enforce shutdown[i][t] to be 0.
            prob += shutdown[i][t] <= state[i][
                t - 1]  # If the generator was off at t-1, this will enforce shutdown[i][t] to be 0.
    return prob


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

# def create_max_transition_time_between_states_constraints_a(prob, data, u_2_dict, IntervalCount, intervals):
#     import copy
#     for gen in data:
#         gen_id = gen['gen_id']
#         # print('')
#         # print('gen_id: ', gen_id)
#         # for t in intervals[1:]:
#         # print('gen_id: ', gen_id)
#         for allowed_transition in gen['operating-state-transitions']:
#             from_oper_state_id = allowed_transition['from']
#             to_oper_states = copy.deepcopy(allowed_transition['transitions'])  # all allowed states to transition to
#             to_oper_states.append({'id': from_oper_state_id})  # also we can stay in the current state
#             # transition_data.append([from_oper_state_id, to_oper_states])
#             # print(transition_data)
#             # print('from: ', from_oper_state_id, 'to: ', to_oper_states)
#             # at this point we have 1 from id and 1 or more to ids
#
#             for next_state in to_oper_states:
#                 next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
#                 # print('id:', next_state_id)
#                 if from_oper_state_id == next_state_id:
#                     pass
#                 else:
#                     max_time_left = next_state['max-transition-time-left_a']  # if max-time key does not exist, use a very large number as the default value for max-time
#                     # if for any given time period in the beginning of the schedule we are in an operating state for more consecutive periods than max-time-left for
#                     # transition defines, then we cannot transit to that next specific operating state
#                     # if max_time_left <= IntervalCount - 3:
#                     for t in intervals[max_time_left:]:
#                         if (gen_id, t + 2, next_state_id) in u_2_dict:
#                                 prob += u_2_dict[(gen_id, t + 2, next_state_id)] <= 1 - (pl.lpSum(u_2_dict[(gen_id, t_prime, from_oper_state_id)] for t_prime in intervals[1:t + 2]) - t)
#                         else:
#                             pass
#             for tt in intervals[1:]:  # Start from 1 as we compare with the previous interval
#                 # Check if the generator entered the state at this interval
#                 # entered_state_now = (u_2_dict[(gen_id, t, from_oper_state_id)] - u_2_dict[(gen_id, t-1, from_oper_state_id)])
#                 for next_state in to_oper_states: # there must be an operating state id when we define the "to" state
#                     next_state_id = next_state['id']  # there must be an operating state id when we define the "to" state
#                     if from_oper_state_id == next_state_id:
#                         pass
#                     else:
#                         max_time = next_state['max-transition-time_a'] # if min-time key does not exist, use 0 as the default value for min-time
#                         for t in intervals[tt + max_time - 1:]:
#                             if (gen_id, t + 2, next_state_id) in u_2_dict:
#                                 # print(tt + max_time + 1)
#                                 # print(IntervalCount)
#                                 # if for any given time period we are in an operating state for more consecutive periods than max-time for transition defines, then
#                                 # we cannot transit to that next specific operating state
#                                 prob += u_2_dict[(gen_id, t + 2, next_state_id)] <= 1 - (pl.lpSum(u_2_dict[(gen_id, t_prime, from_oper_state_id)] for t_prime in intervals[tt:t+2]) - (t + 1 - tt))
#                             else:
#                                 pass
#
#     return prob

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

# when we activate the following constraint, we must activate also the min-max constraint
def create_res_pv_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast,
                                                 RES_forecast, RES_sum, M, s_power_minus):
    setpoint = [[pl.LpVariable(name=f'setpoint{i + 1}_{t}', lowBound=0, upBound=1) for t in intervals] for i in range(len(data))]
    Min_grid_capacity_1 = [pl.LpVariable(name=f'Min_grid_capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]  # for non-dispatchable res
    Min_grid_capacity_2 = [pl.LpVariable(name=f'Min_grid_capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    Min_Power_Calc = [[pl.LpVariable(name=f'Min_Power_Calc_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]

    s_Grid_Capacity_1 = [pl.LpVariable(name=f's_Grid_Capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_2 = [pl.LpVariable(name=f's_Grid_Capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_3 = [pl.LpVariable(name=f's_Grid_Capacity_3_{t}', lowBound=0, upBound=None) for t in intervals]

    m = [[pl.LpVariable(name=f'm_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]
    rel_var = [pl.LpVariable(name=f'rel_var_{t}', lowBound=0, upBound=None) for t in
               intervals]  # for non-dispatchable res
    g1 = [pl.LpVariable(name=f'g1_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g2 = [pl.LpVariable(name=f'g2_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g3 = [[pl.LpVariable(name=f'g3_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g4 = [[pl.LpVariable(name=f'g4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]

    Grid_Capacity1 = [pl.LpVariable(name=f'Grid_Capacity1_{t}', lowBound=0, upBound=None) for t in intervals]
    Grid_Capacity2 = [pl.LpVariable(name=f'Grid_Capacity2_{t}', lowBound=0, upBound=None) for t in intervals]
    Grid_Capacity3 = [pl.LpVariable(name=f'Grid_Capacity3_{t}', lowBound=0, upBound=None) for t in intervals]
    # M = 10000
    # for t in intervals[1:]:
    #     for i in PV:
    #         prob += power[i][t] == RES_forecast[t - 1][i]
    for t in intervals[1:]:
        prob += Grid_Capacity2[t] == input_data["Other_coefficients"]["x_res_pv_dynamic"] * pl.lpSum(data[i]['max_power(MW)'][t-1] * state[i][t] for i in CONV)  # P_Kt
        prob += Grid_Capacity1[t] == pl.lpSum(power[i][t] for i in CONV + RES_SP + PV_SP) - pl.lpSum(data[i]['min_power(MW)'][t-1] * state[i][t] for i in CONV)  #+0.003 # P_TEt Load_forecast[t] not including PV_power
        prob += Grid_Capacity3[t] == pl.lpSum(data[i]['max_power(MW)'][t-1] for i in RES+PV)  ###### από όσες RES+PV είναι διαθέσιμες
        ###############
        prob += (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * g2[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) <= M * (1 - g2[t]) * 10
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) >= -M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) <= M * g2[t] * 10   # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity3[t] + s_Grid_Capacity_3[t]) >= -M * g2[t] * 10  # "a_equals_c_if_g_is_0_neg"
        ################
        #
        prob += RES_sum[t] <= Grid_Capacity1[t] + s_Grid_Capacity_1[t]  # the actual power we expect the res + pv units to produce
        prob += RES_sum[t] <= Grid_Capacity2[t] + s_Grid_Capacity_2[t]
        prob += RES_sum[t] <= Grid_Capacity3[t] + s_Grid_Capacity_3[t]
        #
        prob += (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) - Min_grid_capacity_2[t] <= M * g1[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += Min_grid_capacity_2[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) <= M * (1 - g1[t]) * 10
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] <= M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] >= -M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_1[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) <= M * g1[t] * 10  # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_1[t] - (Grid_Capacity1[t] + s_Grid_Capacity_1[t]) >= -M * g1[t] * 10  # "a_equals_c_if_g_is_0_neg"
        # prob += pl.lpSum(state[i][t] * data[i]["min_power(MW)"] for i in RES) <= Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV)  # for wind parks από όσες RES είναι διαθέσιμες (και έχουν ισχύ > min - όχι η παρένθεση)
        for i in RES_SP + PV_SP:
            # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
            prob += power[i][t] <= setpoint[i][t] * data[i]['max_power(MW)'][t-1]
            # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
            ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
            prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['max_power(MW)'][t-1] <= M * g3[i][t] * 10
            prob += setpoint[i][t] * data[i]['max_power(MW)'][t-1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * (1 - g3[i][t]) * 10
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t-1] <= M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1"
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t-1] >= -M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1_neg"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * g3[i][t] * 10  # "a_equals_c_if_g_is_0"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -M * g3[i][t] * 10  # "a_equals_c_if_g_is_0_neg"
            # calculate the power of RES with setpoint based on the setpoint and the respective forecast
            # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
            prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t-1] <= M * g4[i][t] * 10
            prob += data[i]['min_power(MW)'][t-1] - Min_Power_Calc[i][t] <= M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= M * g4[i][t] * 10
            prob += power[i][t] >= Min_Power_Calc[i][t] - M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= Min_Power_Calc[i][t] + M * (1 - g4[i][t]) * 10
            prob += power[i][t] >= 0
            ##########
            # objective_terms += setpoint[i][t] * (-50) * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]
        prob += Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP) >= pl.lpSum(data[i]['max_power(MW)'][t-1] * setpoint[i][t] for i in RES_SP + PV_SP)  # ###### από όσες RES είναι διαθέσιμες και (έχουν ισχύ > min)  #  + rel_var[t]  # last term added for the case when all states of res are 0 (off)
        objective_terms += (s_Grid_Capacity_1[t] + s_Grid_Capacity_2[t] + s_Grid_Capacity_3[t]) * input_data["Cost_parameters"]["x_Grid_Capacity"]
            # m = setpoint * state
            # prob += m[i][t] <= setpoint[i][t]
            # prob += m[i][t] <= M * state[i][t]
            # prob += m[i][t] >= setpoint[i][t] - M * (1 - state[i][t])
            # prob += m[i][t] >= 0
        first_i = RES_SP[0]  # Take the first unit of the RES_SP as the reference
        for i in RES_SP[1:] + PV_SP:  # Compare every other unit to the first one
            prob += setpoint[first_i][t] == setpoint[i][t]  # equal setpoints for the same RES category (now we have one category - Non dispatchable res)
        for i in CONV + RES_no_SP + PV_no_SP:
            prob += setpoint[i][t] == 0.0
            # prob += m[i][t] == 0.0
    return prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_1, s_Grid_Capacity_2, s_Grid_Capacity_3
def create_res_pv_2_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast,
                                                 RES_forecast, RES_sum, M, s_power_minus):
    setpoint = [[pl.LpVariable(name=f'setpoint{i + 1}_{t}', lowBound=0, upBound=1) for t in intervals] for i in range(len(data))]
    Min_grid_capacity_1 = [pl.LpVariable(name=f'Min_grid_capacity_1_{t}', lowBound=None, upBound=None) for t in intervals]  # for non-dispatchable res
    Min_grid_capacity_2 = [pl.LpVariable(name=f'Min_grid_capacity_2_{t}', lowBound=None, upBound=None) for t in intervals]
    Min_Power_Calc = [[pl.LpVariable(name=f'Min_Power_Calc_{i + 1}_{t}', lowBound=None, upBound=None) for t in intervals] for i in range(len(data))]
    P_sp = [pl.LpVariable(name=f'P_sp_{t}', lowBound=None, upBound=None) for t in intervals]
    P_sp_1 = [pl.LpVariable(name=f'P_s_1_{t}', lowBound=None, upBound=None) for t in intervals]

    # s_Grid_Capacity_1 = [pl.LpVariable(name=f's_Grid_Capacity_1_{t}', lowBound=0, upBound=None) for t in intervals]
    s_Grid_Capacity_2 = [pl.LpVariable(name=f's_Grid_Capacity_2_{t}', lowBound=0, upBound=None) for t in intervals]
    # s_Grid_Capacity_3 = [pl.LpVariable(name=f's_Grid_Capacity_3_{t}', lowBound=0, upBound=None) for t in intervals]

    m = [[pl.LpVariable(name=f'm_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i in range(len(data))]
    rel_var = [pl.LpVariable(name=f'rel_var_{t}', lowBound=0, upBound=None) for t in
               intervals]  # for non-dispatchable res
    g1 = [pl.LpVariable(name=f'g1_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g2 = [pl.LpVariable(name=f'g2_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]
    g3 = [[pl.LpVariable(name=f'g3_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g4 = [[pl.LpVariable(name=f'g4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i in range(len(data))]
    g5 = [pl.LpVariable(name=f'g5_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals]

    Grid_Capacity1 = [pl.LpVariable(name=f'Grid_Capacity1_{t}', lowBound=None, upBound=None) for t in intervals]
    Grid_Capacity2 = [pl.LpVariable(name=f'Grid_Capacity2_{t}', lowBound=None, upBound=None) for t in intervals]
    Grid_Capacity3 = [pl.LpVariable(name=f'Grid_Capacity3_{t}', lowBound=None, upBound=None) for t in intervals]

    # P_RES = [pl.LpVariable(name=f'P_RES_{t}', lowBound=0, upBound=None) for t in intervals]
    # P_PV = [pl.LpVariable(name=f'P_PV_{t}', lowBound=0, upBound=None) for t in intervals]

    if input_data["Other_coefficients"]["PV_dispatch_method"] == 1:
        input_data["Other_coefficients"]["x_res_pv_dynamic"] = 1
        input_data["Other_coefficients"]["PV_Participation_coefficient"] = 100
        for i in RES_SP:
            for t in intervals[1:]:
                data[i]['availability'][t - 1] = 0


    for t in intervals[1:]:
        prob += Grid_Capacity2[t] == input_data["Other_coefficients"]["x_res_pv_dynamic"] * Load_forecast[t]  #pl.lpSum(power[i][t] for i in UNITS)
        # prob += Grid_Capacity1[t] == pl.lpSum(power[i][t] for i in UNITS) - pl.lpSum(data[i]['min_power(MW)'][t-1] * state[i][t] for i in CONV)  #+0.003 # P_TEt Load_forecast[t] not including PV_power
        prob += Grid_Capacity1[t] == Load_forecast[t] - pl.lpSum(data[i]['min_power(MW)'][t - 1] * state[i][t] for i in CONV) - input_data["Other_coefficients"]["include_PV"] * pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP)
        prob += Grid_Capacity3[t] == pl.lpSum(data[i]['availability'][t-1] for i in RES_SP) + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * pl.lpSum(data[i]['availability'][t-1] for i in PV_SP)  #+ pl.lpSum(data[i]['availability'][t-1] for i in PV_no_SP)  ###### από όσες RES+PV είναι διαθέσιμες
        ###############
        prob += Grid_Capacity3[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * g2[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) - Grid_Capacity3[t] <= M * (1 - g2[t]) * 10
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) <= M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_2[t] - (Grid_Capacity2[t] + s_Grid_Capacity_2[t]) >= -M * (1 - g2[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_2[t] - Grid_Capacity3[t] <= M * g2[t] * 10   # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_2[t] - Grid_Capacity3[t] >= -M * g2[t] * 10  # "a_equals_c_if_g_is_0_neg"
        ################
        #
        # prob += RES_sum[t] <= Grid_Capacity1[t] + s_Grid_Capacity_1[t]  # the actual power we expect the res + pv units to produce
        # prob += RES_sum[t] <= Grid_Capacity2[t] + s_Grid_Capacity_2[t]
        # prob += RES_sum[t] <= Grid_Capacity3[t] + s_Grid_Capacity_3[t]
        #
        prob += Grid_Capacity1[t] - Min_grid_capacity_2[t] <= M * g1[t] * 10  # multiplication by 1000 is used to make sure M*1000 > Grid_Capacity2 when no min-max constraints are applied
        prob += Min_grid_capacity_2[t] - Grid_Capacity1[t] <= M * (1 - g1[t]) * 10
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] <= M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1"
        prob += Min_grid_capacity_1[t] - Min_grid_capacity_2[t] >= -M * (1 - g1[t]) * 10  # "a_equals_b_if_g_is_1_neg"
        prob += Min_grid_capacity_1[t] - Grid_Capacity1[t] <= M * g1[t] * 10  # "a_equals_c_if_g_is_0"
        prob += Min_grid_capacity_1[t] - Grid_Capacity1[t] >= -M * g1[t] * 10  # "a_equals_c_if_g_is_0_neg"
        # prob += pl.lpSum(state[i][t] * data[i]["min_power(MW)"] for i in RES) <= Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV)  # for wind parks από όσες RES είναι διαθέσιμες (και έχουν ισχύ > min - όχι η παρένθεση)

        # max(Min_grid_capacity_1[t], 0)
        prob += P_sp_1[t] >= Min_grid_capacity_1[t]
        prob += P_sp_1[t] >= 0
        prob += P_sp_1[t] <= Min_grid_capacity_1[t] + M * (1 - g5[t])
        prob += P_sp_1[t] <= M * g5[t]
        prob += Min_grid_capacity_1[t] <= M * g5[t]

        prob += P_sp[t] <= P_sp_1[t]

        # prob += P_RES[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))
        # prob += P_PV[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in PV_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))

        # prob += P_RES[t] == P_sp[t]  # - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP)
        # prob += P_PV[t] * pl.lpSum(RES_forecast[t - 1][i] for i in RES_SP + PV_SP) == pl.lpSum(RES_forecast[t - 1][i] for i in PV_SP) * (P_sp[t] - pl.lpSum(power[i][t] for i in RES_no_SP + PV_no_SP))


        # calculate setpoint with reference to installed capacity
        if input_data["Other_coefficients"]["PV_dispatch_method"] == 0:
            temp_sum = pl.lpSum(data[j]['availability'][t - 1] for j in RES_SP)
            temp_sum_2 = pl.lpSum(data[j]['availability'][t - 1] for j in PV_SP)
            for i in RES_SP:
                prob += setpoint[i][t] * (temp_sum + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * temp_sum_2) == P_sp[t]  #* data[i]['availability'][t-1]  #- pl.lpSum(power[j][t] for j in RES_no_SP + PV_no_SP)
            for i in PV_SP:
                prob += setpoint[i][t] * (temp_sum + (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100) * temp_sum_2) == P_sp[t] * (input_data["Other_coefficients"]["PV_Participation_coefficient"]/100)  #* data[i]['availability'][t-1]

                # for i in PV_SP:
            #     prob += setpoint[i][t] * pl.lpSum(data[j]['availability'][t-1] for j in PV_SP) == P_PV[t]
        else:
            temp_sum_3 = pl.lpSum(data[j]['availability'][t - 1] for j in PV_SP)
            for i in RES_SP:
                prob += setpoint[i][t] == 0
            for i in PV_SP:
                prob += setpoint[i][t] * temp_sum_3 == P_sp[t]   #* data[i]['availability'][t-1]



        for i in RES_SP + PV_SP:
            # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
            prob += power[i][t] <= setpoint[i][t] * data[i]['availability'][t-1]
            # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
            ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
            prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['availability'][t-1] <= M * g3[i][t] * 10
            prob += setpoint[i][t] * data[i]['availability'][t-1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * (1 - g3[i][t]) * 10
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['availability'][t-1] <= M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1"
            prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['availability'][t-1] >= -M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1_neg"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * g3[i][t] * 10  # "a_equals_c_if_g_is_0"
            prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -M * g3[i][t] * 10  # "a_equals_c_if_g_is_0_neg"
            # calculate the power of RES with setpoint based on the setpoint and the respective forecast
            # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
            prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t-1] <= M * g4[i][t] * 10
            prob += data[i]['min_power(MW)'][t-1] - Min_Power_Calc[i][t] <= M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= M * g4[i][t] * 10
            prob += power[i][t] >= Min_Power_Calc[i][t] - M * (1 - g4[i][t]) * 10
            prob += power[i][t] <= Min_Power_Calc[i][t] + M * (1 - g4[i][t]) * 10
            prob += power[i][t] >= 0
            ##########
            objective_terms += setpoint[i][t] * (-50)  # * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]
        # for i in PV_SP:
        #     # prob += power[i][t] <= RES_forecast[t - 1][i]  # * state[i][t]
        #     prob += power[i][t] <= setpoint[i][t] * data[i]['max_power(MW)'][t - 1]
        #     # prob += setpoint[i][t] * data[i]['max_power(MW)'] <= data[i]['min_power(MW)'] + M * state[i][t]  # να προσθέσω ένα -ε στο δεύτερο μέλος--- μόνο για τις διαθέσιμες RES
        #     ##########    Calculate the minimum between RES_forecast[t - 1][i] and setpoint[i][t] * data[i]['max_power(MW)']
        #     prob += (RES_forecast[t - 1][i] + s_power_minus[i][t]) - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] <= M * g3[i][t] * 10
        #     prob += setpoint[i][t] * data[i]['max_power(MW)'][t - 1] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * (1 - g3[i][t]) * 10
        #     prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] <= M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1"
        #     prob += Min_Power_Calc[i][t] - setpoint[i][t] * data[i]['max_power(MW)'][t - 1] >= -M * (1 - g3[i][t]) * 10  # "a_equals_b_if_g_is_1_neg"
        #     prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) <= M * g3[i][t] * 10  # "a_equals_c_if_g_is_0"
        #     prob += Min_Power_Calc[i][t] - (RES_forecast[t - 1][i] + s_power_minus[i][t]) >= -M * g3[i][t] * 10  # "a_equals_c_if_g_is_0_neg"
        #     # calculate the power of RES with setpoint based on the setpoint and the respective forecast
        #     # "if Min_Power_Calc[i][t] < data[i]['min_power(MW)'] then power[i][t] = 0, else power[i][t] = Min_Power_Calc[i][t]"
        #     prob += Min_Power_Calc[i][t] - data[i]['min_power(MW)'][t - 1] <= M * g4[i][t] * 10
        #     prob += data[i]['min_power(MW)'][t - 1] - Min_Power_Calc[i][t] <= M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] <= M * g4[i][t] * 10
        #     prob += power[i][t] >= Min_Power_Calc[i][t] - M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] <= Min_Power_Calc[i][t] + M * (1 - g4[i][t]) * 10
        #     prob += power[i][t] >= 0
        #     ##########
        #     objective_terms += setpoint[i][t] * (-50)  # * input_data["Time_granularity"]
            # + 0.00000001 * setpoint[i][t]

        # prob += Min_grid_capacity_1[t] - pl.lpSum(power[j][t] for j in PV_no_SP + RES_no_SP) == pl.lpSum(data[i]['max_power(MW)'] * setpoint[i][t] for i in RES)  # ###### από όσες RES είναι διαθέσιμες και (έχουν ισχύ > min)  #  + rel_var[t]  # last term added for the case when all states of res are 0 (off)
        objective_terms += s_Grid_Capacity_2[t] * input_data["Cost_parameters"]["x_Grid_Capacity"]
            # m = setpoint * state
            # prob += m[i][t] <= setpoint[i][t]
            # prob += m[i][t] <= M * state[i][t]
            # prob += m[i][t] >= setpoint[i][t] - M * (1 - state[i][t])
            # prob += m[i][t] >= 0
        # first_i = RES[0]  # Take the first unit of the RES as the reference
        # for i in RES[1:]:  # Compare every other unit to the first one
        #     prob += setpoint[first_i][t] == setpoint[i][t]  # equal setpoints for the same RES category (now we have one category - Non dispatchable res)
        for i in CONV + RES_no_SP + PV_no_SP + Partially_Controllable:  #+ PV:
            prob += setpoint[i][t] == 0.0
            # prob += m[i][t] == 0.0
    return prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_2

def create_power_state_baseline_deviations_calculation_constraints(input_data, prob, objective_terms, data, intervals, power, state,
                                                                   RDAS_power_df,
                                                                   RDAS_state_df, CONV, M):
    deviation_1 = [[pl.LpVariable(name=f'dev_1_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in
                   enumerate(data)]
    deviation_2 = [[pl.LpVariable(name=f'dev_2_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in
                   enumerate(data)]
    y_4 = [[pl.LpVariable(name=f'y_4_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in
           enumerate(data)]
    y_5 = [[pl.LpVariable(name=f'y_5_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in
           enumerate(data)]
    # M = 10000
    for i in CONV:
        for t in intervals[1:]:
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] <= + M * y_4[i][t]  # + dev_1[i][t]
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] >= - M * (1 - y_4[i][t])  # - dev_1[i][t]
            # Constraint 1: If y=1, then d=d1 else d=-d1
            prob += (power[i][t] - RDAS_power_df.iat[i, t - 1]) - deviation_1[i][t] <= M * (1 - y_4[i][t])
            prob += (power[i][t] - RDAS_power_df.iat[i, t - 1]) - deviation_1[i][t] >= - M * (1 - y_4[i][t])
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] + deviation_1[i][t] <= M * y_4[i][t]
            prob += power[i][t] - RDAS_power_df.iat[i, t - 1] + deviation_1[i][t] >= - M * y_4[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] <= M * y_5[i][t]  # + dev_1[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] >= - M * (1 - y_5[i][t])  # - dev_1[i][t]
            # Constraint 1: If y=1, then d=d1 else d=-d1
            prob += (state[i][t] - RDAS_state_df.iat[i, t - 1]) - deviation_2[i][t] <= M * (1 - y_5[i][t])
            prob += (state[i][t] - RDAS_state_df.iat[i, t - 1]) - deviation_2[i][t] >= - M * (1 - y_5[i][t])
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] + deviation_2[i][t] <= M * y_5[i][t]
            prob += state[i][t] - RDAS_state_df.iat[i, t - 1] + deviation_2[i][t] >= - M * y_5[i][t]
            # if i in CONV:
            objective_terms += deviation_1[i][t] * 100 * input_data["Time_granularity"] + deviation_2[i][t] * 1000 * input_data["Time_granularity"]
    return prob, objective_terms, deviation_1, deviation_2, y_4, y_5
# def create_power_deviation_penalty(input_data, prob, objective_terms, power, intervals, CONV, M, data):
#     # so that to limit the change in power value of conventional units between t-1 to t dispatch period
#     y_6 = [[pl.LpVariable(name=f'y_6_{i + 1}_{t}', lowBound=0, upBound=1, cat='Binary') for t in intervals] for i, _ in enumerate(data)]
#     deviation_3 = [[pl.LpVariable(name=f'dev_3_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
#     # M = 10000
#     for i in CONV:
#         for t in intervals[1:]:
#             # if power[i][t] - power[i][t-1] >=0, then y_6 = 1
#             prob += power[i][t] - power[i][t-1] <= + M * y_6[i][t]
#             # if power[i][t] - power[i][t-1] <=0, then y_6 = 0
#             prob += power[i][t] - power[i][t-1] >= - M * (1 - y_6[i][t])
#
#             prob += (power[i][t] - power[i][t-1]) - deviation_3[i][t] <= M * (1 - y_6[i][t])
#             prob += (power[i][t] - power[i][t-1]) - deviation_3[i][t] >= - M * (1 - y_6[i][t])
#             prob += (power[i][t] - power[i][t-1]) + deviation_3[i][t] <= M * y_6[i][t]
#             prob += (power[i][t] - power[i][t-1]) + deviation_3[i][t] >= - M * y_6[i][t]
#
#
#             # if i in CONV:
#             objective_terms += deviation_3[i][t] * 10 * input_data["Time_granularity"]
#
#     return prob, objective_terms, deviation_3, y_6

def create_testing_mode_constraints(prob, objective_terms, input_data, data, power, intervals, CONV):
    s_power_testing_mode_plus = [[pl.LpVariable(name=f's_power_testing_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    s_power_testing_mode_minus = [[pl.LpVariable(name=f's_power_testing_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]

    for i in CONV:  # CONV + dispatchable RES (in all dispatchable units)
        for t in intervals[1:]:
            if data[i]['testing_mode_enabled'][t-1] == 1:
                prob += power[i][t] - s_power_testing_mode_minus[i][t] + s_power_testing_mode_plus[i][t] == data[i]['power_production_in_testing_mode'][t-1]
            else:
                pass
            objective_terms += s_power_testing_mode_minus[i][t] * input_data["Cost_parameters"]["x_testing_mode"] + s_power_testing_mode_plus[i][t] * input_data["Cost_parameters"]["x_testing_mode"]

    return prob, objective_terms

def create_availability_program(prob, objective_terms, input_data, data, power, intervals, CONV):
    # s_avail = [[pl.LpVariable(name=f's_avail_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    for i in range(len(data)):
        for t in intervals[1:]:
            prob += power[i][t] <= data[i]["availability"][t-1]  # - s_avail[i][t]
        # print(data[gen_id].get('gen_declaration'), float('inf'))

            # objective_terms += s_avail[i][t] * input_data["Cost_parameters"]["x_availability"]
            # prob += s_avail[i][t] == 0
    return prob, objective_terms





def create_OOS_mode_constraints(prob, objective_terms, input_data, data, power, intervals, PV_no_SP):
    s_power_OOS_less_plus = [[pl.LpVariable(name=f's_power_OOS_less_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
    s_power_OOS_more_minus = [[pl.LpVariable(name=f's_power_OOS_more_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]

    for i in range(len(data)):  # CONV + dispatchable RES (in all dispatchable units)
        if i in PV_no_SP:
            pass
        else:
            for t in intervals[1:]:
                if data[i]['OOS_mode_less_than_enabled'][t - 1] == 1:
                    prob += power[i][t] - s_power_OOS_less_plus[i][t] <= data[i]['power_production_in_OOS_mode_less_than'][t - 1]
                if data[i]['OOS_mode_more_than_enabled'][t - 1] == 1:
                    prob += power[i][t] + s_power_OOS_more_minus[i][t] >= data[i]['power_production_in_OOS_mode_more_than'][t - 1]


                objective_terms += s_power_OOS_less_plus[i][t] * input_data["Cost_parameters"]["x_OOS_less_than"] + s_power_OOS_more_minus[i][t] * input_data["Cost_parameters"]["x_OOS_more_than"]



    return prob, objective_terms







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

# def round_solution_values():
#     # Load the solution values from the JSON file
#     with open('solution_values.json', 'r') as f:
#         solution_values = json.load(f)
#
#     # Round the values to the third decimal place and handle small values
#     rounded_values = {}
#     small_values = {}
#
#     for k, v in solution_values.items():
#         rounded_value = round(v, 3)
#         rounded_values[k] = rounded_value
#         if rounded_value == 0 and v != 0:
#             small_values[k] = v
#
#     # Save the updated values back to the JSON file
#     with open('solution_values_rounded.json', 'w') as f:
#         json.dump(rounded_values, f, indent=4)
#
#     # Print the updated values to verify
#     # print("Rounded Values:")
#     # for var_name, value in rounded_values.items():
#     #     print(f"{var_name}: {value}")
#
#     # Print any small values that were rounded to zero
#     # if small_values:
#     #     print("\nSmall Values Rounded to Zero:")
#     #     for var_name, value in small_values.items():
#     #         print(f"{var_name}: {value}")

def define_problem_and_solve_problem(data, input_data, UNITS, RES, PV, CONV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_forecast, Load_forecast, intervals,
                             x_load, on_AGC, warmStart=False, keepFiles=False, logPath=None, timeLimit=None,
                             solver_name="highs", gapRel=None, gapAbs=None, threads=None,
                             solver_options=None, require_optimal=True):

    big_m_setting = input_data.get("optimization_parameters", {}).get("big_m", "auto")
    if big_m_setting == "auto":
        M = estimate_big_m(input_data, data, intervals)
    else:
        M = float(big_m_setting)
    print(f"Using big-M value: {M:g}")
    start_time = time.time()
    # Define the problem
    prob = pl.LpProblem(name="Rdas_DispatchScheduling", sense=pl.LpMinimize)

    IntervalCount = len(intervals)

    # Define constraints
    build_tracker = ConstraintBuildTracker(prob)
    objective_terms = 0
    with build_tracker.section("initial_conditions"):
        prob, power, state, RES_sum, startup, shutdown = create_global_variables(prob, data, intervals)
    with build_tracker.section("res_sum_definition"):
        prob = create_res_sum_calculation_constraint(prob, power, intervals, RES_sum, RES, PV, Partially_Controllable)
    with build_tracker.section("commitment_transition_logic"):
        prob = create_ensure_variables_correctness_constraint(prob, data, intervals, state, startup, shutdown)
    with build_tracker.section("variable_cost_curve"):
        prob, objective_terms, u_1 = create_variable_cost_curve_calculation_constraints(input_data, prob, objective_terms, power,
                                                                                             data, intervals, M, state, CONV)
    # prob, objective_terms, z_3 = create_thermal_state_startup_cost_variable_constraint(prob, objective_terms, data, intervals, u_2, startup) # u_2 --> u_2_dict & z_3 --> z_3_dict done

    #
    # for i, _ in enumerate(data):
    #     data[i]["max_power(MW)"] = 24 * [data[i]["max_power(MW)"]]
    #     data[i]["min_power(MW)"] = 24 * [data[i]["min_power(MW)"]]
    #     for operating_states in data[i]["operating-states"]:
    #         operating_states["max-power"] = 24 * [operating_states["max-power"]]
    #         operating_states["min-power"] = 24 * [operating_states["min-power"]]
    # print(data)

    data = produce_min_max_t(data, intervals)

    with build_tracker.section("unit_max_power_limits"):
        for gen in data:
            gen_id = gen['gen_id']
            for t in intervals[1:]:
                prob += power[gen_id][t] <= gen['max_power(MW)'][t-1]


    with build_tracker.section("min_max_handling"):
        prob, data, on_AGC = min_max_handling(prob, data, input_data, CONV, Partially_Controllable, on_AGC, intervals, u_1, state, power)
    # if input_data["constraints"]["min_max_constraint"]:
    #     # only for dispatchable units check 5.2.4.4 Constraints paragraph in "Διακήρυξη" pdf
    #     for gen in data:
    #         gen_id = gen['gen_id']
    #         if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
    #             for t in intervals[1:]:
    #                 # if constraint enabled -- we cannot go to the zone above technical maximum
    #                 prob += u_1[gen_id][t][-1] == 0
    #         else:
    #             pass
    # else:
    #     for gen in data:
    #         gen_id = gen['gen_id']
    #         if gen_id in CONV + Partially_Controllable:  # in current version dispatchable units are only the Conventional units
    #             for operating_state in data[gen_id]["operating-states"]:
    #                 if operating_state["isOperational"]:
    #                     for t in intervals[1:]:
    #                         operating_state["max-power"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
    #                         operating_state["min-power"][t-1] = 0
    #                 else:
    #                     for t in intervals[1:]:
    #                         operating_state["max-power"][t-1] = operating_state["min-power"][t-1] = 0
    #             for t in intervals[1:]:
    #                 data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["var_gen_cost(euro/MW)"][0][-1]
    #                 data[gen_id]["min_power(MW)"][t-1] = 0
    #         else:
    #             pass
    #
    # for i, _ in enumerate(data):
    #     # these units can provide secondary reserves - regulation
    #     # for i in CONV:
    #     agc_configuration = data[i].get("agc_configuration", {})
    #     if agc_configuration.get("isConnected", 0) == 1:
    #         on_AGC.append(i)
    #         for operating_states in data[i]["operating-states"]:
    #             if operating_states["isOperational"]:
    #                 for t in intervals[1:]:
    #                     operating_states["max-power"][t-1] = agc_configuration.get("maxLoad", operating_states["max-power"][t-1])
    #                     operating_states["min-power"][t-1] = agc_configuration.get("minLoad", operating_states["min-power"][t-1])
    #             else:
    #                 pass
    #     else:
    #         pass
    #
    #
    # for i, _ in enumerate(data):
    #     if i in Partially_Controllable:
    #         print("Partially_Controllable Unit:", i)
    #         for t in intervals[1:]:
    #             for operating_states in data[i]["operating-states"]:
    #                 if operating_states["isOperational"]:
    #                     if operating_states["max-power"][t-1] > data[i]["production_program"][t-1]:
    #                         if operating_states["min-power"][t-1] > data[i]["production_program"][t-1]:
    #                             for operating_states_2 in data[i]["operating-states"]:
    #                                 operating_states_2["max-power"][t - 1] = operating_states_2["min-power"][t-1] = 0
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[gen_id]["min_power(MW)"][t - 1] = 0
    #                             prob += state[gen_id][t] == 0
    #                         else:
    #                             operating_states["max-power"][t - 1] = data[i]["production_program"][t-1]
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #                     else:
    #                         if data[gen_id]["max_power(MW)"][t - 1] < data[i]["production_program"][t-1]:
    #                             pass
    #                         else:
    #                             data[gen_id]["max_power(MW)"][t - 1] = data[i]["production_program"][t-1]
    #
    #
    #                     # operating_states["max-power"][t-1] = min(operating_states["max-power"][t-1], data[i]["production_program"][t-1])
    #                     # data[gen_id]["max_power(MW)"][t - 1] = operating_states["max-power"][t - 1]
    #
    #                     # if operating_states["max-power"][t-1] < operating_states["min-power"][t-1]:
    #                     #     for operating_states in data[i]["operating-states"]:
    #                     #         operating_states["max-power"][t-1] = operating_states["min-power"][t-1] = data[gen_id]["max_power(MW)"][t-1] = data[gen_id]["min_power(MW)"][t-1] = 0
    #                     # else:
    #
    #                 else:
    #                     pass
    # print(data[5])










# constraints for PV & RES apart from setpoints' constraints
    with build_tracker.section("res_pv_forecast_tracking"):
        s_power_plus = [[pl.LpVariable(name=f's_power_plus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
        s_power_minus = [[pl.LpVariable(name=f's_power_minus_{i + 1}_{t}', lowBound=0, upBound=None) for t in intervals] for i, _ in enumerate(data)]
        for t in intervals[1:]:
            for i in RES_no_SP + PV_no_SP:
                prob += 100 * (power[i][t] - s_power_minus[i][t] + s_power_plus[i][t]) == 100 * RES_forecast[t - 1][i]
            for i in RES_SP + PV_SP:
                prob += power[i][t] - s_power_minus[i][t] <= RES_forecast[t - 1][i]
            for i in RES+PV:
                objective_terms += s_power_plus[i][t] * input_data["Cost_parameters"]["x_RES_PV_power_plus"] + s_power_minus[i][t] * input_data["Cost_parameters"]["x_RES_PV_power_minus"]
    #

        # objective_terms += s_min_a_left[gen_id][t] * 100000
    # print('data:', data)
    with build_tracker.section("operating_state_power_levels"):
        prob, objective_terms, u_2_dict, shutdown_states = create_operating_states_power_levels_constraints(input_data, prob, objective_terms, power, state, data, intervals, CONV, RES, PV, M)  # u_2 --> u_2_dict done
    # if input_data["constraints"]["availability_constraint"]:
    with build_tracker.section("availability_program"):
        prob, objective_terms = create_availability_program(prob, objective_terms, input_data, data, power, intervals, CONV)
    print('')
    # print(data)
    print('')
    #  prob = create_min_max_constraints(prob, power, data, intervals, state, u_2) # u_2 --> u_2_dict
    # if input_data["constraints"]["gen_declaration_constraint"]:
    #     prob = create_generation_declaration(prob, data, power, intervals)
    if input_data["constraints"]["ramp_up_down_constraints"]:
        with build_tracker.section("ramp_up_down"):
            prob, ramp_relax, objective_terms = create_ramp_up_down_constraints(input_data, prob, power, data, intervals, objective_terms)
    if input_data["constraints"]["allowed_thermal_states_transition_constraints"]:
        with build_tracker.section("allowed_operating_state_transitions"):
            prob, objective_terms = create_allowed_operating_states_transition_constraints(prob, objective_terms, data, intervals, u_2_dict, M) # u_2 --> u_2_dict done
    # if input_data["constraints"]["operating_states_min_time_constraint"]:
    #     prob = create_operating_state_min_time_constraints(prob, data, u_2_dict, IntervalCount, intervals) # u_2 --> u_2_dict
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        with build_tracker.section("min_transition_time_between_states_a"):
            prob, objective_terms = create_min_transition_time_between_states_constraints_a(prob, objective_terms, input_data, data, u_2_dict, intervals)
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        with build_tracker.section("min_transition_time_between_states_b"):
            prob,  objective_terms = create_min_transition_time_between_states_constraints_b(prob,  objective_terms, input_data, data, u_2_dict, intervals)
    # if input_data["constraints"]["rdas_deviations_calculation_constraints"] and power_baseline is not None and state_baseline is not None:
    #     prob, objective_terms, deviation_1, deviation_2, y_4, y_5 = create_power_state_baseline_deviations_calculation_constraints(input_data, prob, objective_terms, data, intervals, power,
    #         state, power_baseline, state_baseline, CONV, M)
    # if input_data["constraints"]["power_deviation_penalty"]:
    #     prob, objective_terms, deviation_3, y_6 = create_power_deviation_penalty(input_data, prob, objective_terms, power, intervals, CONV, M, data)
    if input_data["constraints"]["load_production_balance_constraint"]:
        with build_tracker.section("load_balance"):
            prob, objective_terms, s_load_minus, s_load_plus = create_production_load_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV, x_load)
    # if input_data["constraints"]["load_production_Energy_balance_constraint"]:
    #     prob, objective_terms, s_load_minus, s_load_plus = create_production_load_Energy_balance_constraint(prob, objective_terms, intervals, Load_forecast, power, data, CONV, x_load)
    if input_data["constraints"]["primary_active_power_reserves_constraint"] or input_data["constraints"]["secondary_active_power_reserves_constraint"] or input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        with build_tracker.section("largest_online_units"):
            N_1, N_2 = find_N_1_N_2_thermal_units(prob, CONV, RES, PV, state, data, M, intervals)
    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        with build_tracker.section("primary_active_power_reserves"):
            prob, objective_terms, primary_ActPR_plus, primary_ActPR_minus, primary_APRR, s_primary_APR_upwards, s_primary_APR_downwards = create_primary_active_power_reserves_constraint(
                prob, input_data, objective_terms, power, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, N_1, N_2)
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        with build_tracker.section("secondary_active_power_reserves"):
            prob, objective_terms, y_plus, y_minus, secondary_ActPR_plus, secondary_ActPR_minus, secondary_APRR, s_secondary_APR_upwards, s_secondary_APR_downwards = create_secondary_active_power_reserves_constraint(
                prob, input_data, objective_terms, power, primary_ActPR_plus, primary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, N_1, N_2)
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        with build_tracker.section("tertiary_active_power_reserves"):
            prob, objective_terms, tertiary_ActPR_plus, tertiary_ActPR_minus, tertiary_APRR, s_tertiary_APR_upwards, s_tertiary_APR_downwards = create_tertiary_active_power_reserves_constraint(
                prob, input_data, objective_terms, y_plus, y_minus, power, primary_ActPR_plus, primary_ActPR_minus, secondary_ActPR_plus, secondary_ActPR_minus, state, u_2_dict, data, intervals, on_AGC, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, RES_sum, Load_forecast, M, PV, N_1, N_2)
    if input_data["constraints"]["forbidden_zones_constraint"]:
        with build_tracker.section("forbidden_zones"):
            prob, objective_terms, y_zone, s_forbidden_zones_plus, s_forbidden_zones_minus = create_forbidden_zones_constraint(prob, objective_terms, input_data, power, data, intervals, CONV, M)
    if input_data["constraints"]["must_run_units_constraint"]:
        with build_tracker.section("must_run_units"):
            prob, objective_terms, s_must_run = create_mustRun_constraints(prob, objective_terms, input_data, data, intervals, state)
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        with build_tracker.section("res_pv_dispatch_variables"):
            prob, objective_terms, setpoint, Min_grid_capacity_1, Min_grid_capacity_2, Min_Power_Calc, m, rel_var, g1, g2, g3, g4, Grid_Capacity1, Grid_Capacity2, Grid_Capacity3, s_Grid_Capacity_2 = create_res_pv_2_dispatch_variables_constraints(prob, objective_terms, input_data, power, state, data, intervals, UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, Partially_Controllable, Load_forecast, RES_forecast, RES_sum, M, s_power_minus)
    else:
        with build_tracker.section("res_curtailment_objective"):
            for i in RES:
                for t in intervals[1:]:
                    objective_terms += (
                            (RES_forecast[t - 1][i] - power[i][t]) * 1000 * input_data["Time_granularity"]  #RES_forecast[t - 1][i]
                    )
                    # pass
    if input_data["constraints"]["testing_mode_constraints"]:
        with build_tracker.section("testing_mode"):
            prob, objective_terms = create_testing_mode_constraints(prob, objective_terms, input_data, data, power, intervals, CONV)
    if input_data["constraints"]["OOS_mode_constraints"]:
        with build_tracker.section("oos_mode"):
            prob, objective_terms = create_OOS_mode_constraints(prob, objective_terms, input_data, data, power, intervals, PV_no_SP)
    # if input_data["constraints"]["operating_states_max_time_constraints"]:
    #     prob = create_operating_state_max_time_constraints(prob, data, u_2_dict, IntervalCount, intervals, CONV, RES)
    # if input_data["constraints"]["operating_states_max_transition_time_between_states_constraint_a"]:
    #     prob = create_max_transition_time_between_states_constraints_a(prob, data, u_2_dict, IntervalCount, intervals)
    if input_data["constraints"]["operating_states_max_transition_time_between_states_constraint_b"]:
        with build_tracker.section("max_transition_time_between_states_b"):
            prob, objective_terms = create_max_transition_time_between_states_constraints_b(prob, objective_terms, input_data, data, u_2_dict, IntervalCount, intervals)
    if input_data["constraints"]["states_time_constraint"]:
        # print('--------- states --------')
        with build_tracker.section("state_minimum_time"):
            prob, objective_terms = create_min_time_states_constraints_states(prob, objective_terms, input_data, data, state, intervals, startup, shutdown)

    # prob += u_2_dict[(2, 8, 4)] == 1
    # prob += u_2_dict[(2, 16, 6)] == 1
    # prob += u_2_dict[(0, 4, 6)] == 1
    # prob += u_2_dict[(0, 1, 4)] == 1
    # prob += u_2_dict[(0, 2, 4)] == 1
    # prob += u_2_dict[(0, 3, 4)] == 1
    # prob += u_2_dict[(0, 4, 4)] == 1
    # prob += u_2_dict[(0, 5, 4)] == 1
    # prob += u_2_dict[(0, 6, 4)] == 1
    #
    # for t in intervals[1:]:
    #     prob += s_Grid_Capacity_1[t] == s_Grid_Capacity_2[t] == s_Grid_Capacity_3[t] == 0


    # prob += power[0][2] == 11
    # prob += power[2][7] == 2
    # prob += u_2_dict[(1, 10, 2)] == 1
    # prob += u_2_dict[(1, 11, 3)] == 1
    # prob += u_2_dict[(1, 12, 4)] == 1
    # # prob += u_2_dict[(1, 13, 4)] == 1
    # prob += u_2_dict[(1, 14, 4)] == 1
    # prob += u_2_dict[(1, 15, 2)] == 1
    # prob += u_2_dict[(1, 16, 4)] == 1
    # prob += u_2_dict[(1, 17, 4)] == 1
    # prob += u_2_dict[(1, 10, 4)] == 0

    # prob += power[0][3] == 8.6
    # # prob += power[1][3] == 5.7
    # prob += power[0][1] == 15.6
    # # prob += power[1][1] == 17.3
    # prob += state[5][6] == 1
    # prob += state[5][5] == 1

    # prob += power[0][3] == 0
    # prob += power[1][3] == 0
    # prob += power[2][3] == 0
    # prob += state[0][10] == 1
    # prob += state[0][5] == 0
    # prob += state[0][6] == 0
    # prob += state[1][9] == 0
    # prob += power[0][3] == 0
    # prob += power[0][4] == 15.5
    # prob += power[0][5] == 8.5

    # prob += u_2_dict[(1, 10, 2)] == 1
    # prob += u_2_dict[(1, 11, 3)] == 1
    # prob += u_2_dict[(1, 12, 4)] == 1
    # prob += power[1][13] == 0

    # prob += u_1_dict[(0, 1, 0)] == 1
    # prob += u_2_dict[(0, 13, 6)] == 1

    # prob += u_2_dict[(gen_id, t, operating_state_id)] == 1

    with build_tracker.section("commitment_objective_terms"):
        for i, gen in enumerate(data):
            for t in intervals[1:]:
                if i in CONV:
                    objective_terms += (
                            gen.get('start_up_cost(euro)', 0) * startup[i][t] + gen.get('shut_down_cost(euro)', 0) *
                            shutdown[i][t] + state[i][t] * (+100) * input_data["Time_granularity"]
                    )
                #
                # the two following conditional terms, could be commented out as there is already the
                # term that pushes the solution to be as close to the rdas solution, as possible

                # if i in RES:
                #     objective_terms += power[i][t] * (-11320) * input_data["Time_granularity"]  #(-1000) -11320

    # objective_terms += 13123000000

    # Add the objective terms to the objective function
    with build_tracker.section("objective"):
        prob += pl.lpSum(objective_terms)

    # Check if the problem is an MIP problem
    if prob.isMIP():
        print("The problem is a Mixed-Integer Programming (MIP) problem.")
    # # Solve the problem
    # prob.solve()

    # Specify the path for the log file
    # log_file_path = "solver_log.txt"
    # path_to_glpk = r'C:\Users\NikosPapadopoulos\PycharmProjects\pythonProject\venv\Lib\site-packages\pulp\solverdir\glpk\glpk-4.65\w64\glpsol.exe'

    # solver = pl.GLPK_CMD(path=path_to_glpk, msg=True, timeLimit=620)
    # path_to_cplex = r'C:\Program Files\IBM\ILOG\CPLEX_Studio_Community2211\cplex\bin\x64_win64\cplex.exe'

    # solver = pl.GUROBI(msg=True, timeLimit=timeLimit, gapRel=0.1)  # gapRel=0.1,

    # solver = pl.CPLEX_PY(msg=True, timeLimit=timeLimit, gapRel=0.1)  # gapRel=0.1
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles, gapRel=0.1)




    # solver = pl.PULP_CBC_CMD(msg=True, timeLimit=timeLimit) #gapRel=0.1 # logPath=log_file_path  keepFiles=keepFiles, warmStart=warmStart
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles)

    # Set the number of threads
    # import os
    # os.environ['OMP_NUM_THREADS'] = '8'
    #
    # # Load the initial values from the JSON file
    # with open('solution_values.json', 'r') as f:
    #     initial_values = json.load(f)
    #
    # start_time_init = time.time()
    # print("initialization is starting")
    # #  Set initial values for warm start
    # for var_name, value in initial_values.items():
    #     if var_name in prob.variablesDict():
    #         var = prob.variablesDict()[var_name]
    #         var.setInitialValue(value)
    #
    # print("initialization is completed")
    # end_time_init = time.time()
    #
    # initialization_time = end_time_init - start_time_init
    # print("Initialization time:", round(initialization_time, 3), "seconds")
    # print('')

    # solver = HiGHS_CMD(path=r'C:\Users\NikosPapadopoulos\PycharmProjects\pythonProject4\venv\Lib\site-packages\HiGHS_build\RELEASE\bin\highs.exe', options=['--parallel choose'], msg=True, keepFiles=True)  # timeLimit=450
    # solver = pl.SCIP_CMD(msg=True, timeLimit=timeLimit, keepFiles=keepFiles)
    # solver = pl.PULP_CBC_CMD(msg=True, keepFiles=True, warmStart=True)  #gapRel=0.1 # logPath=log_file_path  keepFiles=keepFiles, warmStart=warmStart
    # prob.solve(solver)
    # print(pl.listSolvers(onlyAvailable=True))
    # print(pl.listSolvers())
    # Define solver and set parameters
    # solver = pl.PULP_CBC_CMD(options=[
    #     'maxSolutions 1',  # Limit the number of solutions # 'sec 120',  # Set time limit to 120 seconds
    #
    #     'ratio 0.1',  # Set gap tolerance to 1%
    #     'threads 8'  # Use 4 threads
    #     # Additional parameters as needed
    # ])
    # prob.solve(highs_solver)
    constraint_sections = build_tracker.summary()
    print("Constraint build sections:")
    for section in constraint_sections:
        print(
            f"  {section['section']}: "
            f"+{section['constraints_added']} constraints, "
            f"+{section['variables_added']} variables"
        )

    renamed_constraints = name_auto_constraints(prob)
    print(f"Named anonymous constraints: {renamed_constraints}")

    # Write the model to an MPS file without solving

    mps_filename = "example_model.mps"
    prob.writeMPS(mps_filename)

    print(f"Model successfully written to {mps_filename} without solving.")
    end_time = time.time()
    execution_time = end_time - start_time
    print(".mps file creation time:", round(execution_time, 3), "seconds")
    print('')

    solver_name = (solver_name or "highs").lower()
    solver_options = solver_options or {}
    if solver_name == "highs":
        solver = pl.HiGHS(
            msg=True, timeLimit=timeLimit, gapRel=gapRel, gapAbs=gapAbs, threads=threads,
            **solver_options)
    elif solver_name == "cbc":
        solver = pl.PULP_CBC_CMD(
            msg=True, timeLimit=timeLimit, keepFiles=keepFiles, warmStart=warmStart,
            logPath=logPath, gapRel=gapRel, gapAbs=gapAbs, threads=threads)
    else:
        raise ValueError(f"Unsupported solver '{solver_name}'. Use 'highs' or 'cbc'.")
    print(f"Using solver backend: {solver_name}")

    print("Number of constraints:", prob.numConstraints())
    print("Number of variables:", prob.numVariables())
    print("")
    prob.solve(solver)

    Solution_Status = pl.LpStatus[prob.status]
    print("Objective function cost =", round(pl.value(prob.objective), 2))
    print('Status: ', pl.LpStatus[prob.status])
    print('')

    end_time_2 = time.time()
    execution_time_2 = end_time_2 - start_time
    print("DS execution time:", round(execution_time_2, 3), "seconds")
    print('')

    if require_optimal and Solution_Status != "Optimal":
        raise RuntimeError(
            f"Solver finished with status '{Solution_Status}', but an optimal solution is required. "
            "Increase/remove the time limit, relax require_optimal, or inspect the solver log."
        )

    # if pl.LpStatus[prob.status] == 'Optimal':
    #     print("Objective function cost =", round(pl.value(prob.objective), 5))
    # else:
    #     print("Problem not solved successfully. Status:", pl.LpStatus[prob.status])
    # if logPath == None:
    #     pass
    # else:
    #     try:
    #         with open(log_file_path, 'r') as file:
    #             solver_output = file.read()
    #         # print(solver_output)
    #         # Variable to store the matched line
    #         result_line = ""
    #         # Open the file in read mode
    #         with open(log_file_path, 'r') as file:
    #             # Iterate over each line
    #             for line in file:
    #                 # Check if the line starts with "Result -"
    #                 if line.startswith("Result -"):
    #                     result_line = line.strip()  # Using strip() to remove any leading/trailing whitespace
    #                     break  # Exit the loop once the line is found
    #         # result_line contains the desired line or is an empty string if no match was found
    #         print(result_line)
    #     except FileNotFoundError:
    #         print("Log file not found. Please check the solver and file path.")
    #     print('')
    #
    # # Extract values from the solved problem
    # solution_values = {v.name: v.varValue for v in prob.variables()}
    # # Serialize and save the dictionary to a file
    # with open('solution_values.json', 'w') as file:
    #     json.dump(solution_values, file)

    # Print the results
    # for v in prob.variables():
    #     print(v.name, "=", v.varValue)
    # Solution_Status = pl.LpStatus[prob.status]
    # print("Objective function cost =", round(pl.value(prob.objective), 2))
    # print('Status: ', Solution_Status)
    # print('')
    # print('# Must_run_units:', count_mru.value())

    # check the status
    # if pl.LpStatus[prob.status] == 'Optimal':
    #     print("The solution is optimal.")
    # else:
    #     print("The solution is not optimal.")


    # def categorize_variables(model):
    #     binary_vars = []
    #     integer_vars = []
    #     continuous_vars = []
    #
    #     for var in model.variables():
    #         if var.cat == 'Binary':
    #             binary_vars.append(var)
    #         elif var.cat == 'Integer':
    #             integer_vars.append(var)
    #         else:
    #             continuous_vars.append(var)
    #
    #     return binary_vars, integer_vars, continuous_vars
    #
    # # Get categorized variables
    # binary_vars, integer_vars, continuous_vars = categorize_variables(prob)
    #
    # # # Display the lists
    # # print("Binary Variables:", [var.name for var in binary_vars])
    # # print("Integer Variables:", [var.name for var in integer_vars])
    # # print("Continuous Variables:", [var.name for var in continuous_vars])
    #
    # # Total_cost = [0] * len(Load_forecast)
    # # for t in intervals[1:]:
    # #     for i, gen in enumerate(data):
    # #         if i in CONV:
    # #
    # #             if input_data["constraints"]["primary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += primary_ActPR_plus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][0] + \
    # #                                  primary_ActPR_minus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][1]
    # #             if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += secondary_ActPR_plus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][0] + \
    # #                                  secondary_ActPR_minus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][1]
    # #             if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
    # #                 Total_cost[t] += tertiary_ActPR_plus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][0] + \
    # #                                  tertiary_ActPR_minus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][1]
    # #
    # #             Total_cost[t] += gen.get('start_up_cost(euro)', 0) * startup[i][t].value() + gen.get(
    # #                 'shut_down_cost(euro)', 0) * shutdown[i][t].value()
    # #             # primary_ActPR_plus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][0] + \
    # #             # primary_ActPR_minus[i][t].value() * gen["Primary_APR_Cost(euro/MW)"][1] + \
    # #             # + tertiary_ActPR_plus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][0] + \
    # #             # tertiary_ActPR_minus[i][t].value() * gen["Tertiary_APR_Cost(euro/MW)"][1] +
    # #             # secondary_ActPR_plus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][0] + \
    # #             # secondary_ActPR_minus[i][t].value() * gen["Secondary_APR_Cost(euro/MW)"][1] \
    # #
    # #             for s_index, s in enumerate(gen['var_gen_cost(euro/MW)'][1]):
    # #                 Total_cost[t] += s * z_1[i][t][s_index].value()
    # #             for s_2_index, s_2 in enumerate(
    # #                     gen['Thermal_state_costs'][0]):  # for startup from a specific previous hour's thermal state
    # #                 # print(i,t,z_3[i][t][s_2_index].value())
    # #                 # print(u_2[i][t-1][s_2_index].value())
    # #                 Total_cost[t] += s_2 * z_3[i][t][s_2_index].value()
    # #             for s_3_index, s_3 in enumerate(
    # #                     gen['Thermal_state_costs'][1]):  # for remaining in a specific thermal state every hour t
    # #                 Total_cost[t] += s_3 * u_2[i][t][s_3_index].value()
    # #         # print(round(Total_cost[t],2))
    # # for t in intervals[1:]:
    # #     Total_cost[t] = round(Total_cost[t],
    # #                           2)  # we should divide by 4 some cost variables because the respective cost is calculated per hour
    # # Total_cost = [0, 0]
    solve_metadata = {
        "solver": solver_name,
        "solution_status": Solution_Status,
        "objective_value": round(pl.value(prob.objective), 8),
        "big_m": M,
        "num_constraints": prob.numConstraints(),
        "num_variables": prob.numVariables(),
        "anonymous_constraints_named": renamed_constraints,
        "constraint_sections": constraint_sections,
        "mps_file": mps_filename,
        "model_build_and_solve_seconds": round(execution_time_2, 3),
    }

    return prob.variables(), RES, Solution_Status, solve_metadata

# def define_and_solve_problem(binary_vars, integer_vars, continuous_vars):
#
#     start_time_3 = time.time()
#     # Create the HiGHS model
#     model = highspy.Highs()
#     # Set the MIP feasibility tolerance to 1e-2
#     # model.setOptionValue('mip_feasibility_tolerance', 1e-8)
#
#     # Retrieve the options dictionary
#     # options = model.getOptions()
#
#     # List all public attributes (options)
#     # available_options = [attr for attr in dir(options) if not attr.startswith('_')]
#
#     # print("Available options:")
#     # for option in available_options:
#     #     print(option)
#
#     # Read a model from MPS file model.mps
#     filename = "example_model.mps"
#     status = model.readModel(filename)
#     print('Reading model file ', filename, ' returns a status of ', status)
#     # num_cols = model.getNumCol()
#     #####################
#     # Create sets of variable names for efficient lookup
#     # binary_var_names = set(var.name for var in binary_vars)
#     # integer_var_names = set(var.name for var in integer_vars)
#     # continuous_var_names = set(var.name for var in continuous_vars)
#     # #
#     # # #############################
#     # initialize the variables values using a previous solution
#     # with open('Final_highsNative_solution_values.json', 'r') as file:
#     #     initial_solution_dict = json.load(file)
#
#
#
# #######################################################################
# #####################################################################################
#
#
#     # # number of decision variables in our new model
#     # num_vars = model.getNumCol()
#     # initial_values = [float(0)] * num_vars
#     # # Create a mapping from model variable names to indices
#     # var_name_to_index = {}
#     # for idx in range(num_vars):
#     #     status, var_name = model.getColName(idx)
#     #     if status == highspy.HighsStatus.kOk:
#     #         var_name_to_index[var_name] = idx
#     #     else:
#     #         print(f"Failed to get name for variable at index {idx}")
#     # # Assign values from the initial solution dictionary
#     # for var_name, value in initial_solution_dict.items():
#     #     if var_name in var_name_to_index:   # and not var_name.startswith('s_') and not var_name.startswith('ramp_relax'):
#     #         if var_name in integer_var_names:  #  and not var_name.startswith('state') and not var_name.startswith('u_2'):
#     #             index = var_name_to_index[var_name]
#     #             initial_values[index] = abs(round(value, 0))  #  round(value, 0)
#     #         else:
#     #             index = var_name_to_index[var_name]
#     #             initial_values[index] = abs(round(value, 3))
#     #     else:
#     #         print(f"Warning: Variable '{var_name}' in the initial solution is not initialized (does not exist in the model or it is a relaxation variable).")
#     # print('initial values: ', initial_values)
#     # # Create a HighsSolution object
#     # initial_solution = HighsSolution()
#     #
#     #
#     # # Set the col_value attribute
#     # initial_solution.col_value = initial_values  # List of variable values
#     # # Set the initial solution
#     # status = model.setSolution(initial_solution)
#     # if status == highspy.HighsStatus.kOk:
#         # print("Initial solution set successfully.")
#         # Run the solver
#         # Set a time limit of 1 hour (3600 seconds)
#     status = model.setOptionValue('time_limit', 1000)
#     if status == highspy.HighsStatus.kOk:
#         print("Time limit set to 10800 seconds.")
#     else:
#         print(f"Failed to set time limit. Status: {status}")
#     # Solve the problem
#     model.run()
#     # Write the solution to a .sol file
#     model.writeSolution("DispachScheduling-highsNative.sol", 0)
#     print('Solution status = ', model.modelStatusToString(model.getModelStatus()))
#     Solution_Status = model.modelStatusToString(model.getModelStatus())
#     # create highsNative_solution_values.json file
#
#     sol_file_path = "DispachScheduling-highsNative.sol"
#     # variable_names, variable_values = read_sol_file(sol_file_path)
#     # Create a dictionary mapping variable names to their values
#     # solution_dict = {name: value for name, value in zip(variable_names, variable_values)}
#     # with open('Final_highsNative_solution_values.json', 'w') as file:
#     #     json.dump(solution_dict, file)
#
#     # # Get the solution
#     # model.getSolution()
#     # # print("solution: ", solution)
#     # # Get the objective value
#     # objective_value = model.getObjectiveValue()
#     #
#     # # Print the solution
#     # print("Objective value:", objective_value)
#     #
#     # info = model.getInfo()
#     # print('')
#     # print('Primal solution status = ', model.solutionStatusToString(info.primal_solution_status))
#     # # print('Dual solution status = ', model.solutionStatusToString(info.dual_solution_status))
#
#
#
#
#     end_time_3 = time.time()
#     execution_time = end_time_3 - start_time_3
#     print("DS execution time:", round(execution_time, 3), "seconds")
#     print('')
#     return solution_dict, Solution_Status

def solution_processing(solution, input_data):
    # solution data processing & manipulation
    # --------------------------------------------------------------------------------------------------------------------#
    # Create a dataframe containing the RDAS solution
    import re
    import pandas as pd
    start_time_2 = time.time()
    # Create empty lists to hold decision variable data
    power_values = []
    startup_values = []
    shutdown_values = []
    state_values = []

    s_power_plus_values = []
    s_power_minus_values = []

    #     y_up_values = []
    #     y_down_values = []
    # s_ru_values = []
    # s_rd_values = []




    #     on_prev_values = []
    #     remaining_run_values = []
    z_1_values = []
    u_1_values = []
    u_2_values = []
    delta_values = []
    # z_3_values = []
    # y_res_1_values = []
    unit_cost_values = []
    # Count_values = []
    RES_sum_values = []



    # s_res_values = []
    # y_res_3_values = []
    # y_res_2_values = []
    # k_value = []
    #
    # Percentage_of_Usage_values = []

    # Grid_Capacity_values = []




    if 1:  #input_data["constraints"]["availability_constraint"]:
        s_avail_values = []
        for v in solution:
            if v.name.startswith('s_avail'):
                s_avail_values.append((v.name, v.varValue))
        s_avail_values = sorted(s_avail_values, key=extract_numbers)
        print(s_avail_values)
        s_avail_values_df = pd.DataFrame(s_avail_values, columns=['Variable', 'Value'])
    else:
        s_avail_values_df = pd.DataFrame()

    if input_data["constraints"]["OOS_mode_constraints"]:
        s_power_OOS_less_plus_values = []
        s_power_OOS_more_minus_values = []
        for v in solution:
            if v.name.startswith('s_power_OOS_less_plus_'):
                s_power_OOS_less_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_power_OOS_more_minus_'):
                s_power_OOS_more_minus_values.append((v.name, v.varValue))
        s_power_OOS_less_plus_values = sorted(s_power_OOS_less_plus_values, key=extract_numbers)
        s_power_OOS_more_minus_values = sorted(s_power_OOS_more_minus_values, key=extract_numbers)
        s_power_OOS_less_plus_df = pd.DataFrame(s_power_OOS_less_plus_values, columns=['Variable', 'Value'])
        s_power_OOS_more_minus_df = pd.DataFrame(s_power_OOS_more_minus_values, columns=['Variable', 'Value'])

        s_power_OOS_less_plus_df = extract_gen_hour(s_power_OOS_less_plus_df)
        s_power_OOS_less_plus_df = pivot_df(s_power_OOS_less_plus_df)

        s_power_OOS_more_minus_df = extract_gen_hour(s_power_OOS_more_minus_df)
        s_power_OOS_more_minus_df = pivot_df(s_power_OOS_more_minus_df)

    else:
        # Create empty DataFrame to return
        s_power_OOS_less_plus_df = s_power_OOS_more_minus_df = pd.DataFrame()

    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        s_min_a_left_values = []
        s_min_a_1_values = []
        for v in solution:
            if v.name.startswith('s_min_a_left'):
                s_min_a_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_a_1'):
                s_min_a_1_values.append((v.name, v.varValue))
        s_min_a_left_values = sorted(s_min_a_left_values, key=extract_numbers)
        s_min_a_1_values = sorted(s_min_a_1_values, key=extract_numbers)
        s_min_a_left_df = pd.DataFrame(s_min_a_left_values, columns=['Variable', 'Value'])
        s_min_a_1_df = pd.DataFrame(s_min_a_1_values, columns=['Variable', 'Value'])
        # s_min_a_left_df = extract_gen_hour(s_min_a_left_df)
        # s_min_a_left_df = pivot_df(s_min_a_left_df)
        #
        # s_min_a_1_df = extract_gen_hour(s_min_a_1_df)
        # s_min_a_1_df = pivot_df(s_min_a_1_df)
    else:
        # Create empty DataFrame to return
        s_min_a_left_df = s_min_a_1_df = pd.DataFrame()

    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        s_min_b_left_values = []
        s_min_b_1_values = []

        for v in solution:
            if v.name.startswith('s_min_b_left'):
                s_min_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_b_1'):
                s_min_b_1_values.append((v.name, v.varValue))
        s_min_b_left_values = sorted(s_min_b_left_values, key=extract_numbers)
        s_min_b_1_values = sorted(s_min_b_1_values, key=extract_numbers)
        s_min_b_left_df = pd.DataFrame(s_min_b_left_values, columns=['Variable', 'Value'])
        s_min_b_1_df = pd.DataFrame(s_min_b_1_values, columns=['Variable', 'Value'])
    else:
        s_min_b_left_df = s_min_b_1_df = pd.DataFrame()

    if input_data["constraints"]["operating_states_max_transition_time_between_states_constraint_b"]:
        s_max_b_left_values = []
        s_max_b_1_values = []

        for v in solution:
            if v.name.startswith('s_max_b_left'):
                s_max_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_max_b_1'):
                s_max_b_1_values.append((v.name, v.varValue))

        s_max_b_left_values = sorted(s_max_b_left_values, key=extract_numbers)
        s_max_b_1_values = sorted(s_max_b_1_values, key=extract_numbers)

        s_max_b_left_df = pd.DataFrame(s_max_b_left_values, columns=['Variable', 'Value'])
        s_max_b_1_df = pd.DataFrame(s_max_b_1_values, columns=['Variable', 'Value'])
    else:
        s_max_b_left_df = s_max_b_1_df = pd.DataFrame()


    if input_data["constraints"]["states_time_constraint"]:
        s_min_state_b_left_values = []
        s_min_state_b_1_values = []
        for v in solution:
            if v.name.startswith('s_min_state_b_left'):
                s_min_state_b_left_values.append((v.name, v.varValue))
            elif v.name.startswith('s_min_state_b_1'):
                s_min_state_b_1_values.append((v.name, v.varValue))
        s_min_state_b_left_values = sorted(s_min_state_b_left_values, key=extract_numbers)
        s_min_state_b_1_values = sorted(s_min_state_b_1_values, key=extract_numbers)
        s_min_state_b_left_df = pd.DataFrame(s_min_state_b_left_values, columns=['Variable', 'Value'])
        s_min_state_b_1_df = pd.DataFrame(s_min_state_b_1_values, columns=['Variable', 'Value'])
    else:
        s_min_state_b_left_df = s_min_state_b_1_df = pd.DataFrame()


    # if input_data["constraints"]["rdas_deviations_calculation_constraints"]:
    #     deviation_1_values = []
    #     y_4_values = []
    #     deviation_2_values = []
    #     y_5_values = []
    #     for v in solution:
    #         if v.name.startswith('dev_1'):
    #             deviation_1_values.append((v.name, v.varValue))
    #         elif v.name.startswith('y_4'):
    #             y_4_values.append((v.name, v.varValue))
    #         elif v.name.startswith('dev_2'):
    #             deviation_2_values.append((v.name, v.varValue))
    #         elif v.name.startswith('y_5'):
    #             y_5_values.append((v.name, v.varValue))
    #     y_4_values = sorted(y_4_values, key=extract_numbers)
    #     y_5_values = sorted(y_5_values, key=extract_numbers)
    #     deviation_1_values = sorted(deviation_1_values, key=extract_numbers)
    #     deviation_2_values = sorted(deviation_2_values, key=extract_numbers)
    #     deviation_1_df = pd.DataFrame(deviation_1_values, columns=['Variable', 'Value'])
    #     y_4_df = pd.DataFrame(y_4_values, columns=['Variable', 'Value'])
    #     deviation_2_df = pd.DataFrame(deviation_2_values, columns=['Variable', 'Value'])
    #     y_5_df = pd.DataFrame(y_5_values, columns=['Variable', 'Value'])
    # else:
    #     # Create empty DataFrame to return
    #     deviation_1_df = deviation_2_df = y_4_df = y_5_df = pd.DataFrame()
    if input_data["constraints"]["load_production_balance_constraint"] or input_data["constraints"]["load_production_Energy_balance_constraint"]:
        s_load_plus_values = []
        s_load_minus_values = []
        for v in solution:
            if v.name.startswith('s_load_plus'):
                s_load_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_load_minus'):
                s_load_minus_values.append((v.name, v.varValue))
        s_load_minus_values = sorted(s_load_minus_values, key=extract_single_value)
        s_load_plus_values = sorted(s_load_plus_values, key=extract_single_value)
        s_load_plus_df = pd.DataFrame(s_load_plus_values, columns=['Variable', 'Value'])
        s_load_minus_df = pd.DataFrame(s_load_minus_values, columns=['Variable', 'Value'])
    else:
        # Create empty DataFrame to return
        s_load_plus_df = s_load_minus_df = pd.DataFrame()

    if input_data["constraints"]["must_run_units_constraint"]:
        s_must_run_values = []
        for v in solution:
            if v.name.startswith('s_must_run'):
                s_must_run_values.append((v.name, v.varValue))
        s_must_run_values = sorted(s_must_run_values, key=extract_numbers)
        s_must_run_df = pd.DataFrame(s_must_run_values, columns=['Variable', 'Value'])
        s_must_run_df = extract_gen_hour(s_must_run_df)
        s_must_run_df = pivot_df(s_must_run_df)
    else:
        s_must_run_df = pd.DataFrame()
    # print(s_must_run_values)

    if input_data["constraints"]["primary_active_power_reserves_constraint"] or input_data["constraints"]["secondary_active_power_reserves_constraint"] or input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        N_1_values = []
        N_2_values = []
        s_N_1_values = []
        s_N_2_values = []

        for v in solution:
            if v.name.startswith('N_1_'):
                N_1_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('N_2_'):
                N_2_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('s_N_1_'):
                s_N_1_values.append((v.name, round(float(v.varValue), 8)))
            elif v.name.startswith('s_N_2_'):
                s_N_2_values.append((v.name, round(float(v.varValue), 8)))

        N_1_values = sorted(N_1_values, key=extract_numbers_2)
        N_2_values = sorted(N_2_values, key=extract_numbers_2)
        s_N_1_values = sorted(s_N_1_values, key=extract_numbers_2)
        s_N_2_values = sorted(s_N_2_values, key=extract_numbers_2)


        N_1_df = pd.DataFrame(N_1_values, columns=['Variable', 'Value'])
        N_2_df = pd.DataFrame(N_2_values, columns=['Variable', 'Value'])
        s_N_1_df = pd.DataFrame(s_N_1_values, columns=['Variable', 'Value'])
        s_N_2_df = pd.DataFrame(s_N_2_values, columns=['Variable', 'Value'])


    else:
        N_1_df = N_2_df = s_N_1_df = s_N_2_df = pd.DataFrame()


    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        primary_ActPR_plus_values = []
        primary_ActPR_minus_values = []
        primary_APRR_values = []
        s_primary_APR_upwards_values = []
        s_primary_APR_downwards_values = []
        binary_primary_values = []
        for v in solution:
            if v.name.startswith('primary_ActPR_plus'):
                primary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('primary_ActPR_minus'):
                primary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('primary_APRR'):
                primary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_primary_APR_upwards'):
                s_primary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_primary_APR_downwards'):
                s_primary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_primary'):
                binary_primary_values.append((v.name, round(float(v.varValue), 8)))
        s_primary_APR_upwards_values = sorted(s_primary_APR_upwards_values, key=extract_single_value)
        # print(s_primary_APR_upwards_values)
        s_primary_APR_downwards_values = sorted(s_primary_APR_downwards_values, key=extract_single_value)
        # print(s_primary_APR_downwards_values)
        s_primary_APR_upwards_df = pd.DataFrame(s_primary_APR_upwards_values, columns=['Variable', 'Value'])
        s_primary_APR_downwards_df = pd.DataFrame(s_primary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_primary_values = sorted(binary_primary_values, key=extract_numbers_4)

        primary_ActPR_minus_values = sorted(primary_ActPR_minus_values, key=extract_numbers_2)
        primary_ActPR_plus_values = sorted(primary_ActPR_plus_values, key=extract_numbers_2)
        primary_APRR_values = sorted(primary_APRR_values, key=extract_numbers)
        primary_ActPR_plus_df = pd.DataFrame(primary_ActPR_plus_values, columns=['Variable', 'Value'])
        primary_ActPR_minus_df = pd.DataFrame(primary_ActPR_minus_values, columns=['Variable', 'Value'])
        primary_APRR_df = pd.DataFrame(primary_APRR_values, columns=['Variable', 'Value'])
        binary_primary_df = pd.DataFrame(binary_primary_values, columns=['Variable', 'Value'])
        primary_ActPR_plus_df = extract_gen_hour(primary_ActPR_plus_df)
        primary_ActPR_minus_df = extract_gen_hour(primary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        primary_ActPR_plus_df = primary_ActPR_minus_df = primary_APRR_df = s_primary_APR_upwards_df = s_primary_APR_downwards_df = binary_primary_df = pd.DataFrame()
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:

        secondary_ActPR_plus_values = []
        secondary_ActPR_minus_values = []
        secondary_APRR_values = []
        s_secondary_APR_upwards_values = []
        s_secondary_APR_downwards_values = []
        binary_secondary_values = []

        for v in solution:
            if v.name.startswith('secondary_ActPR_plus'):
                secondary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('secondary_ActPR_minus'):
                secondary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('secondary_APRR'):
                secondary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_secondary_APR_upwards'):
                s_secondary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_secondary_APR_downwards'):
                s_secondary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_secondary'):
                binary_secondary_values.append((v.name, round(v.varValue, 8)))
        s_secondary_APR_upwards_values = sorted(s_secondary_APR_upwards_values, key=extract_single_value)
        s_secondary_APR_downwards_values = sorted(s_secondary_APR_downwards_values, key=extract_single_value)
        s_secondary_APR_upwards_df = pd.DataFrame(s_secondary_APR_upwards_values, columns=['Variable', 'Value'])
        s_secondary_APR_downwards_df = pd.DataFrame(s_secondary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_secondary_values = sorted(binary_secondary_values, key=extract_numbers_4)

        secondary_ActPR_minus_values = sorted(secondary_ActPR_minus_values, key=extract_numbers_2)
        secondary_ActPR_plus_values = sorted(secondary_ActPR_plus_values, key=extract_numbers_2)
        secondary_APRR_values = sorted(secondary_APRR_values, key=extract_numbers)
        secondary_ActPR_plus_df = pd.DataFrame(secondary_ActPR_plus_values, columns=['Variable', 'Value'])
        secondary_ActPR_minus_df = pd.DataFrame(secondary_ActPR_minus_values, columns=['Variable', 'Value'])
        secondary_APRR_df = pd.DataFrame(secondary_APRR_values, columns=['Variable', 'Value'])
        binary_secondary_df = pd.DataFrame(binary_secondary_values, columns=['Variable', 'Value'])
        secondary_ActPR_plus_df = extract_gen_hour(secondary_ActPR_plus_df)
        secondary_ActPR_minus_df = extract_gen_hour(secondary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        secondary_ActPR_plus_df = secondary_ActPR_minus_df = secondary_APRR_df = s_secondary_APR_upwards_df = s_secondary_APR_downwards_df = binary_secondary_df = pd.DataFrame()
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        tertiary_ActPR_plus_values = []
        tertiary_ActPR_minus_values = []
        tertiary_APRR_values = []
        s_tertiary_APR_upwards_values = []
        s_tertiary_APR_downwards_values = []
        binary_tertiary_values = []

        for v in solution:
            if v.name.startswith('tertiary_ActPR_plus'):
                tertiary_ActPR_plus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('tertiary_ActPR_minus'):
                tertiary_ActPR_minus_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('tertiary_APRR'):
                tertiary_APRR_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_tertiary_APR_upwards'):
                s_tertiary_APR_upwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('s_tertiary_APR_downwards'):
                s_tertiary_APR_downwards_values.append((v.name, round(v.varValue, 8)))
            elif v.name.startswith('binary_tertiary'):
                binary_tertiary_values.append((v.name, round(v.varValue, 8)))
        s_tertiary_APR_upwards_values = sorted(s_tertiary_APR_upwards_values, key=extract_single_value)
        s_tertiary_APR_downwards_values = sorted(s_tertiary_APR_downwards_values, key=extract_single_value)
        s_tertiary_APR_upwards_df = pd.DataFrame(s_tertiary_APR_upwards_values, columns=['Variable', 'Value'])
        s_tertiary_APR_downwards_df = pd.DataFrame(s_tertiary_APR_downwards_values, columns=['Variable', 'Value'])
        binary_tertiary_values = sorted(binary_tertiary_values, key=extract_numbers_4)

        tertiary_ActPR_minus_values = sorted(tertiary_ActPR_minus_values, key=extract_numbers_2)
        tertiary_ActPR_plus_values = sorted(tertiary_ActPR_plus_values, key=extract_numbers_2)
        tertiary_APRR_values = sorted(tertiary_APRR_values, key=extract_numbers)
        tertiary_ActPR_plus_df = pd.DataFrame(tertiary_ActPR_plus_values, columns=['Variable', 'Value'])
        tertiary_ActPR_minus_df = pd.DataFrame(tertiary_ActPR_minus_values, columns=['Variable', 'Value'])
        tertiary_APRR_df = pd.DataFrame(tertiary_APRR_values, columns=['Variable', 'Value'])
        binary_tertiary_df = pd.DataFrame(binary_tertiary_values, columns=['Variable', 'Value'])
        tertiary_ActPR_plus_df = extract_gen_hour(tertiary_ActPR_plus_df)
        tertiary_ActPR_minus_df = extract_gen_hour(tertiary_ActPR_minus_df)
    else:
        # Create empty DataFrame to return
        tertiary_ActPR_plus_df = tertiary_ActPR_minus_df = tertiary_APRR_df = s_tertiary_APR_upwards_df = s_tertiary_APR_downwards_df = binary_tertiary_df = pd.DataFrame()
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        setpoint_values = []
        Min_grid_capacity_1_values = []
        Min_grid_capacity_2_values = []
        Min_Power_Calc_values = []
        Grid_Capacity1_values = []
        Grid_Capacity2_values = []
        Grid_Capacity3_values = []
        g1_values = []
        g2_values = []
        g3_values = []
        g4_values = []
        g5_values = []

        m_values = []

        s_Grid_Capacity_1_values = []
        s_Grid_Capacity_2_values = []
        s_Grid_Capacity_3_values = []

        P_RES_values = []
        P_PV_values = []
        P_sp_values = []
        for v in solution:
            if v.name.startswith('setpoint'):
                setpoint_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_grid_capacity_1'):
                Min_grid_capacity_1_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_grid_capacity_2'):
                Min_grid_capacity_2_values.append((v.name, v.varValue))
            elif v.name.startswith('Min_Power_Calc'):
                Min_Power_Calc_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity1'):
                Grid_Capacity1_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity2'):
                Grid_Capacity2_values.append((v.name, v.varValue))
            elif v.name.startswith('Grid_Capacity3'):
                Grid_Capacity3_values.append((v.name, v.varValue))
            elif v.name.startswith('m'):
                m_values.append((v.name, v.varValue))
            elif v.name.startswith('g1'):
                g1_values.append((v.name, v.varValue))
            elif v.name.startswith('g2'):
                g2_values.append((v.name, v.varValue))
            elif v.name.startswith('g3'):
                g3_values.append((v.name, v.varValue))
            elif v.name.startswith('g4'):
                g4_values.append((v.name, v.varValue))
            elif v.name.startswith('g5'):
                g5_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_1'):
                s_Grid_Capacity_1_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_2'):
                s_Grid_Capacity_2_values.append((v.name, v.varValue))
            elif v.name.startswith('s_Grid_Capacity_3'):
                s_Grid_Capacity_3_values.append((v.name, v.varValue))

            elif v.name.startswith('P_RES_'):
                P_RES_values.append((v.name, v.varValue))
            elif v.name.startswith('P_PV_'):
                P_PV_values.append((v.name, v.varValue))
            elif v.name.startswith('P_sp_'):
                P_sp_values.append((v.name, v.varValue))



        setpoint_values = sorted(setpoint_values, key=extract_numbers)
        Min_grid_capacity_1_values = sorted(Min_grid_capacity_1_values, key=extract_single_value)
        Min_grid_capacity_2_values = sorted(Min_grid_capacity_2_values, key=extract_single_value)
        Min_Power_Calc_values = sorted(Min_Power_Calc_values, key=extract_numbers)

        Grid_Capacity1_values = sorted(Grid_Capacity1_values, key=extract_single_value)
        Grid_Capacity2_values = sorted(Grid_Capacity2_values, key=extract_single_value)
        Grid_Capacity3_values = sorted(Grid_Capacity3_values, key=extract_single_value)
        g1_values = sorted(g1_values, key=extract_single_value)
        g2_values = sorted(g2_values, key=extract_single_value)
        g3_values = sorted(g3_values, key=extract_numbers)
        g4_values = sorted(g4_values, key=extract_numbers)
        g5_values = sorted(g5_values, key=extract_single_value)

        m_values = sorted(m_values, key=extract_numbers)

        s_Grid_Capacity_1_values = sorted(s_Grid_Capacity_1_values, key=extract_single_value)
        s_Grid_Capacity_2_values = sorted(s_Grid_Capacity_2_values, key=extract_single_value)
        s_Grid_Capacity_3_values = sorted(s_Grid_Capacity_3_values, key=extract_single_value)

        P_RES_values = sorted(P_RES_values, key=extract_single_value)
        P_PV_values = sorted(P_PV_values, key=extract_single_value)
        P_sp_values = sorted(P_sp_values, key=extract_single_value)


        setpoint_df = pd.DataFrame(setpoint_values, columns=['Variable', 'Value'])
        Min_Power_Calc_df = pd.DataFrame(Min_Power_Calc_values, columns=['Variable', 'Value'])
        g3_df = pd.DataFrame(g3_values, columns=['Variable', 'Value'])
        g4_df = pd.DataFrame(g4_values, columns=['Variable', 'Value'])
        g5_df = pd.DataFrame(g5_values, columns=['Variable', 'Value'])

        s_Grid_Capacity_1_df = pd.DataFrame(s_Grid_Capacity_1_values, columns=['Variable', 'Value'])
        s_Grid_Capacity_2_df = pd.DataFrame(s_Grid_Capacity_2_values, columns=['Variable', 'Value'])
        s_Grid_Capacity_3_df = pd.DataFrame(s_Grid_Capacity_3_values, columns=['Variable', 'Value'])

        P_RES_df = pd.DataFrame(P_RES_values, columns=['Variable', 'Value'])
        P_PV_df = pd.DataFrame(P_PV_values, columns=['Variable', 'Value'])
        P_sp_df = pd.DataFrame(P_sp_values, columns=['Variable', 'Value'])

        Min_grid_capacity_1_df = pd.DataFrame(Min_grid_capacity_1_values, columns=['Variable', 'Value'])
        Min_grid_capacity_2_df = pd.DataFrame(Min_grid_capacity_2_values, columns=['Variable', 'Value'])
        Grid_Capacity1_df = pd.DataFrame(Grid_Capacity1_values, columns=['Variable', 'Value'])
        Grid_Capacity2_df = pd.DataFrame(Grid_Capacity2_values, columns=['Variable', 'Value'])
        Grid_Capacity3_df = pd.DataFrame(Grid_Capacity3_values, columns=['Variable', 'Value'])
        g1_df = pd.DataFrame(g1_values, columns=['Variable', 'Value'])
        g2_df = pd.DataFrame(g2_values, columns=['Variable', 'Value'])
        m_df = pd.DataFrame(m_values, columns=['Variable', 'Value'])
        setpoint_df = extract_gen_hour(setpoint_df)
        setpoint_df = pivot_df(setpoint_df)
        Min_Power_Calc_df = extract_gen_hour(Min_Power_Calc_df )
        Min_Power_Calc_df = pivot_df(Min_Power_Calc_df)
        # g3_df = pd.DataFrame(g3_values, columns=['Variable', 'Value'])
        # g3_df = extract_gen_hour(g3_df)
        # g3_df = pivot_df(g3_df)
    else:
        Min_grid_capacity_1_df = Min_grid_capacity_2_df = Min_Power_Calc_df = Grid_Capacity1_df = Grid_Capacity2_df = Grid_Capacity3_df = g1_df = g2_df = g3_df = g4_df = g5_df = m_df = setpoint_df = s_Grid_Capacity_1_df = s_Grid_Capacity_2_df = s_Grid_Capacity_3_df = P_RES_df = P_PV_df = P_sp_df = pd.DataFrame()
    # total_actual_cost_values = []
    #
    # actual_cost_2_values = []


    if input_data["constraints"]["forbidden_zones_constraint"]:
        y_zone_values = []
        s_forbidden_zones_plus_values = []
        s_forbidden_zones_minus_values = []
        for v in solution:
            if v.name.startswith('y_zone'):
                y_zone_values.append((v.name, v.varValue))
            elif v.name.startswith('s_forbidden_zones_plus'):
                s_forbidden_zones_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_forbidden_zones_minus'):
                s_forbidden_zones_minus_values.append((v.name, v.varValue))

        y_zone_values = sorted(y_zone_values, key=extract_numbers_4)
        y_zone_df = pd.DataFrame(y_zone_values, columns=['Variable', 'Value'])
        s_forbidden_zones_plus_values = sorted(s_forbidden_zones_plus_values, key=extract_numbers)
        s_forbidden_zones_plus_df = pd.DataFrame(s_forbidden_zones_plus_values, columns=['Variable', 'Value'])
        s_forbidden_zones_minus_values = sorted(s_forbidden_zones_minus_values, key=extract_numbers)
        s_forbidden_zones_minus_df = pd.DataFrame(s_forbidden_zones_minus_values, columns=['Variable', 'Value'])
    else:
        y_zone_df = pd.DataFrame()
        s_forbidden_zones_plus_df = pd.DataFrame()
        s_forbidden_zones_minus_df = pd.DataFrame()

    if input_data["constraints"]["testing_mode_constraints"]:
        s_power_testing_mode_plus_values = []
        s_power_testing_mode_minus_values = []
        for v in solution:
            if v.name.startswith('s_power_testing_plus_'):
                s_power_testing_mode_plus_values.append((v.name, v.varValue))
            elif v.name.startswith('s_power_testing_minus_'):
                s_power_testing_mode_minus_values.append((v.name, v.varValue))
        s_power_testing_mode_plus_values = sorted(s_power_testing_mode_plus_values, key=extract_numbers)
        s_power_testing_mode_minus_values = sorted(s_power_testing_mode_minus_values, key=extract_numbers)

        s_power_testing_mode_plus_df = pd.DataFrame(s_power_testing_mode_plus_values, columns=['Variable', 'Value'])
        s_power_testing_mode_minus_df = pd.DataFrame(s_power_testing_mode_minus_values, columns=['Variable', 'Value'])

        s_power_testing_mode_plus_df = extract_gen_hour(s_power_testing_mode_plus_df)
        s_power_testing_mode_plus_df = pivot_df(s_power_testing_mode_plus_df)

        s_power_testing_mode_minus_df = extract_gen_hour(s_power_testing_mode_minus_df)
        s_power_testing_mode_minus_df = pivot_df(s_power_testing_mode_minus_df)
    else:
        s_power_testing_mode_plus_df = s_power_testing_mode_minus_df = pd.DataFrame()

    # Extract decision variable values from solution
    for v in solution:
        if v.name.startswith('power'):
            power_values.append((v.name, v.varValue))
        elif v.name.startswith('startup'):
            startup_values.append((v.name, v.varValue))
        elif v.name.startswith('shutdown'):
            shutdown_values.append((v.name, v.varValue))
        elif v.name.startswith('state'):
            state_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_ru'):
        #     s_ru_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_rd'):
        #     s_rd_values.append((v.name, v.varValue))
        elif v.name.startswith('z_1'):
            z_1_values.append((v.name, v.varValue))
        elif v.name.startswith('u_1'):
            u_1_values.append((v.name, v.varValue))
        elif v.name.startswith('u_2'):
            u_2_values.append((v.name, v.varValue))
        elif v.name.startswith('delta_'):
            delta_values.append((v.name, v.varValue))
        elif v.name.startswith('unit_cost_'):
            unit_cost_values.append((v.name, v.varValue))
        # elif v.name.startswith('z_3'):
        #     z_3_values.append((v.name, v.varValue))
        # elif v.name.startswith('s_APR_up'):
        #     s_APR_upwards_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('s_APR_down'):
        #     s_APR_downwards_values.append((v.name, v.varValue))

        # elif v.name.startswith('y_res_1'):
        #     y_res_1_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('y_res_2'):
        #     y_res_2_values.append((v.name, v.varValue))

        # elif v.name.startswith('Count'):
        #     Count_values.append((v.name, v.varValue))
        elif v.name.startswith('RES_sum'):
            RES_sum_values.append((v.name, v.varValue))
        elif v.name.startswith('s_power_plus'):
            s_power_plus_values.append((v.name, v.varValue))
        elif v.name.startswith('s_power_minus'):
            s_power_minus_values.append((v.name, v.varValue))

        # elif v.name.startswith('s_res'):
        #     s_res_values.append((v.name, v.varValue))
        # elif v.name.startswith('k'):
        #     k_value.append((v.name, v.varValue))
        # elif v.name.startswith('y_res_3'):
        #     y_res_3_values.append((v.name, v.varValue))
        # elif v.name.startswith('Percentage_of_Usage'):
        #     Percentage_of_Usage_values.append((v.name, v.varValue))
        # elif v.name.startswith('mult'):
        #     mult_values.append((v.name, v.varValue))
        # elif v.name.startswith('Grid'):
        #     Grid_Capacity_values.append((v.name, v.varValue))
        #         elif v.name.startswith('y_up'):
        #             y_up_values.append((v.name, v.varValue))
        #         elif v.name.startswith('y_down'):
        #             y_down_values.append((v.name, v.varValue))

        #         elif v.name.startswith('on_prev'):
        #             on_prev_values.append((v.name, v.varValue))

        # elif v.name.startswith('remaining_run'):
        #     remaining_run_values.append((v.name, v.varValue))
        # elif v.name.startswith('total_actual_cost'):
        #     total_actual_cost_values.append((v.name, v.varValue))
        #
        # elif v.name.startswith('actual_cost_2'):
        #     actual_cost_2_values.append((v.name, v.varValue))
    power_values = sorted(power_values, key=extract_numbers)
    startup_values = sorted(startup_values, key=extract_numbers)
    shutdown_values = sorted(shutdown_values, key=extract_numbers)
    state_values = sorted(state_values, key=extract_numbers)

    s_power_plus_values = sorted(s_power_plus_values, key=extract_numbers)
    s_power_minus_values = sorted(s_power_minus_values, key=extract_numbers)

    # total_actual_cost_values = sorted(total_actual_cost_values, key=extract_single_value)
    # actual_cost_2_values = sorted(actual_cost_2_values, key=extract_single_value)
    # y_res_1_values = sorted(y_res_1_values, key=extract_numbers_2)
    # y_res_1_values = sorted(y_res_1_values, key=extract_numbers_2)
    # s_ru_values = sorted(s_ru_values, key=extract_numbers)
    #
    # s_rd_values = sorted(s_rd_values, key=extract_numbers)
    # s_APR_upwards_values = sorted(s_APR_upwards_values, key=extract_single_value)
    #
    # s_APR_downwards_values = sorted(s_APR_downwards_values, key=extract_single_value)
    RES_sum_values = sorted(RES_sum_values, key=extract_single_value)
    # s_res_values = sorted(s_res_values, key=extract_numbers)
    z_1_values = sorted(z_1_values, key=extract_numbers_3)
    # z_3_values = sorted(z_3_values, key=extract_numbers_3)
    u_1_values = sorted(u_1_values, key=extract_numbers_3)
    delta_values = sorted(delta_values, key=extract_numbers_4)
    unit_cost_values = sorted(unit_cost_values, key=extract_numbers)
    u_2_values = sorted(u_2_values, key=extract_numbers_3)
    # Convert lists into DataFrames
    power_df = pd.DataFrame(power_values, columns=['Variable', 'Value'])
    startup_df = pd.DataFrame(startup_values, columns=['Variable', 'Value'])
    state_df = pd.DataFrame(state_values, columns=['Variable', 'Value'])

    s_power_plus_df = pd.DataFrame(s_power_plus_values, columns=['Variable', 'Value'])
    s_power_minus_df = pd.DataFrame(s_power_minus_values, columns=['Variable', 'Value'])

    #     y_up_df = pd.DataFrame(y_up_values, columns=['Variable', 'Value'])
    #     y_down_df = pd.DataFrame(y_down_values, columns=['Variable', 'Value'])
    # total_actual_cost_values_df = pd.DataFrame(total_actual_cost_values, columns=['Variable', 'Value'])
    # actual_cost_2_values_df = pd.DataFrame(actual_cost_2_values, columns=['Variable', 'Value'])
    # setpoint_df, Min_grid_capacity_df, Grid_Capacity1_df, Grid_Capacity2_df, g_df, m_df
    # s_ru_df = pd.DataFrame(s_ru_values, columns=['Variable', 'Value'])
    # s_rd_df = pd.DataFrame(s_rd_values, columns=['Variable', 'Value'])
    z_1_df = pd.DataFrame(z_1_values, columns=['Variable', 'Value'])
    u_1_df = pd.DataFrame(u_1_values, columns=['Variable', 'Value'])
    delta_df = pd.DataFrame(delta_values, columns=['Variable', 'Value'])
   # unit_cost_df = pd.DataFrame(unit_cost_values, columns=['Variable', 'Value'])
    # y_res_1_df = pd.DataFrame(y_res_1_values, columns=['Variable', 'Value'])
    #
    # y_res_2_df = pd.DataFrame(y_res_2_values, columns=['Variable', 'Value'])

    # Count_df = pd.DataFrame(Count_values, columns=['Variable', 'Value'])
    RES_sum_df = pd.DataFrame(RES_sum_values, columns=['Variable', 'Value'])
    # s_res_df = pd.DataFrame(s_res_values, columns=['Variable', 'Value'])
    # s_APR_upwards_df = pd.DataFrame(s_APR_upwards_values, columns=['Variable', 'Value'])
    # s_APR_downwards_df = pd.DataFrame(s_APR_downwards_values, columns=['Variable', 'Value'])
    # y_res_3_df = pd.DataFrame(y_res_3_values, columns=['Variable', 'Value'])
    # Percentage_of_Usage_df = pd.DataFrame(Percentage_of_Usage_values, columns=['Variable', 'Value'])
    # Grid_Capacity_df = pd.DataFrame(Grid_Capacity_values, columns=['Variable', 'Value'])
    shutdown_df = pd.DataFrame(shutdown_values, columns=['Variable', 'Value'])
    #     on_prev_df = pd.DataFrame(on_prev_values, columns=['Variable', 'Value'])
    #     remaining_run_df = pd.DataFrame(remaining_run_values, columns=['Variable', 'Value'])
    # mult_df = pd.DataFrame(mult_values, columns=['Variable', 'Value'])
    # z_3_df = pd.DataFrame(z_3_values, columns=['Variable', 'Value'])
    u_2_df = pd.DataFrame(u_2_values, columns=['Variable', 'Value'])
    # # Merge all DataFrames into one
    # solution_df = pd.concat([power_df, startup_df, state_df, y_up_df, y_down_df]).reset_index(drop=True)

    # # print(solution_df)
    power_df = extract_gen_hour(power_df)
   # unit_cost_df = extract_gen_hour(unit_cost_df)
    startup_df = extract_gen_hour(startup_df)
    shutdown_df = extract_gen_hour(shutdown_df)
    state_df = extract_gen_hour(state_df)

    s_power_plus_df = extract_gen_hour(s_power_plus_df)
    s_power_minus_df = extract_gen_hour(s_power_minus_df)

    # mult_df = extract_gen_hour(mult_df)
    #     y_up_df = extract_gen_hour(y_up_df)
    #     y_down_df = extract_gen_hour(y_down_df)
    # s_ru_df = extract_gen_hour(s_ru_df)
    # s_rd_df = extract_gen_hour(s_rd_df)
    #     s_load_plus_df  = extract_gen_hour(s_load_plus_df)
    #     s_load_minus_df  = extract_gen_hour(s_load_minus_df)
    #     z_df = extract_gen_hour(z_df)
    #     u_df = extract_gen_hour(u_df)
    #     on_prev_df = extract_gen_hour(on_prev_df)
    #     remaining_run_df = extract_gen_hour(remaining_run_df)

    # Pivot DataFrames to get one column per hour and one row per generator
    power_df = pivot_df(power_df)
    startup_df = pivot_df(startup_df)
    shutdown_df = pivot_df(shutdown_df)
    state_df = pivot_df(state_df)
    #unit_cost_df = pivot_df(unit_cost_df)

    s_power_plus_df = pivot_df(s_power_plus_df)
    s_power_minus_df = pivot_df(s_power_minus_df)

    if input_data["constraints"]["ramp_up_down_constraints"]:
        ramp_relax_values = []
        for v in solution:
            if v.name.startswith('ramp_relax'):
                ramp_relax_values.append((v.name, v.varValue))
                ramp_relax_values = sorted(ramp_relax_values, key=extract_numbers)
                ramp_relax_df = pd.DataFrame(ramp_relax_values, columns=['Variable', 'Value'])
                ramp_relax_df = extract_gen_hour(ramp_relax_df)
                ramp_relax_df = pivot_df(ramp_relax_df)
    else:
        ramp_relax_df = pd.DataFrame()



    # mult_df = pivot_df(mult_df)
    #     y_up_df = pivot_df(y_up_df)
    #     y_down_df = pivot_df(y_down_df)

    # s_ru_df = pivot_df(s_ru_df)
    # s_rd_df = pivot_df(s_rd_df)

    #     ActPR_plus_df  = pivot_df(ActPR_plus_df)

    #     s_load_plus_df  = pivot_df(s_load_plus_df )
    #     s_load_minus_df  = pivot_df(s_load_minus_df)

    #     z_df = pivot_df(z_df)
    #     u_df = pivot_df(u_df)

    #     on_prev_df = pivot_df(on_prev_df)
    #     remaining_run_df = pivot_df(remaining_run_df)

    # print(power_df)
    # print(startup_df)
    # print(state_df)

    # Create an empty DataFrame with the same columns as your existing ones
    # final_df = pd.DataFrame(columns=power_df.columns)
    #
    # # Loop through all the generator IDs and append Power, State, and Startup for each generator
    # for gen_id in power_df.index:
    #     if gen_id != 'Total_dispatched' and gen_id != 'Load Forecast':
    #         final_df.loc[f'Gen_{gen_id} Power'] = power_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} State'] = state_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} Startup'] = startup_df.loc[gen_id]
    #         #             final_df.loc[f'Gen_{gen_id} y_up'] = y_up_df.loc[gen_id]
    #         #             final_df.loc[f'Gen_{gen_id} y_down'] = y_down_df.loc[gen_id]
    #
    #         final_df.loc[f'Gen_{gen_id} s_ru'] = s_ru_df.loc[gen_id]
    #         final_df.loc[f'Gen_{gen_id} s_rd'] = s_rd_df.loc[gen_id]

    #             final_df.loc[f'Gen_{gen_id} on_prev'] = on_prev_df.loc[gen_id]
    #             final_df.loc[f'Gen_{gen_id} remaining_run'] = remaining_run_df.loc[gen_id]

    # Add rows for total state (number of units ON), total startup units and total power
    # total_state = state_df.apply(lambda x: (x == 1.0).sum()).rename('# Units ON')
    # total_startup = startup_df.sum().rename('# Startup Units')
    # total_power = power_df.sum()

    # final_df = pd.concat([final_df, total_state, total_startup, total_power], axis=0)
    # final_df = final_df.append(state_df.apply(lambda x: (x == 1.0).sum()).rename('# Units ON'))
    # final_df = final_df.append(startup_df.sum().rename('# Startup Units'))
    # final_df.loc['Total Power Dispatched'] = power_df.sum()
    #
    # # Add load forecast to the DataFrame
    # final_df.loc['Load Forecast'] = Load_forecast
    end_time_2 = time.time()
    execution_time_2 = end_time_2 - start_time_2
    print("solution_processing function execution time:", round(execution_time_2, 3), "seconds")
    print('')
    return (
        power_df, state_df, startup_df, shutdown_df,  ramp_relax_df, s_load_plus_df, s_load_minus_df,
        z_1_df, u_1_df, primary_ActPR_plus_df, primary_ActPR_minus_df, s_primary_APR_upwards_df, s_primary_APR_downwards_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, s_tertiary_APR_upwards_df,
        s_tertiary_APR_downwards_df, secondary_ActPR_plus_df, secondary_ActPR_minus_df, s_secondary_APR_upwards_df, s_secondary_APR_downwards_df, RES_sum_df,
        primary_APRR_df, binary_primary_df, tertiary_APRR_df, binary_tertiary_df, secondary_APRR_df, binary_secondary_df, u_2_df, setpoint_df, Min_grid_capacity_1_df, Min_grid_capacity_2_df, Min_Power_Calc_df, Grid_Capacity1_df, Grid_Capacity2_df, Grid_Capacity3_df, g1_df, g2_df, g3_df, g4_df,
        m_df, y_zone_df, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df, s_must_run_df, s_min_a_left_df, s_min_a_1_df, s_min_b_left_df, s_min_b_1_df, s_max_b_left_df, s_max_b_1_df,
        s_min_state_b_left_df, s_min_state_b_1_df, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df,
        s_power_plus_df, s_power_minus_df, N_1_df, N_2_df, P_RES_df, P_PV_df, s_avail_values_df, s_N_1_df, s_N_2_df, P_sp_df, g5_df, delta_df, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df
    )  # y_up_df, y_down_df,

def setpoint_calculation(input_data, RES, RES_forecast, Sum_RES_forecast, data, power_df, setpoint_df, state_df):
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:

        num_rows = len(RES_forecast)
        column_lengths = len(RES_forecast[0])

        # Convert the array to a DataFrame and transpose
        RES_forecast_df = pd.DataFrame(RES_forecast).transpose()

        # Set the column labels starting from 1
        RES_forecast_df.columns = [f' {i + 1}' for i in range(RES_forecast_df.shape[1])]

        # Adjust index to start from 1
        RES_forecast_df.index = RES_forecast_df.index + 1

        # Creating a MultiIndex with "Hour" as the top-level label
        hours = [str(i) for i in RES_forecast_df.index]
        RES_forecast_df.index = hours
        RES_forecast_df.columns = pd.MultiIndex.from_product([['Hour'], RES_forecast_df.columns])
        RES_forecast_df.index = pd.MultiIndex.from_product([['Generator'], RES_forecast_df.index])
        # Creating a MultiIndex with "Hour" as the top-level label for columns

        #     RES_forecast_df

        Setpoints = np.zeros((num_rows, column_lengths))
        Setpoints_df = pd.DataFrame(Setpoints).transpose()

        # Set the column labels starting from 1
        Setpoints_df.columns = [f' {i + 1}' for i in range(Setpoints_df.shape[1])]

        # Adjust index to start from 1
        Setpoints_df.index = Setpoints_df.index + 1

        # Creating a MultiIndex with "Hour" as the top-level label
        Setpoints_df.columns = pd.MultiIndex.from_product([['Hour'], Setpoints_df.columns])
        Setpoints_df.index = pd.MultiIndex.from_product([['Generator'], Setpoints_df.index])

        #     Setpoints_df

        # for i in range(len(Setpoints_df)):
        #     for j in Setpoints_df.columns:
        #         print(Setpoints_df.loc[i][j])

        for row_labels in RES:
            for col in range(len(RES_forecast)):
                # if y_res_1_df.iloc[col][1] == 1:
                #     Setpoints_df.iloc[row_labels, col] = Grid_Capacity_df.iloc[col][1] * (
                #             RES_forecast_df.iloc[row_labels][col] / Sum_RES_forecast[col + 1]) * (
                #                                                  1 / data[row_labels]['max_power(MW)'])
                # else:

                if setpoint_df.iloc[row_labels, col] > 1:
                    Setpoints_df.iloc[row_labels, col] = round(setpoint_df.iloc[row_labels, col], 3)
                else:
                    Setpoints_df.iloc[row_labels, col] = round(setpoint_df.iloc[row_labels, col], 3)
                # if state_df.iloc[row_labels, col] == 0:
                #     Setpoints_df.iloc[row_labels, col - 1] = 0.0
                # else:
                #     pass

                #  (UN-)COMMENT THE NEXT CONDITIONAL STATEMENT (4 LINES) BELLOW FOR DIFFERENT CALCULATION OF SETPOINTS

                # if power_df.iloc[row_labels, col]/data[row_labels]['max_power(MW)'] < Setpoints_df.iloc[row_labels, col-1]:
                #     Setpoints_df.iloc[row_labels, col-1] = power_df.iloc[row_labels, col]/data[row_labels]['max_power(MW)']
                # else:
                #     pass

                # print('indexes: ', row_labels, ', ', col)
                # print('power: ', power_df.iloc[row_labels, col])
                # print('Max power: ', round(data[row_labels]['max_power(MW)'], 2))
                # print('Setpoints: ', round(Setpoints_df.iloc[row_labels, col-1], 2))
                # print('')
    else:
        Setpoints_df = setpoint_df




        #         print(y_res_1_df.iloc[row_labels][1])
        #         Setpoints_df.iloc[row_labels, col]=0
        #         print(Setpoints_df.iloc[row_labels, col])
    # print(Setpoints_df)
    # print(setpoint_df)
    #
    # print(power_df)
    # print(state_df)

    return round(Setpoints_df, 3)

def units_matrices(u_2_df, data):
    # import pandas as pd

    # Extract unit, row, and column indices
    u_2_df[['unit', 'row', 'col']] = u_2_df['Variable'].str.extract(r'u_2_(\d+)_(\d+)_(\d+)')

    # Convert extracted strings to integers
    u_2_df['unit'] = u_2_df['unit'].astype(int)
    u_2_df['row'] = u_2_df['row'].astype(int)
    u_2_df['col'] = u_2_df['col'].astype(int)

    # Dictionary to store matrices
    unit_matrices = {}

    # Iterate over each unit and create matrix
    for unit in range(1, len(data) + 1):
        subset = u_2_df[u_2_df['unit'] == unit]
        matrix = subset.pivot(index='row', columns='col', values='Value')
        unit_matrices[unit] = matrix

    return unit_matrices

def matrices_to_dfs(unit_matrices):
    dfs = {}
    for key, matrix in unit_matrices.items():
        # Convert matrix to DataFrame
        df = pd.DataFrame(matrix)

        # Create multi-index for columns
        columns = pd.MultiIndex.from_product([['Thermal_states'], df.columns])
        df.columns = columns

        # Create multi-index for rows
        rows = pd.MultiIndex.from_product([['hours'], range(df.shape[0])])
        df.index = rows
        dfs[key] = df

    return dfs

def load_curtailment(input_data, s_load_plus_df, s_load_minus_df):
    LC = []
    LA = []
    if input_data["constraints"]["load_production_balance_constraint"] or input_data["constraints"]["load_production_Energy_balance_constraint"]:
        for i in range(0, len(s_load_minus_df)):
            LC.append(abs(round(s_load_minus_df['Value'][i], 3)))
            LA.append(abs(round(s_load_plus_df['Value'][i], 3)))  # Load Augmentation
        if any(LC):
            print('Load Curtailment is required !!!')
        else:
            print('----- No Load Cutrailment is required -----')
        if any(LA):
            print('Load Augmentation is required !!!')
        else:
            print('----- No Load Augmentation is required -----')
    else:
        LC = 'Nan'
    return LC


def APRR_violation(input_data, s_primary_APR_upwards_df, s_primary_APR_downwards_df, s_secondary_APR_upwards_df, s_secondary_APR_downwards_df, s_tertiary_APR_upwards_df, s_tertiary_APR_downwards_df):
    primary_upwards_APRV = []
    primary_downwards_APRV = []
    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        for i in range(0, len(s_primary_APR_upwards_df)):
            primary_upwards_APRV.append(abs(round(s_primary_APR_upwards_df['Value'][i], 5)))
            primary_downwards_APRV.append(abs(round(s_primary_APR_downwards_df['Value'][i], 5)))
        if any(primary_upwards_APRV):
            print('----- WARNING: upwards primary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No upwards primary APRR constraint violated-----')
        if any(primary_downwards_APRV):
            print('----- WARNING: downwards primary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No downwards primary APRR constraint violated-----')
    else:
        primary_upwards_APRV = 'Nan'
        primary_downwards_APRV = 'Nan'

    secondary_upwards_APRV = []
    secondary_downwards_APRV = []
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        for i in range(0, len(s_secondary_APR_upwards_df)):
            # print('len(df)', len(s_secondary_APR_upwards_df))
            secondary_upwards_APRV.append(abs(round(s_secondary_APR_upwards_df['Value'][i], 5)))
            secondary_downwards_APRV.append(abs(round(s_secondary_APR_downwards_df['Value'][i], 5)))
        if any(secondary_upwards_APRV):
            print('----- WARNING: upwards secondary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No upwards secondary APRR constraint violated-----')
        if any(secondary_downwards_APRV):
            print('----- WARNING: downwards secondary APRR constraint violated!!! -----')
        else:
            pass  #print('----- No downwards secondary APRR constraint violated-----')
    else:
        secondary_upwards_APRV = 'Nan'
        secondary_downwards_APRV = 'Nan'

    tertiary_upwards_APRV = []
    tertiary_downwards_APRV = []
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        for i in range(0, len(s_tertiary_APR_upwards_df)):
            tertiary_upwards_APRV.append(abs(round(s_tertiary_APR_upwards_df['Value'][i], 5)))
            tertiary_downwards_APRV.append(abs(round(s_tertiary_APR_downwards_df['Value'][i], 5)))
        if any(tertiary_upwards_APRV):
            print('----- WARNING: upwards tertiary APRR constraint violated!!! -----')
        else:
            pass  # print('----- No upwards tertiary APRR constraint violated-----')
        if any(tertiary_downwards_APRV):
            print('----- WARNING: downwards tertiary APRR constraint violated!!! -----')
        else:
            pass  # print('----- No downwards tertiary APRR constraint violated-----')
    else:
        tertiary_upwards_APRV = 'Nan'
        tertiary_downwards_APRV = 'Nan'

    return primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV, tertiary_upwards_APRV, tertiary_downwards_APRV

def forbidden_zones_violations(input_data, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df):
    # List to store (i-1, t) pairs
    fz_violated_constraints = []
    if input_data["constraints"]["forbidden_zones_constraint"]:
        # Iterate over each row of the dataframe
        for index, row in s_forbidden_zones_plus_df.iterrows():
            variable = row['Variable']
            value = row['Value']

            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_forbidden_zones_plus_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    fz_violated_constraints.append((int(i) - 1, int(t)))
                    # Print the warning message
                    # Iterate over each row of the dataframe
        for index, row in s_forbidden_zones_minus_df.iterrows():
            variable = row['Variable']
            value = row['Value']

            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_forbidden_zones_minus_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    fz_violated_constraints.append((int(i) - 1, int(t)))
                    # Print the warning message

        # Remove duplicates by converting the list to a set and back to a list
        fz_violated_constraints = list(set(fz_violated_constraints))

        # Sort the list first by unit (i) and then by dispatch period (t)
        fz_violated_constraints.sort(key=lambda x: (x[0], x[1]))

        # Print the warning message for each pair in the sorted list
        for i, t in fz_violated_constraints:
            print(f"----- WARNING: forbidden zones constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def ramp_up_down_violations(input_data, ramp_relax_df):
    # List to store (i-1, t) pairs
    ramp_up_down_violated_constraints = []
    if input_data["constraints"]["ramp_up_down_constraints"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(ramp_relax_df > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(f"----- WARNING: ramp up/ramp down constraint violated at unit {row}, dispatch period {ramp_relax_df.columns[col]} ----- ")
            print("")
    return None

def mustRun_violations(input_data, s_must_run_df):
    if input_data["constraints"]["must_run_units_constraint"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_must_run_df > 0)
        # Printing row and column information for each non-zero value
        for row, col in zip(*non_zero_positions):
            print(f"----- WARNING: must run constraint violated at unit {row}, dispatch period {s_must_run_df.columns[col]} ----- ")
        print("")
    return None

def min_transition_time_between_states_constraints_a_violations(input_data, s_min_a_left_df, s_min_a_1_df):
    min_a_left_violated_constraints = []
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_a"]:
        # Iterate over each row of the dataframe
        for index, row in s_min_a_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_a_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_a_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_a_left_violated_constraints = list(set(min_a_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_a_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_a_left_violated_constraints:
            print(
                f"----- WARNING: min-time-a-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
        min_a_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_a_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_a_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_a_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_a_1_violated_constraints = list(set(min_a_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_a_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_a_1_violated_constraints:
            print(
                f"----- WARNING: min-time-a-1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def min_transition_time_between_states_constraints_b_violations(input_data, s_min_b_left_df, s_min_b_1_df):
    min_b_left_violated_constraints = []
    if input_data["constraints"]["operating_states_min_transition_time_between_states_constraint_b"]:
        # Iterate over each row of the dataframe
        for index, row in s_min_b_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_b_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_b_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_b_left_violated_constraints = list(set(min_b_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_b_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_b_left_violated_constraints:
            print(
                f"----- WARNING: min-time-b-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
        min_b_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_b_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_b_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_b_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_b_1_violated_constraints = list(set(min_b_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_b_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_b_1_violated_constraints:
            print(
                f"----- WARNING: min-time-b-1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')
    return None

def max_transition_time_between_states_constraints_b_violations(input_data, s_max_b_left_df, s_max_b_1_df):
    if input_data["constraints"]["operating_states_max_transition_time_between_states_constraint_b"]:
        max_b_left_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_max_b_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_max_b_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    max_b_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        max_b_left_violated_constraints = list(set(max_b_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        max_b_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in max_b_left_violated_constraints:
            print(
                f"----- WARNING: max-time-b-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')



        max_b_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_max_b_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_max_b_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    max_b_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        max_b_1_violated_constraints = list(set(max_b_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        max_b_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in max_b_1_violated_constraints:
            print(
                f"----- WARNING: max-time-b-1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')


    return None

def min_state_transition_constraints_b_violations(input_data, s_min_state_b_left_df,  s_min_state_b_1_df):
    if input_data["constraints"]["states_time_constraint"]:
        min_state_b_left_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_state_b_left_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_state_b_left_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_state_b_left_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_state_b_left_violated_constraints = list(set(min_state_b_left_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_state_b_left_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_state_b_left_violated_constraints:
            print(
                f"----- WARNING: min-state-b-left constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')

        min_state_b_1_violated_constraints = []
        # Iterate over each row of the dataframe
        for index, row in s_min_state_b_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if value != 0:
                # Extract i and t using regex
                match = re.search(r's_min_state_b_1_(\d+)_(\d+)', variable)
                if match:
                    i = match.group(1)  # Extract the first number as i
                    t = match.group(2)  # Extract the second number as t
                    min_state_b_1_violated_constraints.append((int(i) - 1, int(t)))
        # Print the warning message
        # Iterate over each row of the dataframe
        # Remove duplicates by converting the list to a set and back to a list
        min_state_b_1_violated_constraints = list(set(min_state_b_1_violated_constraints))
        # Sort the list first by unit (i) and then by dispatch period (t)
        min_state_b_1_violated_constraints.sort(key=lambda x: (x[0], x[1]))
        # Print the warning message for each pair in the sorted list
        for i, t in min_state_b_1_violated_constraints:
            print(
                f"----- WARNING: min-state-b1 constraint violated for unit: {i}, dispatch period: {t} ----- ")
        print(' ')

    return None

def res_pv_constraints_violations(input_data, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df):

    # if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
    #     Grid_Capacity_1_violated_constraints = []
    #     # Iterate over each row of the dataframe
    #     for index, row in s_Grid_Capacity_1_df.iterrows():
    #         variable = row['Variable']
    #         value = row['Value']
    #         # Check if the value is non-zero
    #         if round(value, 8) != 0:
    #             # Extract i and t using regex
    #             match = re.search(r's_Grid_Capacity_1_(\d+)', variable)
    #             if match:
    #                 t = match.group(1)  # Extract the first number as t
    #                 Grid_Capacity_1_violated_constraints.append(t)
    #     # Print the warning message
    #     # Iterate over each row of the dataframe
    #     # Remove duplicates by converting the list to a set and back to a list
    #     Grid_Capacity_1_violated_constraints = list(set(Grid_Capacity_1_violated_constraints))
    #     # Sort the list first by unit (i) and then by dispatch period (t)
    #     # Grid_Capacity_1_violated_constraints.sort(key=lambda x: (x[0]))
    #     # Print the warning message for each number in the sorted list
    if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
        Grid_Capacity_1_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_1_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_1_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_1_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_1_violated_constraints = sorted(Grid_Capacity_1_violated_constraints)
        for t in Grid_Capacity_1_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_1 constraint violated for dispatch period: {t} ----- ")
        print(' ')

        Grid_Capacity_2_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_2_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_2_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_2_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_2_violated_constraints = sorted(Grid_Capacity_2_violated_constraints)
        # Print the warning message for each number in the sorted list
        for t in Grid_Capacity_2_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_2 constraint violated for dispatch period: {t} ----- ")
        print(' ')

        Grid_Capacity_3_violated_constraints = set()  # Using a set to avoid duplicates

        # Iterate over each row of the dataframe
        for index, row in s_Grid_Capacity_3_df.iterrows():
            variable = row['Variable']
            value = row['Value']
            # Check if the value is non-zero
            if round(value, 8) != 0:
                # Extract t using regex
                match = re.search(r's_Grid_Capacity_3_(\d+)', variable)
                if match:
                    t = int(match.group(1))  # Extract and convert t to an integer
                    Grid_Capacity_3_violated_constraints.add(t)

        # Sort the list of violated constraints
        Grid_Capacity_3_violated_constraints = sorted(Grid_Capacity_3_violated_constraints)
        # Print the warning message for each number in the sorted list
        for t in Grid_Capacity_3_violated_constraints:
            print(
                f"----- WARNING: Grid_Capacity_3 constraint violated for dispatch period: {t} ----- ")
        print(' ')

    return None

def testing_mode_constraints_violations(input_data, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df):

    if input_data["constraints"]["testing_mode_constraints"]:
        # print(s_power_testing_mode_plus_df)
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_testing_mode_plus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: testing mode plus constraint violated at unit {row}, dispatch period {s_power_testing_mode_plus_df.columns[col]} ----- ")
            print("")

        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_testing_mode_minus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: testing mode minus constraint violated at unit {row}, dispatch period {s_power_testing_mode_minus_df.columns[col]} ----- ")
            print("")
    return None



def OOS_mode_constraints_violations(input_data, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df):

    if input_data["constraints"]["OOS_mode_constraints"]:
        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_OOS_less_plus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: OOS mode 'less than' constraint violated at unit {row}, dispatch period {s_power_OOS_less_plus_df.columns[col]} ----- ")
            print("")

        # Finding the positions of non-zero values
        non_zero_positions = np.where(s_power_OOS_more_minus_df.round(6) > 0)
        # Printing row and column information for each non-zero value
        if non_zero_positions:
            for row, col in zip(*non_zero_positions):
                print(
                    f"----- WARNING: OOS mode 'more than' constraint violated at unit {row}, dispatch period {s_power_OOS_more_minus_df.columns[col]} ----- ")
            print("")
    return None




def RES_PV_power_constraints_violations(s_power_plus_df, s_power_minus_df):
    non_zero_positions = np.where(s_power_plus_df.round(6) > 0)
    # Printing row and column information for each non-zero value
    if non_zero_positions:
        for row, col in zip(*non_zero_positions):
            print(
                 f"----- WARNING: RES-PV power plus constraint violated at unit {s_power_plus_df.index[row] - 1}, dispatch period {s_power_plus_df.columns[col]} ----- ")
        print("")

    # Finding the positions of non-zero values
    non_zero_positions = np.where(s_power_minus_df.round(6) > 0)
    # Printing row and column information for each non-zero value
    if non_zero_positions:
        for row, col in zip(*non_zero_positions):
            print(
                 f"----- WARNING: RES-PV power minus constraint violated at unit {s_power_minus_df.index[row] - 1}, dispatch period {s_power_minus_df.columns[col]} ----- ")
        print("")
    return None




def availability_violations(s_avail_values_df):
    # Convert all values to numeric, coercing errors to NaN
    s_avail_values_df = s_avail_values_df.apply(pd.to_numeric, errors='coerce')
    non_zero_positions = np.where(s_avail_values_df.round(6) > 0)

    # Check if there are any non-zero elements
    if len(non_zero_positions[0]) > 0:
        for row, col in zip(*non_zero_positions):
            print(
                f"----- WARNING: Availability constraint violated at unit {s_avail_values_df.index[row] - 1}, dispatch period {s_avail_values_df.columns[col]} -----"
            )
        print("")  # Print an empty line for better formatting

    return None

def output_json(data, input_data, json_template, power_df, Setpoints_df, unit_thermal_states_dfs, state_df, LC,
                Solution_Status,
                primary_ActPR_plus_df, primary_ActPR_minus_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df,
                secondary_ActPR_plus_df, secondary_ActPR_minus_df, CONV, RES, PV, shutdown_df, startup_df,
                primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV,
                tertiary_upwards_APRV, tertiary_downwards_APRV):
    data_output = {}

    data_output["Generating_Units"] = json_template

    data_output["primary_upwards_APRV"] = primary_upwards_APRV
    data_output["primary_downwards_APRV"] = primary_downwards_APRV
    data_output["secondary_upwards_APRV"] = secondary_upwards_APRV
    data_output["secondary_downwards_APRV"] = secondary_downwards_APRV
    data_output["tertiary_upwards_APRV"] = tertiary_upwards_APRV
    data_output["tertiary_downwards_APRV"] = tertiary_downwards_APRV

    data_output["Load_Cutrailment"] = LC

    data_output["Solution_Status"] = Solution_Status

    Units_Setpoints = [list(row) for row in Setpoints_df.values]

    power_df = power_df.drop(0, axis=1)

    Units_Power = [list(row) for row in np.around(power_df.values, 3)]
    #     Unit_thermal_states = []
    state_df = state_df.drop(0, axis=1)
    # Units_states = [list(row) for row in state_df.values]
    Units_states = [[round(value, 3) for value in row] for row in state_df.values]

    # Units_Shutdown = [list(row) for row in shutdown_df.values]
    Units_Shutdown = [[round(value, 3) for value in row] for row in shutdown_df.values]

    # Units_Startup = [list(row) for row in startup_df.values]
    Units_Startup = [[round(value, 3) for value in row] for row in startup_df.values]


    if input_data["constraints"]["primary_active_power_reserves_constraint"]:
        # primary_ActPR_plus = [group['Value'].tolist() for _, group in primary_ActPR_plus_df.groupby('Generator')]
        primary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in primary_ActPR_plus_df.groupby('Generator')]


        # primary_ActPR_minus = [group['Value'].tolist() for _, group in primary_ActPR_minus_df.groupby('Generator')]
        primary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in primary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
        # secondary_ActPR_plus = [group['Value'].tolist() for _, group in secondary_ActPR_plus_df.groupby('Generator')]
        secondary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in secondary_ActPR_plus_df.groupby('Generator')]

        # secondary_ActPR_minus = [group['Value'].tolist() for _, group in secondary_ActPR_minus_df.groupby('Generator')]
        secondary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in secondary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
        # tertiary_ActPR_plus = [group['Value'].tolist() for _, group in tertiary_ActPR_plus_df.groupby('Generator')]
        tertiary_ActPR_plus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in tertiary_ActPR_plus_df.groupby('Generator')]

        # tertiary_ActPR_minus = [group['Value'].tolist() for _, group in tertiary_ActPR_minus_df.groupby('Generator')]
        tertiary_ActPR_minus = [[round(value, 3) for value in group['Value'].tolist()] for _, group in tertiary_ActPR_minus_df.groupby('Generator')]
    else:
        pass
    for i in range(len(data)):
        data_output["Generating_Units"][i]["gen_id"] = data[i]['gen_id']
        data_output["Generating_Units"][i]["comments"] = data[i]['comments']
        data_output["Generating_Units"][i]["Power"] = Units_Power[i]
        if input_data["constraints"]["primary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][0] = primary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][1] = primary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Primary_Active_Power_Reserves(MW)"][1] = 'Nan'
        if input_data["constraints"]["secondary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][0] = secondary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][1] = secondary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Secondary_Active_Power_Reserves(MW)"][1] = 'Nan'
        if input_data["constraints"]["tertiary_active_power_reserves_constraint"]:
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][0] = tertiary_ActPR_plus[i]
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][1] = tertiary_ActPR_minus[i]
        else:
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][0] = 'Nan'
            data_output["Generating_Units"][i]["Tertiary_Active_Power_Reserves(MW)"][1] = 'Nan'

        data_output["Generating_Units"][i]["State"] = Units_states[i]
        data_output["Generating_Units"][i]["Shutdown"] = Units_Shutdown[i]
        data_output["Generating_Units"][i]["Startup"] = Units_Startup[i]
        unit_thermal_states_dfs[i + 1] = unit_thermal_states_dfs[i + 1].iloc[1:]
        # Unit_thermal_states_temp = [list(row) for row in unit_thermal_states_dfs[i + 1].values]
        Unit_thermal_states_temp = [[round(value, 3) for value in row] for row in unit_thermal_states_dfs[i + 1].values]
        data_output["Generating_Units"][i]["Operating-states"] = Unit_thermal_states_temp

        if i in RES:
            if input_data["constraints"]["res_pv_dispatch_variables_constraints"]:
                data_output["Generating_Units"][i]['Setpoints'] = Units_Setpoints[i]
            else:
                data_output["Generating_Units"][i]['Setpoints'] = 'Nan'

    return data_output


def create_output_json_template(data, CONV, RES, PV, Partially_Controllable):
    json_template = []
    for i in range(len(data)):
        if i in CONV:
            json_template.append({'gen_id': 0,
                                  'comments': 'Thermoelectric Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'Operating-states': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0]})
        elif i in PV:
            json_template.append({'gen_id': 0,
                                  'comments': 'PV (Aggregated) Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'State': [0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0]})
        elif i in RES:
            json_template.append({'gen_id': 0,
                                  'comments': 'Wind Turbine Generating Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'State': 0,
                                  'Power': [0.0, 0.0, 0.0, 0.0],
                                  'Setpoints': [0.0, 0.0, 0.0, 0.0]})
        elif i in Partially_Controllable:
            json_template.append({'gen_id': 0,
                                  'comments': 'Partially Controllable Unit 000',
                                  'Primary_Active_Power_Reserves(MW)': [0, 0],
                                  'Secondary_Active_Power_Reserves(MW)': [0, 0],
                                  'Tertiary_Active_Power_Reserves(MW)': [0, 0],
                                  'Operating-states': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                                  'Power': [0.0, 0.0, 0.0, 0.0]})
    return json_template


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

def parse_and_execute_optimization(input_data):
    time_gran = input_data["Time_granularity"]
    input_data = time_granularity(input_data, time_gran)
    data = input_data.get('Generating_Units', [])
    data = filter_generating_units(data)
    # print(data)
    RES_forecast = []
    for i, gen in enumerate(data):
        #     print(gen['Production_Forecast'])
        RES_forecast.append(gen.get('Production_Forecast', []))

    RES_forecast = [list(row) for row in zip(*RES_forecast)]

    Load_forecast = input_data.get("Load_forecast", [])

    intervals = list(range(0, len(Load_forecast)))  # the 1st hour (index 0) is the 24th hour of the previous day#
    # print(intervals[0:-1])
    gen_ids = []
    for i in range(len(data)):
        gen_ids.append(data[i]['gen_id'])
    # Create a list ("RES") containing the index (corresponding to other lists - ie. decision variable lists) that corresponds to the RES units

    # CONV = []
    # RES = []
    # PV = []
    # Partially_Controllable = []

    # on_AGC = []
    # units_numbers = range(len(data))
    # for i, _ in enumerate(data):
    #     #     print(i['comments'])
    #     if data[i]['comments'][:5] == 'Therm':
    #         CONV.append(i)
    #     elif data[i]['comments'][:2] == 'PV':
    #         PV.append(i)
    #     elif "Partially Controllable" in data[i]['comments']:
    #         Partially_Controllable.append(i)
    #     else:
    #         RES.append(i)
    UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, Partially_Controllable = unit_categories(input_data, data)
    # print(PV)
        # these units can provide secondary reserves - regulation
        # for i in CONV:
        # agc_configuration = data[i].get("agc_configuration", {})
        # if agc_configuration.get("isConnected", 0) == 1:
        #     on_AGC.append(i)
        #     for operating_states in data[i]["operating-states"]:
        #         if operating_states["isOperational"]:
        #             operating_states["max-power"] = agc_configuration.get("maxLoad", operating_states["max-power"])
        #             operating_states["min-power"] = agc_configuration.get("minLoad", operating_states["min-power"])
        #         else:
        #             pass
        # else:
        #     pass

    optimization_parameters = input_data.get('optimization_parameters', {})
    warmstart_parameters = optimization_parameters.get('warmStart_parameters', {})
    warmStart = warmstart_parameters.get('warmStart', False)
    keepFiles = warmstart_parameters.get("keepFiles", False)
    logPath = warmstart_parameters.get("logPath", None)
    timeLimit = optimization_parameters.get("early_stopping", {}).get("time_limit", None)
    solver_name = optimization_parameters.get("solver", "highs")
    gapRel = optimization_parameters.get("gapRel", optimization_parameters.get("mip_gap", None))
    gapAbs = optimization_parameters.get("gapAbs", None)
    threads = optimization_parameters.get("threads", None)
    require_optimal = optimization_parameters.get("require_optimal", True)
    solver_options = optimization_parameters.get("highs_options", {})

    Sum_RES_forecast = [sum(row[i] for i in RES) for row in RES_forecast]
    Sum_RES_forecast.insert(0, 0)  # per 15' RES forecasted production - NOT PV INCLUDED -- insert O value (or any value) in indice 0

    # baseline_power_list = []
    # for i, gen in enumerate(input_data["Generating_Units"]):
    #     if input_data['constraints']['rdas_deviations_calculation_constraints']:
    #         baseline_power_list.append(gen['RDAS_power_results'])
    #
    # baseline_state_list = []
    # for i, gen in enumerate(input_data["Generating_Units"]):
    #     if input_data['constraints']['rdas_deviations_calculation_constraints']:
    #         baseline_state_list.append(gen['RDAS_state_results'])
    #
    # baseline_state_df = pd.DataFrame(baseline_state_list)
    # baseline_power_df = pd.DataFrame(baseline_power_list)

    x_load = input_data['Cost_parameters']['x_load']

    # create .mps file through pulp
    solution, RES, Solution_Status, solve_metadata = define_problem_and_solve_problem(data=data,
        input_data=input_data, UNITS=UNITS,
        RES=RES, PV=PV, CONV=CONV, RES_SP=RES_SP, RES_no_SP=RES_no_SP, PV_SP=PV_SP, PV_no_SP=PV_no_SP, Partially_Controllable=Partially_Controllable,
        RES_forecast=RES_forecast,
        Load_forecast=Load_forecast,
        intervals=intervals,
        x_load=x_load,
        on_AGC=on_AGC, warmStart=warmStart, keepFiles=keepFiles, logPath=logPath,
        timeLimit=timeLimit, solver_name=solver_name, gapRel=gapRel, gapAbs=gapAbs,
        threads=threads, solver_options=solver_options, require_optimal=require_optimal)


#----------------------------------------- .mps file created-------------------------------------------------
    # solution_dict, Solution_Status = define_and_solve_problem(binary_vars, integer_vars, continuous_vars)

    (power_df, state_df, startup_df, shutdown_df, ramp_relax_df, s_load_plus_df, s_load_minus_df,
    z_1_df, u_1_df, primary_ActPR_plus_df, primary_ActPR_minus_df, s_primary_APR_upwards_df,
    s_primary_APR_downwards_df, tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, s_tertiary_APR_upwards_df,
    s_tertiary_APR_downwards_df, secondary_ActPR_plus_df, secondary_ActPR_minus_df, s_secondary_APR_upwards_df,
    s_secondary_APR_downwards_df, RES_sum_df,
    primary_APRR_df, binary_primary_df, tertiary_APRR_df, binary_tertiary_df, secondary_APRR_df, binary_secondary_df, u_2_df, setpoint_df, Min_grid_capacity_1_df, Min_grid_capacity_2_df, Min_Power_Calc_df, Grid_Capacity1_df,
    Grid_Capacity2_df, Grid_Capacity3_df, g1_df, g2_df, g3_df, g4_df,
    m_df, y_zone_df, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df, s_must_run_df, s_min_a_left_df,
    s_min_a_1_df, s_min_b_left_df, s_min_b_1_df, s_max_b_left_df, s_max_b_1_df,
    s_min_state_b_left_df, s_min_state_b_1_df, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df,
    s_power_testing_mode_plus_df, s_power_testing_mode_minus_df,
    s_power_plus_df, s_power_minus_df, N_1_df, N_2_df, P_RES_df, P_PV_df, s_avail_values_df, s_N_1_df, s_N_2_df, P_sp_df, g5_df, delta_df,
    s_power_OOS_less_plus_df, s_power_OOS_more_minus_df) = solution_processing(solution, input_data)
    Setpoints_df = setpoint_calculation(input_data, RES, RES_forecast, Sum_RES_forecast, data, power_df, setpoint_df, state_df)
    unit_matrices = units_matrices(u_2_df, data)
    unit_thermal_states_dfs = matrices_to_dfs(unit_matrices)
    LC = load_curtailment(input_data, s_load_plus_df, s_load_minus_df)
    primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV, secondary_downwards_APRV, tertiary_upwards_APRV, tertiary_downwards_APRV = APRR_violation(
    input_data, s_primary_APR_upwards_df, s_primary_APR_downwards_df, s_secondary_APR_upwards_df,
    s_secondary_APR_downwards_df, s_tertiary_APR_upwards_df, s_tertiary_APR_downwards_df)
    forbidden_zones_violations(input_data, s_forbidden_zones_plus_df, s_forbidden_zones_minus_df)
    ramp_up_down_violations(input_data, ramp_relax_df)
    mustRun_violations(input_data, s_must_run_df)
    min_transition_time_between_states_constraints_a_violations(input_data, s_min_a_left_df, s_min_a_1_df)
    min_transition_time_between_states_constraints_b_violations(input_data, s_min_b_left_df, s_min_b_1_df)
    max_transition_time_between_states_constraints_b_violations(input_data, s_max_b_left_df, s_max_b_1_df)
    min_state_transition_constraints_b_violations(input_data, s_min_state_b_left_df, s_min_state_b_1_df)
    res_pv_constraints_violations(input_data, s_Grid_Capacity_1_df, s_Grid_Capacity_2_df, s_Grid_Capacity_3_df)
    testing_mode_constraints_violations(input_data, s_power_testing_mode_plus_df, s_power_testing_mode_minus_df)

    OOS_mode_constraints_violations(input_data, s_power_OOS_less_plus_df, s_power_OOS_more_minus_df)

    RES_PV_power_constraints_violations(s_power_plus_df, s_power_minus_df)
    availability_violations(s_avail_values_df)
    json_template = create_output_json_template(data, CONV, RES, PV, Partially_Controllable)
    data_output_json = output_json(data, input_data, json_template, power_df, Setpoints_df, unit_thermal_states_dfs,
                                   state_df, LC,
                                   Solution_Status, primary_ActPR_plus_df, primary_ActPR_minus_df,
                                   tertiary_ActPR_plus_df, tertiary_ActPR_minus_df, secondary_ActPR_plus_df,
                                   secondary_ActPR_minus_df, CONV, RES, PV, shutdown_df, startup_df,
                                   primary_upwards_APRV, primary_downwards_APRV, secondary_upwards_APRV,
                                   secondary_downwards_APRV,
                                   tertiary_upwards_APRV, tertiary_downwards_APRV)
    data_output_json["Solve_Metadata"] = solve_metadata



    return data_output_json



