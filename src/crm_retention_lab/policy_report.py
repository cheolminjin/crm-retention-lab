"""Append reviewed aggregate policy results; never refit or reevaluate here."""

import json
from pathlib import Path

from .reporting import _json, build_report_source
from .storage import file_hash


def append_policy_report(policy_dir, report_dir, *, static_svg=False):
    from .policy_pipeline import verify_policy_lock
    from .policy_visuals import create_policy_figures
    from .visuals import export_figures

    policy_dir, report = Path(policy_dir).resolve(), Path(report_dir).resolve()
    if policy_dir == report or policy_dir in report.parents or report in policy_dir.parents:
        raise ValueError("Private model artifacts and aggregate report must be separate")
    public_files = ["index.qmd", "data/policy.json", "data/analysis_manifest.json"]
    public_files += [f"assets/figures/{name}.{suffix}" for name in
        ("policy_validation", "policy_profit", "policy_allocation", "policy_guardrails", "policy_segments")
        for suffix in ("html", "json", "svg")]
    for relative in public_files:
        destination = report / relative
        if report not in destination.resolve().parents:
            raise ValueError("A policy report output resolves outside the public report directory")
        if destination.exists() and destination.stat().st_nlink > 1:
            raise ValueError("Refusing to overwrite a policy report file with multiple hard links")
    lock = verify_policy_lock(policy_dir)
    digest = json.loads((policy_dir / "analysis.digest.json").read_text(encoding="utf-8"))
    if file_hash(policy_dir / "analysis.json") != digest["sha256"]:
        raise ValueError("Saved final analysis changed; do not silently replace evaluated results")
    analysis = json.loads((policy_dir / "analysis.json").read_text(encoding="utf-8"))
    if analysis["lock_sha256"] != file_hash(policy_dir / "policy.lock.json"):
        raise ValueError("Analysis is not associated with the frozen policy")
    manifest = json.loads((report / "data/analysis_manifest.json").read_text(encoding="utf-8"))
    aggregates = {}
    for name in ("diagnostics", "experiment", "experiment_checks"):
        path = report / "data" / (name + ".json")
        if file_hash(path) != manifest[name + "_sha256"]:
            raise ValueError("Existing aggregate changed: " + name)
        aggregates[name] = json.loads(path.read_text(encoding="utf-8"))
    if aggregates["diagnostics"]["metadata"]["input_simulation_id"] != analysis["metadata"]["splits"]["train"]["input_simulation_id"]:
        raise ValueError("Existing report and policy models use different training sources")
    figures = create_policy_figures(analysis)
    exported = export_figures(figures, report / "assets/figures", static_svg=static_svg)
    for paths in exported["figures"].values():
        for key, path in paths.items():
            if path:
                paths[key] = Path(path).relative_to(report).as_posix()
    if manifest["stage"] == 3:
        manifest["stage_3_provenance"] = {key: manifest[key] for key in
            ("analysis_scope", "as_of", "analysis_source_sha256", "source_run_manifest_sha256", "analysis_spec_sha256")}
    manifest["figures"]["figures"].update(exported["figures"])
    manifest["figures"]["policy_static_svg"] = exported["static_svg"]
    fragments = {name: (report / row["html"]).read_text(encoding="utf-8")
                 for name, row in manifest["figures"]["figures"].items()}
    _json(report / "data/policy.json", analysis)
    (report / "index.qmd").write_text(build_report_source(aggregates["diagnostics"], fragments,
        experiment=aggregates["experiment"], experiment_checks=aggregates["experiment_checks"], policy_analysis=analysis), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    manifest.update(stage=4, analysis_scope="train_diagnosis_and_experiment__validation_selection__locked_final_policy",
        final_test_used=True, oracle_used=False, splits=analysis["metadata"]["splits"],
        policy_sha256=file_hash(report / "data/policy.json"), policy_lock_sha256=analysis["lock_sha256"],
        policy_spec_sha256=lock["spec_sha256"], report_source_sha256=file_hash(report / "index.qmd"),
        analysis_source_sha256={path.relative_to(root).as_posix(): file_hash(path) for path in sorted((root / "src").rglob("*.py"))})
    manifest["packages"].update(analysis["model_manifest"]["software"])
    _json(report / "data/analysis_manifest.json", manifest)
    return {"quarto_source": str(report / "index.qmd"), "figures": len(fragments),
            "selected_policy": analysis["selection"]["chosen_policy"]["id"], "static_svg": exported["static_svg"]}
