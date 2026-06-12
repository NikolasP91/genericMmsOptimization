import json
import shutil
from pathlib import Path


def prepare_artifact_dir(path):
    if path is None:
        return None
    artifact_dir = Path(path)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def write_json(path, data):
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_run_artifacts(artifact_dir, input_data, output_data=None, error_report=None):
    if artifact_dir is None:
        return
    write_json(artifact_dir / "input_snapshot.json", input_data)
    if output_data is not None:
        write_json(artifact_dir / "output_snapshot.json", output_data)
        if "Validation" in output_data:
            write_json(artifact_dir / "validation_report.json", output_data["Validation"])
        if "Run_Metadata" in output_data:
            write_json(artifact_dir / "run_metadata.json", output_data["Run_Metadata"])
        if "Solve_Metadata" in output_data:
            write_json(artifact_dir / "solve_metadata.json", output_data["Solve_Metadata"])
    if error_report is not None:
        write_json(artifact_dir / "error_report.json", error_report)
    mps_path = Path("example_model.mps")
    if mps_path.exists():
        shutil.copy2(mps_path, artifact_dir / mps_path.name)
