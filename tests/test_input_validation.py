import copy
import json
import unittest
from pathlib import Path

from input_validation import validate_input_data


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json"


class InputValidationTests(unittest.TestCase):
    def test_project_input_passes_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        report = validate_input_data(data)
        self.assertEqual(report["errors"], [])

    def test_bad_load_length_fails_validation(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        bad_data = copy.deepcopy(data)
        bad_data["Generating_Units"][0]["availability"] = [1, 2, 3]
        report = validate_input_data(bad_data)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("availability" in error for error in report["errors"]))

    def test_noncontiguous_ids_are_warned(self):
        with INPUT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        warned_data = copy.deepcopy(data)
        warned_data["Generating_Units"][0]["gen_id"] = 99
        report = validate_input_data(warned_data)
        self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
