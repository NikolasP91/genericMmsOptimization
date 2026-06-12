import json
import unittest
from pathlib import Path

from solution_validation import validate_solution


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "benchmarks" / "known_answer_cases.json"


class KnownAnswerBenchmarkTests(unittest.TestCase):
    def test_known_answer_cases_validate_as_expected(self):
        with BENCHMARK_PATH.open(encoding="utf-8") as f:
            cases = json.load(f)
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(case=case["name"]):
                report = validate_solution(case["input"], case["output"])
                self.assertEqual(report["status"], case["expected_validation_status"])


if __name__ == "__main__":
    unittest.main()
