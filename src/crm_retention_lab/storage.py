"""Typed JSONL artifacts, content hashes, and separate oracle output."""

import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .config import canonical_json, config_hash, parse_ts, simulation_id
from .schema import SCHEMA_VERSION, TABLE_COLUMNS


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _write_jsonl(path, rows):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def ensure_empty_output(path):
    path = Path(path).resolve()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Output already exists and is not empty: {path}. Choose a new directory.")
    return path


def check_output_separation(output, oracle_output):
    output = ensure_empty_output(output)
    if oracle_output is None:
        return output, None
    oracle_output = ensure_empty_output(oracle_output)
    if output == oracle_output or output in oracle_output.parents or oracle_output in output.parents:
        raise ValueError("Observed run and oracle directories must be separate, non-nested paths")
    return output, oracle_output


def technical_summary(observed, config):
    cutoff = parse_ts(config["population"]["observation_end_exclusive"])
    horizon = config["experiment"]["outcome_horizon_days"] + config["experiment"]["settlement_lag_days"]
    assignments = observed["assignments"]
    return {
        "row_counts": {name: len(observed[name]) for name in TABLE_COLUMNS},
        "assigned_by_arm": dict(sorted(Counter(row["arm"] for row in assignments).items())),
        "eligibility_reasons": dict(sorted(Counter(
            reason for row in observed["eligibility_audit"] for reason in row["reason_codes"]
        ).items())),
        "pending_day14_customers": len(observed["customers"]) - len(observed["eligibility_audit"]),
        "profit_window_mature_customers": sum(
            parse_ts(row["assigned_at"]) + timedelta(days=horizon) <= cutoff for row in assignments
        ),
        "no_marketing_effect_estimates_computed": True,
    }


def write_run(output, observed, oracle, config, validation, *, oracle_output=None):
    """Never overwrite a run; only allowlisted observed tables enter its data folder."""
    output, oracle_output = check_output_separation(output, oracle_output)
    if not validation["valid"]:
        raise ValueError("Refusing to write a dataset that failed validation")
    if set(observed) != set(TABLE_COLUMNS):
        raise ValueError("Observed dataset does not match the public table allowlist")
    data_path = output / "observed"
    data_path.mkdir(parents=True, exist_ok=False)
    observed_hashes = {}
    for name in TABLE_COLUMNS:
        path = data_path / f"{name}.jsonl"
        _write_jsonl(path, observed[name])
        observed_hashes[f"observed/{name}.jsonl"] = file_hash(path)
    _write_json(output / "config.snapshot.json", config)
    _write_json(output / "validation.json", validation)

    oracle_hash = None
    if oracle_output is not None:
        oracle_output.mkdir(parents=True, exist_ok=True)
        path = oracle_output / "latent_customers.jsonl"
        _write_jsonl(path, oracle)
        oracle_hash = file_hash(path)
        _write_json(oracle_output / "ORACLE_NOTICE.json", {
            "simulation_id": simulation_id(config),
            "purpose": "generator_state_only_not_an_analysis_input",
            "content": "latent_customer_parameters_only",
            "potential_outcomes_implemented": False,
            "sha256": oracle_hash,
        })

    project_root = Path(__file__).resolve().parents[2]
    source_files = sorted((project_root / "src").rglob("*.py"))
    source_hashes = {path.relative_to(project_root).as_posix(): file_hash(path) for path in source_files}
    manifest = {
        "artifact_version": "0.1.0",
        "schema_version": SCHEMA_VERSION,
        "simulation_id": simulation_id(config),
        "purpose": config["runtime"]["purpose"],
        "data_origin": "fully_synthetic",
        "scenario": config["runtime"]["scenario"],
        "seed": config["reproducibility"]["base_seed"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime": {"python": platform.python_version(), "implementation": sys.implementation.name,
                    "package_version": __version__, "third_party_runtime_dependencies": []},
        "config_sha256": config_hash(config),
        "observed_sha256": observed_hashes,
        "source_sha256": source_hashes,
        "source_identity": "source hashes; no parent repository commit assumed",
        "oracle": {"written_separately": oracle_output is not None,
                   "latent_file_sha256": oracle_hash, "potential_outcomes_implemented": False},
        "summary": technical_summary(observed, config),
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


def load_observed(path):
    """Read public tables only. Do not accept an oracle file alongside them."""
    path = Path(path)
    expected = {f"{name}.jsonl" for name in TABLE_COLUMNS}
    actual = {item.name for item in path.iterdir() if item.is_file()}
    if actual != expected:
        raise ValueError(f"Observed file allowlist mismatch: missing={expected-actual}, extra={actual-expected}")
    observed = {}
    for name in TABLE_COLUMNS:
        rows = []
        with (path / f"{name}.jsonl").open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                row = json.loads(line)
                if not isinstance(row, dict) or set(row) != set(TABLE_COLUMNS[name]):
                    raise ValueError(f"Invalid fields in {name}, line {line_number}")
                rows.append(row)
        observed[name] = rows
    return observed


def verify_run_hashes(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    config = json.loads((path / "config.snapshot.json").read_text(encoding="utf-8"))
    if config_hash(config) != manifest["config_sha256"]:
        raise ValueError("Configuration snapshot hash mismatch")
    expected = {f"observed/{name}.jsonl" for name in TABLE_COLUMNS}
    if set(manifest["observed_sha256"]) != expected:
        raise ValueError("Manifest does not contain exactly the observed file allowlist")
    for relative_path in sorted(expected):
        if file_hash(path / relative_path) != manifest["observed_sha256"][relative_path]:
            raise ValueError(f"Observed file hash mismatch: {relative_path}")
    return config
