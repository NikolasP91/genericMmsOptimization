import unittest

import pandas as pd

from mms.slacks import build_slack_penalty_report


class SlackPenaltyReportTests(unittest.TestCase):
    def test_slack_penalty_report_combines_variable_and_matrix_sources(self):
        input_data = {
            "Cost_parameters": {
                "x_ramp": 10,
                "x_Grid_Capacity": 20,
                "x_primary_APR_up": 30,
            }
        }
        slack_frames = {
            "ramp_relax": pd.DataFrame([[0.0, 2.0]], index=[1], columns=[1, 2]),
            "s_Grid_Capacity_2": pd.DataFrame(
                [("s_Grid_Capacity_2_2", 3.5)], columns=["Variable", "Value"]
            ),
            "s_primary_APR_upwards": pd.DataFrame(
                [("s_primary_APR_upwards_1", 1.0)], columns=["Variable", "Value"]
            ),
        }

        report = build_slack_penalty_report(input_data, slack_frames)
        entries = {entry["family"]: entry for entry in report["entries"]}

        self.assertEqual("warning", report["status"])
        self.assertEqual(3, report["nonzero_slack_count"])
        self.assertAlmostEqual(120.0, report["total_penalty_eur"])
        self.assertEqual(0, entries["ramp_relaxation"]["unit_index"])
        self.assertEqual(2, entries["ramp_relaxation"]["period"])
        self.assertEqual(70.0, entries["grid_capacity_2"]["cost_eur"])

    def test_slack_penalty_report_passes_when_all_slacks_are_zero(self):
        input_data = {"Cost_parameters": {"x_ramp": 10}}
        slack_frames = {"ramp_relax": pd.DataFrame([[0.0]], index=[1], columns=[1])}

        report = build_slack_penalty_report(input_data, slack_frames)

        self.assertEqual("passed", report["status"])
        self.assertEqual(0, report["nonzero_slack_count"])
        self.assertEqual([], report["entries"])


if __name__ == "__main__":
    unittest.main()
