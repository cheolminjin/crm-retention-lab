"""Render the prepared Quarto source and copy a self-contained deliverable."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarto", default=shutil.which("quarto"), help="Quarto executable (1.11.9 tested)")
    parser.add_argument("--temp-dir", type=Path, help="Writable ASCII-only temporary path for Windows Quarto")
    args = parser.parse_args()
    if not args.quarto:
        parser.error("Install Quarto or provide --quarto with its executable path")
    root = Path(__file__).resolve().parents[1]
    report = root / "report"
    manifest = json.loads((report / "data/analysis_manifest.json").read_text(encoding="utf-8"))
    if sha256(report / "index.qmd") != manifest["report_source_sha256"]:
        raise ValueError("Quarto source differs from the analysis manifest; regenerate with diagnose")
    for name in ("diagnostics", "experiment", "experiment_checks", "policy"):
        key = name + "_sha256"
        if key in manifest and sha256(report / "data" / f"{name}.json") != manifest[key]:
            raise ValueError(f"Aggregate {name} differs from the analysis manifest; regenerate the analysis")
    env = dict(os.environ)
    temp = (args.temp_dir or Path(env.get("TEMP", str(root / ".tools/tmp")))).resolve()
    temp.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp), DENO_DIR=str(temp / "deno-cache"))
    version = subprocess.check_output([args.quarto, "--version"], cwd=root, env=env, text=True).strip()
    subprocess.run([args.quarto, "render", "report/index.qmd", "--to", "html"], cwd=root, env=env, check=True)
    destination = root / "reports/CRM_DIAGNOSTIC.html"
    shutil.copyfile(report / "_site/index.html", destination)
    result = {"quarto_version": version, "analysis_manifest_sha256": sha256(report / "data/analysis_manifest.json"),
              "render_inputs_sha256": {path.relative_to(root).as_posix(): sha256(path)
                                       for path in (report / "index.qmd", report / "_quarto.yml", report / "styles.css")},
              "html_sha256": sha256(destination), "output": "reports/CRM_DIAGNOSTIC.html"}
    result["render_inputs_sha256"]["scripts/render_report.py"] = sha256(Path(__file__))
    theme = report / "theme.scss"
    if theme.exists():
        result["render_inputs_sha256"][theme.relative_to(root).as_posix()] = sha256(theme)
    (root / "reports/RENDER_MANIFEST.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
