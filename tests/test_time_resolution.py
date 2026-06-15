import copy
import unittest

from mms.model.preprocessing import round_max_time_to_periods, round_min_time_to_periods, time_granularity
from mms.model.time_resolution import prepare_operating_state_time_resolution


def _base_unit():
    return {
        "gen_id": 0,
        "comments": "Thermal Generating Unit",
        "operating-states": [
            {"id": 1, "isShutdown": False, "isOperational": False, "isEnabled": True},
            {"id": 2, "isShutdown": False, "isOperational": False, "isEnabled": False},
            {"id": 3, "isShutdown": False, "isOperational": True, "isEnabled": False},
        ],
        "operating-state-transitions": [
            {
                "from": 1,
                "transitions": [
                    {"id": 2, "transition-cost": 4, "min-transition-time_b": 25},
                ],
            },
            {
                "from": 2,
                "transitions": [
                    {"id": 3, "transition-cost": 6},
                ],
            },
            {
                "from": 3,
                "transitions": [
                    {"id": 1, "transition-cost": 0},
                ],
            },
        ],
        "state-transitions": [],
    }


class TimeResolutionPreprocessingTests(unittest.TestCase):
    def test_explicit_subperiod_transient_state_is_embedded_into_transition_arc(self):
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        input_data["Generating_Units"][0]["operating-states"][1]["state_role"] = "synchronization"

        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        unit = prepared["Generating_Units"][0]
        report = prepared["Time_Resolution_Report"]

        self.assertEqual(1, report["embedded_state_count"])
        self.assertEqual("passed", report["status"])
        self.assertNotIn(2, {state["id"] for state in unit["operating-states"]})
        self.assertNotIn(2, {transition["from"] for transition in unit["operating-state-transitions"]})

        transitions_from_1 = next(
            transition_group["transitions"]
            for transition_group in unit["operating-state-transitions"]
            if transition_group["from"] == 1
        )
        embedded_arc = next(transition for transition in transitions_from_1 if transition["id"] == 3)

        self.assertEqual(10.0, embedded_arc["transition-cost"])
        self.assertEqual(2, embedded_arc["embedded_transient_states"][0]["id"])
        self.assertEqual(
            "min-transition-time_b",
            embedded_arc["embedded_transient_states"][0]["timing_minutes"][0]["field"],
        )
        self.assertNotIn("min-transition-time_b", embedded_arc)

    def test_unmarked_subperiod_timer_is_reported_but_not_embedded(self):
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }

        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        unit = prepared["Generating_Units"][0]
        report = prepared["Time_Resolution_Report"]

        self.assertEqual(0, report["embedded_state_count"])
        self.assertEqual("passed", report["status"])
        self.assertIn(2, {state["id"] for state in unit["operating-states"]})
        self.assertTrue(
            any(
                issue["code"] == "subperiod_transition_min_time"
                and issue["severity"] == "info"
                and issue["operating_state_id"] == 2
                for issue in report["issues"]
            )
        )

        converted = time_granularity(prepared, 60)
        transition_to_2 = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]
        self.assertEqual(1, transition_to_2["min-transition-time_b"])

    def test_maximum_times_round_down_to_dispatch_periods(self):
        self.assertEqual(1, round_min_time_to_periods(25, 60))
        self.assertEqual(0, round_max_time_to_periods(25, 60))
        self.assertEqual(1, round_max_time_to_periods(60, 60))
        self.assertEqual(1, round_max_time_to_periods(119, 60))

        data = {
            "Generating_Units": [
                {
                    "operating-states": [
                        {
                            "min-time-enabled": 25,
                            "max-time-enabled": 25,
                            "min-time-enabled-left": 25,
                            "max-time-enabled-left": 25,
                        }
                    ],
                    "operating-state-transitions": [
                        {
                            "from": 1,
                            "transitions": [
                                {
                                    "id": 2,
                                    "min-transition-time_b": 25,
                                    "max-transition-time_b": 25,
                                }
                            ],
                        }
                    ],
                    "state-transitions": [
                        {"transitions": {"min-transition-time-left": 25, "min-transition-time": 25}}
                    ],
                }
            ]
        }

        converted = time_granularity(data, 60)
        state = converted["Generating_Units"][0]["operating-states"][0]
        transition = converted["Generating_Units"][0]["operating-state-transitions"][0]["transitions"][0]

        self.assertEqual(1, state["min-time-enabled"])
        self.assertEqual(0, state["max-time-enabled"])
        self.assertEqual(1, state["min-time-enabled-left"])
        self.assertEqual(0, state["max-time-enabled-left"])
        self.assertEqual(1, transition["min-transition-time_b"])
        self.assertEqual(0, transition["max-transition-time_b"])

    def test_explicit_transient_state_with_period_level_duration_is_not_embedded(self):
        input_data = {
            "Time_granularity": 60,
            "optimization_parameters": {},
            "Generating_Units": [_base_unit()],
        }
        unit = input_data["Generating_Units"][0]
        unit["operating-states"][1]["state_role"] = "synchronization"
        unit["operating-state-transitions"][0]["transitions"][0]["min-transition-time_b"] = 90

        prepared = prepare_operating_state_time_resolution(copy.deepcopy(input_data))
        report = prepared["Time_Resolution_Report"]

        self.assertEqual(0, report["embedded_state_count"])
        self.assertIn(2, {state["id"] for state in prepared["Generating_Units"][0]["operating-states"]})
        self.assertTrue(
            any(issue["code"] == "transient_state_not_subperiod" for issue in report["issues"])
        )


if __name__ == "__main__":
    unittest.main()
