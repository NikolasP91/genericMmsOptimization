import unittest

import pulp as pl

from mms.model.operating_states import (
    create_min_time_states_constraints_states,
    create_min_transition_time_between_states_constraints_a,
    create_min_transition_time_between_states_constraints_b,
    create_operating_state_max_time_constraints,
    create_operating_state_max_time_constraints_b,
    create_operating_state_min_time_constraints_a,
    create_operating_state_min_time_constraints_b,
)


def _cost_parameters():
    return {
        "x_min_transition_states_left": 1000,
        "x_min_transition_states": 1000,
        "x_min_transition_oper_states_a_left": 1000,
        "x_min_transition_oper_states_a": 1000,
        "x_min_transition_oper_states_b_left": 1000,
        "x_min_transition_oper_states_b": 1000,
        "x_min_oper_state_time_a_left": 1000,
        "x_min_oper_state_time_a": 1000,
        "x_min_oper_state_time_b_left": 1000,
        "x_min_oper_state_time_b": 1000,
        "x_max_oper_state_time_left": 1000,
        "x_max_oper_state_time": 1000,
        "x_max_oper_state_time_b_left": 1000,
        "x_max_oper_state_time_b": 1000,
    }


def _input_data():
    return {"Cost_parameters": _cost_parameters()}


def _fixed_binary(prob, name, value):
    variable = pl.LpVariable(name, lowBound=0, upBound=1, cat="Binary")
    prob += variable == int(value)
    return variable


def _fixed_binary_matrix(prob, prefix, unit_count, intervals, values_by_unit):
    return [
        [
            _fixed_binary(prob, f"{prefix}_{unit_index + 1}_{t}", values_by_unit[unit_index].get(t, 0))
            for t in intervals
        ]
        for unit_index in range(unit_count)
    ]


def _fixed_operating_state_variables(prob, intervals, schedule_by_state):
    return {
        (0, t, state_id): _fixed_binary(prob, f"u_2_1_{t}_{state_id}", schedule_by_state[state_id].get(t, 0))
        for state_id in schedule_by_state
        for t in intervals
    }


def _solve(prob, objective_terms):
    prob += objective_terms
    prob.solve(pl.HiGHS(msg=False))
    if pl.LpStatus[prob.status] != "Optimal":
        raise AssertionError(f"Expected Optimal, got {pl.LpStatus[prob.status]}")


def _value(prob, variable_name):
    return prob.variablesDict()[variable_name].value()


def _sum_values(prob, prefix):
    return sum(
        variable.value() or 0
        for variable_name, variable in prob.variablesDict().items()
        if variable_name.startswith(prefix)
    )


class TimeConstraintScenarioTests(unittest.TestCase):
    def test_state_minimum_time_slacks_cover_initial_startup_and_shutdown_windows(self):
        intervals = [0, 1, 2, 3, 4, 5]
        prob = pl.LpProblem("state_minimum_time_scenario", pl.LpMinimize)
        data = [
            {
                "gen_id": 0,
                "state-transitions": [
                    {"from": 0, "transitions": {"min-transition-time-left": 1, "min-transition-time": 2}},
                    {"from": 1, "transitions": {"min-transition-time-left": 0, "min-transition-time": 2}},
                ],
            }
        ]
        state = _fixed_binary_matrix(prob, "state", 1, intervals, [{1: 0, 2: 1, 3: 0, 4: 0, 5: 1}])
        startup = _fixed_binary_matrix(prob, "startup", 1, intervals, [{2: 1}])
        shutdown = _fixed_binary_matrix(prob, "shutdown", 1, intervals, [{4: 1}])

        prob, objective_terms = create_min_time_states_constraints_states(
            prob, 0, _input_data(), data, state, intervals, startup, shutdown
        )

        _solve(prob, objective_terms)

        self.assertEqual(1, _value(prob, "s_min_state_b_left_1_1"))
        self.assertEqual(2, _sum_values(prob, "s_min_state_b_1_1_"))

    def test_operating_state_minimum_dwell_a_and_b_detect_early_exit(self):
        intervals = [0, 1, 2, 3, 4]
        prob = pl.LpProblem("operating_state_minimum_dwell_scenario", pl.LpMinimize)
        data = [
            {
                "gen_id": 0,
                "operating-states": [
                    {
                        "id": 4,
                        "isEnabled": True,
                        "min-time-enabled-left": 1,
                        "min-time-enabled": 2,
                    }
                ],
            }
        ]
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                4: {
                    0: 1,
                    1: 0,
                    2: 1,
                    3: 0,
                    4: 0,
                }
            },
        )

        prob, objective_terms = create_operating_state_min_time_constraints_a(
            prob, 0, _input_data(), data, u_2_dict, len(intervals), intervals
        )
        prob, objective_terms = create_operating_state_min_time_constraints_b(
            prob, objective_terms, _input_data(), data, u_2_dict, len(intervals), intervals
        )

        _solve(prob, objective_terms)

        self.assertEqual(1, _value(prob, "s_min_oper_state_time_a_left_1_4_1"))
        self.assertEqual(1, _value(prob, "s_min_oper_state_time_a_1_1_4_3"))
        self.assertEqual(1, _value(prob, "s_min_oper_state_time_b_left_1_4_1"))
        self.assertEqual(1, _sum_values(prob, "s_min_oper_state_time_b_1_1_4_"))

    def test_min_transition_time_a_blocks_departure_from_source_state_too_soon(self):
        intervals = [0, 1, 2, 3, 4]
        prob = pl.LpProblem("transition_minimum_time_a_scenario", pl.LpMinimize)
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time-left_a": 1,
                                "min-transition-time_a": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 1, 1: 0, 2: 1, 3: 0, 4: 0},
                2: {0: 0, 1: 1, 2: 0, 3: 1, 4: 1},
            },
        )

        prob, objective_terms = create_min_transition_time_between_states_constraints_a(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        _solve(prob, objective_terms)

        self.assertEqual(1, _value(prob, "s_min_a_left_1_1"))
        self.assertEqual(1, _value(prob, "s_min_a_1_1_3"))

    def test_min_transition_time_b_requires_destination_state_to_persist(self):
        intervals = [0, 1, 2, 3, 4]
        prob = pl.LpProblem("transition_minimum_time_b_scenario", pl.LpMinimize)
        data = [
            {
                "gen_id": 0,
                "operating-state-transitions": [
                    {
                        "from": 1,
                        "transitions": [
                            {
                                "id": 2,
                                "min-transition-time-left_b": 1,
                                "min-transition-time_b": 3,
                            }
                        ],
                    }
                ],
            }
        ]
        u_2_dict = _fixed_operating_state_variables(
            prob,
            intervals,
            {
                1: {0: 0, 1: 1, 2: 0, 3: 1, 4: 1},
                2: {0: 0, 1: 0, 2: 1, 3: 0, 4: 0},
            },
        )

        prob, objective_terms = create_min_transition_time_between_states_constraints_b(
            prob, 0, _input_data(), data, u_2_dict, intervals
        )

        _solve(prob, objective_terms)

        self.assertEqual(1, _value(prob, "s_min_b_left_1_1"))
        self.assertEqual(2, _sum_values(prob, "s_min_b_1_1_"))

    def test_max_operating_time_constraints_detect_overstaying_generic_and_b_windows(self):
        intervals = [0, 1, 2, 3, 4]
        generic_prob = pl.LpProblem("generic_max_operating_time_scenario", pl.LpMinimize)
        generic_data = [
            {
                "gen_id": 0,
                "operating-states": [
                    {
                        "id": 4,
                        "isEnabled": True,
                        "max-time-enabled-left": 1,
                        "max-time-enabled": 2,
                    }
                ],
            }
        ]
        generic_u_2 = _fixed_operating_state_variables(
            generic_prob,
            intervals,
            {4: {0: 1, 1: 1, 2: 1, 3: 1, 4: 0}},
        )

        generic_prob, generic_objective = create_operating_state_max_time_constraints(
            generic_prob, 0, _input_data(), generic_data, generic_u_2, len(intervals), intervals, CONV=[0], RES=[]
        )
        _solve(generic_prob, generic_objective)

        self.assertEqual(1, _value(generic_prob, "s_max_oper_state_time_left_1_4_2"))
        self.assertEqual(1, _value(generic_prob, "s_max_oper_state_time_1_1_4_3"))

        transition_prob = pl.LpProblem("transition_max_operating_time_b_scenario", pl.LpMinimize)
        transition_data = [
            {
                "gen_id": 0,
                "operating-states": [
                    {"id": 4, "isEnabled": False},
                    {"id": 5, "isEnabled": True},
                ],
                "operating-state-transitions": [
                    {
                        "from": 4,
                        "transitions": [
                            {
                                "id": 5,
                                "max-transition-time-left_b": 1,
                                "max-transition-time_b": 2,
                            }
                        ],
                    }
                ],
            }
        ]
        transition_u_2 = _fixed_operating_state_variables(
            transition_prob,
            intervals,
            {
                4: {0: 1, 1: 0, 2: 0, 3: 0, 4: 0},
                5: {0: 0, 1: 1, 2: 1, 3: 1, 4: 0},
            },
        )

        transition_prob, transition_objective = create_operating_state_max_time_constraints_b(
            transition_prob, 0, _input_data(), transition_data, transition_u_2, len(intervals), intervals
        )
        _solve(transition_prob, transition_objective)

        self.assertEqual(1, _value(transition_prob, "s_max_oper_state_time_b_left_1_4_5_2"))
        self.assertEqual(1, _value(transition_prob, "s_max_oper_state_time_b_1_1_4_5_3"))


if __name__ == "__main__":
    unittest.main()
