import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "v2.1_last_real_values_RDAS_60_FAT---test-case_BIOMASS.json"


class FullRunRegressionTests(unittest.TestCase):
    def test_default_biomass_case_matches_known_solver_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_path = tmp_path / "optimization_output.json"
            artifact_dir = tmp_path / "artifacts"
            log_path = tmp_path / "run_log.txt"

            completed = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    str(CONFIG_FILE),
                    "-o",
                    str(output_path),
                    "--artifacts-dir",
                    str(artifact_dir),
                    "--log-file",
                    str(log_path),
                    "--solver-log-file",
                    str(artifact_dir / "solver_log.txt"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=180,
            )

            if completed.returncode != 0:
                self.fail(
                    "Full optimization regression failed.\n"
                    f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
                )

            with output_path.open(encoding="utf-8") as f:
                output = json.load(f)

            solve_metadata = output["Solve_Metadata"]
            self.assertEqual("Optimal", output["Solution_Status"])
            self.assertEqual("passed", output["Validation"]["status"])
            self.assertAlmostEqual(373212.7626889, solve_metadata["objective_value"], delta=1e-3)
            self.assertEqual(11442, solve_metadata["num_constraints"])
            self.assertEqual(4973, solve_metadata["num_variables"])
            self.assertEqual(1000.0, solve_metadata["big_m"])
            self.assertGreaterEqual(solve_metadata["mps_write_seconds"], 0)
            self.assertGreaterEqual(solve_metadata["solver_seconds"], 0)
            self.assertEqual("passed", output["Diagnostics_Report"]["status"])
            self.assertIn(output["Warning_Report"]["status"], ("passed", "warning"))
            self.assertGreater(output["Performance_Profile"]["total_seconds"], 0)
            self.assertIn("pipeline", output["Performance_Profile"])

            expected_artifacts = [
                "input_snapshot.json",
                "output_snapshot.json",
                "run_metadata.json",
                "solve_metadata.json",
                "validation_report.json",
                "dispatch_instructions.json",
                "reserve_monitoring_report.json",
                "res_curtailment_report.json",
                "warning_report.json",
                "diagnostics_report.json",
                "performance_profile.json",
                "run_events.jsonl",
                "run_log.txt",
                "solver_log.txt",
                "example_model.mps",
            ]
            for filename in expected_artifacts:
                with self.subTest(artifact=filename):
                    self.assertTrue((artifact_dir / filename).exists())

            with (artifact_dir / "run_events.jsonl").open(encoding="utf-8") as f:
                event_names = [json.loads(line)["event"] for line in f if line.strip()]
            self.assertIn("run_started", event_names)
            self.assertIn("solver_log_configured", event_names)
            self.assertIn("optimization_finished", event_names)
            self.assertIn("validation_finished", event_names)

            solver_log = (artifact_dir / "solver_log.txt").read_text(encoding="utf-8")
            self.assertIn("Running HiGHS", solver_log)


if __name__ == "__main__":
    unittest.main()
