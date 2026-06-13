import unittest
from contextlib import redirect_stdout
from io import StringIO

from RV_genericMmsOptimization import define_problem_and_solve_problem as public_problem_entry
from mms.model.bounds import forbidden_zone_big_m, reserve_activation_bound
from mms.model.preprocessing import filter_generating_units, round_to_best, time_granularity, unit_categories
from mms.model.problem import define_problem_and_solve_problem


class ModelModuleBoundaryTests(unittest.TestCase):
    def test_main_script_uses_modular_problem_entry_point(self):
        self.assertIs(public_problem_entry, define_problem_and_solve_problem)

    def test_filter_generating_units_removes_fully_unavailable_units(self):
        units = [
            {"availability": [0, 0, 0]},
            {"availability": [0, 1, 0]},
            {"availability": 0},
            {"availability": 5},
        ]

        self.assertEqual([units[1], units[3]], filter_generating_units(units))

    def test_unit_categories_preserve_current_set_construction(self):
        input_data = {
            "Generating_Units": [
                {"Accepts_SP": 0},
                {"Accepts_SP": 1},
                {"Accepts_SP": 1},
                {"Accepts_SP": 0},
            ],
            "Other_coefficients": {"include_PV": True},
        }
        data = [
            {"comments": "Thermal Generating Unit"},
            {"comments": "PV Aggregated Unit"},
            {"comments": "Wind Turbine Generating Unit"},
            {"comments": "Partially Controllable Unit"},
        ]

        with redirect_stdout(StringIO()):
            UNITS, CONV, RES, PV, RES_SP, RES_no_SP, PV_SP, PV_no_SP, on_AGC, partially = unit_categories(
                input_data, data
            )

        self.assertEqual([0, 2, 1], UNITS)
        self.assertEqual([0], CONV)
        self.assertEqual([2], RES)
        self.assertEqual([1], PV)
        self.assertEqual([2], RES_SP)
        self.assertEqual([], RES_no_SP)
        self.assertEqual([1], PV_SP)
        self.assertEqual([], PV_no_SP)
        self.assertEqual([], on_AGC)
        self.assertEqual([3], partially)

    def test_time_granularity_converts_minutes_to_period_counts(self):
        data = {
            "Generating_Units": [
                {
                    "operating-states": [
                        {
                            "min-time-enabled": 30,
                            "max-time-enabled": 45,
                            "min-time-enabled-left": 15,
                            "max-time-enabled-left": 60,
                        }
                    ],
                    "operating-state-transitions": [
                        {
                            "from": 1,
                            "transitions": [
                                {
                                    "id": 2,
                                    "min-transition-time_a": 30,
                                    "max-transition-time_a": 45,
                                    "min-transition-time-left_b": 15,
                                }
                            ],
                        }
                    ],
                    "state-transitions": [
                        {"transitions": {"min-transition-time-left": 15, "min-transition-time": 30}}
                    ],
                }
            ]
        }

        converted = time_granularity(data, 15)
        state = converted["Generating_Units"][0]["operating-states"][0]
        transition = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
        unit_transition = converted["Generating_Units"][0]["state-transitions"][0]["transitions"]

        self.assertEqual(2, state["min-time-enabled"])
        self.assertEqual(3, state["max-time-enabled"])
        self.assertEqual(1, state["min-time-enabled-left"])
        self.assertEqual(4, state["max-time-enabled-left"])
        self.assertEqual(2, transition["min-transition-time_a"])
        self.assertEqual(3, transition["max-transition-time_a"])
        self.assertEqual(1, transition["min-transition-time-left_b"])
        self.assertEqual(1, unit_transition["min-transition-time-left"])
        self.assertEqual(2, unit_transition["min-transition-time"])

    def test_round_to_best_matches_existing_ceiling_behavior(self):
        self.assertEqual(3, round_to_best(45, 15))
        self.assertEqual(4, round_to_best(46, 15))
        self.assertEqual(100000000000, round_to_best(float("inf"), 15))

    def test_reserve_activation_bound_uses_unit_and_state_limits(self):
        unit = {
            "availability": [12],
            "Primary_Active_Power_Reserves(MW)": [20, 20],
        }
        operating_state = {
            "max-power": [9],
            "min-power": [3],
            "user_max_power": 8,
            "user_min_power": 4,
        }

        self.assertEqual(
            8.0,
            reserve_activation_bound(
                unit, "Primary_Active_Power_Reserves(MW)", 0, 0, operating_state
            ),
        )
        self.assertEqual(
            8.0,
            reserve_activation_bound(
                unit, "Primary_Active_Power_Reserves(MW)", 1, 0, operating_state
            ),
        )

    def test_forbidden_zone_big_m_is_local_and_never_larger_than_fallback(self):
        unit = {"availability": [20]}
        local_m = forbidden_zone_big_m(unit, [8, 12], 0, 1000)

        self.assertGreaterEqual(local_m, 10)
        self.assertLess(local_m, 1000)
        self.assertEqual(5.0, forbidden_zone_big_m(unit, [8, 12], 0, 5))


if __name__ == "__main__":
    unittest.main()
