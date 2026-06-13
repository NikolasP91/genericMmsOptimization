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


def write_run_artifacts(
    artifact_dir,
    input_data,
    output_data=None,
    error_report=None,
    diagnostics_report=None,
    log_file=None,
):
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
        if "Dispatch_Instructions" in output_data:
            write_json(artifact_dir / "dispatch_instructions.json", output_data["Dispatch_Instructions"])
        if "Reserve_Monitoring_Report" in output_data:
            write_json(artifact_dir / "reserve_monitoring_report.json", output_data["Reserve_Monitoring_Report"])
        if "RES_Curtailment_Report" in output_data:
            write_json(artifact_dir / "res_curtailment_report.json", output_data["RES_Curtailment_Report"])
        if "Thermal_Cost_Curve_Audit" in output_data:
            write_json(artifact_dir / "thermal_cost_curve_audit.json", output_data["Thermal_Cost_Curve_Audit"])
        if "Thermal_Cost_Curve_Generation" in output_data:
            write_json(artifact_dir / "thermal_cost_curve_generation.json", output_data["Thermal_Cost_Curve_Generation"])
        if "Thermal_Cost_Report" in output_data:
            write_json(artifact_dir / "thermal_cost_report.json", output_data["Thermal_Cost_Report"])
        if "Penalty_Hierarchy_Audit" in output_data:
            write_json(artifact_dir / "penalty_hierarchy_audit.json", output_data["Penalty_Hierarchy_Audit"])
        if "Objective_Breakdown_Report" in output_data:
            write_json(artifact_dir / "objective_breakdown_report.json", output_data["Objective_Breakdown_Report"])
        if "Slack_Penalty_Report" in output_data:
            write_json(artifact_dir / "slack_penalty_report.json", output_data["Slack_Penalty_Report"])
        if "Warning_Report" in output_data:
            write_json(artifact_dir / "warning_report.json", output_data["Warning_Report"])
        if "Diagnostics_Report" in output_data:
            write_json(artifact_dir / "diagnostics_report.json", output_data["Diagnostics_Report"])
        if "Performance_Profile" in output_data:
            write_json(artifact_dir / "performance_profile.json", output_data["Performance_Profile"])
    if error_report is not None:
        write_json(artifact_dir / "error_report.json", error_report)
    if diagnostics_report is not None:
        write_json(artifact_dir / "diagnostics_report.json", diagnostics_report)
    if log_file:
        log_path = Path(log_file)
        if log_path.exists():
            shutil.copy2(log_path, artifact_dir / log_path.name)
    mps_path = Path("example_model.mps")
    if mps_path.exists():
        shutil.copy2(mps_path, artifact_dir / mps_path.name)
