"""Rebuild the final presentation from verified public aggregates, without analysis."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm_retention_lab.storage import file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-svg", action="store_true", help="Also refresh SVGs using Kaleido and Chrome")
    args = parser.parse_args()
    report = ROOT / "report"
    manifest_path = report / "data/analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("stage") != 4:
        raise ValueError("This command requires the completed stage 4 aggregate report")
    aggregates = {}
    for name in ("diagnostics", "experiment", "experiment_checks", "policy"):
        path = report / "data" / f"{name}.json"
        if file_hash(path) != manifest[name + "_sha256"]:
            raise ValueError("Aggregate differs from its recorded hash: " + name)
        aggregates[name] = json.loads(path.read_text(encoding="utf-8"))
    if aggregates["policy"]["lock_sha256"] != manifest["policy_lock_sha256"]:
        raise ValueError("Public policy aggregate differs from the recorded policy lock")

    import plotly
    from plotly.offline import get_plotlyjs
    from crm_retention_lab.experiment_visuals import create_experiment_figures
    from crm_retention_lab.policy_visuals import create_policy_figures
    from crm_retention_lab.reporting import build_report_source
    from crm_retention_lab.visuals import create_figures, export_figures

    if plotly.__version__ != manifest["packages"]["plotly"]:
        raise ValueError("Install the Plotly version recorded in the analysis manifest")
    figures = create_figures(aggregates["diagnostics"])
    figures.update(create_experiment_figures(aggregates["experiment"], aggregates["experiment_checks"]))
    figures.update(create_policy_figures(aggregates["policy"]))
    if len(figures) != 14:
        raise ValueError("The final report must contain all 14 figures")
    destinations = [manifest_path, report / "index.qmd", report / "assets/plotly.min.js"]
    destinations += [report / "assets/figures" / f"{name}.{suffix}" for name in figures
                     for suffix in ("html", "json", "svg")]
    for path in destinations:
        if report.resolve() not in path.resolve().parents or (path.exists() and path.stat().st_nlink > 1):
            raise ValueError("Report output must be a regular file inside report/: " + path.name)
    exported = export_figures(figures, report / "assets/figures", static_svg=args.static_svg)
    if args.static_svg and exported["static_svg"]["status"] != "exported":
        raise ValueError("SVG refresh failed: " + str(exported["static_svg"]["errors"]))
    for paths in exported["figures"].values():
        for key, value in paths.items():
            if value:
                paths[key] = Path(value).relative_to(report).as_posix()
    fragments = {name: (report / row["html"]).read_text(encoding="utf-8")
                 for name, row in exported["figures"].items()}
    source = build_report_source(aggregates["diagnostics"], fragments,
        experiment=aggregates["experiment"], experiment_checks=aggregates["experiment_checks"],
        policy_analysis=aggregates["policy"])
    (report / "index.qmd").write_text(source, encoding="utf-8")
    (report / "assets/plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    manifest["report_source_sha256"] = file_hash(report / "index.qmd")
    manifest["figures"] = exported
    # Keep original analysis provenance; record presentation code separately.
    source_names = ["reporting.py", "experiment_reporting.py", "policy_reporting.py",
                    "visuals.py", "experiment_visuals.py", "policy_visuals.py"]
    build_sources = [ROOT / "src/crm_retention_lab" / name for name in source_names] + [Path(__file__)]
    manifest["presentation_refresh"] = {
        "analysis_recomputed": False, "model_refitted": False, "policy_reselected": False,
        "source_sha256": {path.relative_to(ROOT).as_posix(): file_hash(path) for path in build_sources},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": "report/index.qmd", "figures": len(figures),
                      "analysis_recomputed": False, "static_svg": exported["static_svg"]["status"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
