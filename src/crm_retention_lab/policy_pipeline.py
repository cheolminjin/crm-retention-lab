"""Fit/select/lock before creating an independent final evaluation population."""

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import config_hash, load_config
from .contracts import validate_dataset
from .marts import build_policy_marts
from .storage import file_hash, load_observed, verify_run_hashes

ROOT = Path(__file__).resolve().parents[2]
DECISION_FILES = ("uplift.py", "policy.py", "policy_evaluation.py", "policy_pipeline.py", "marts.py",
                  "config.py", "contracts.py", "finance.py", "simulation.py", "storage.py", "schema.py", "eligibility.py")


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _progress(message):
    print(message, flush=True)


def _decision_hashes():
    return {"src/crm_retention_lab/" + name: file_hash(ROOT / "src/crm_retention_lab" / name)
            for name in DECISION_FILES}


def _load_split(path, split):
    config = verify_run_hashes(path)
    observed = load_observed(Path(path) / "observed")
    validation = validate_dataset(observed, config)
    if not validation["valid"]:
        raise ValueError("Invalid source: " + str(validation["errors"][:3]))
    marts = build_policy_marts(observed, config, split=split)
    n = len(marts["features"])
    if not n or n != marts["metadata"]["finalized_label_count"]:
        raise ValueError("Policy evaluation requires a nonempty, fully settled ITT population")
    marts["metadata"]["source_manifest_sha256"] = file_hash(Path(path) / "manifest.json")
    return marts, config


def _save_marts(path, marts):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    for name in ("features", "outcomes"):
        with (path / f"{name}.jsonl").open("x", encoding="utf-8") as handle:
            for row in marts[name]:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    _write(path / "metadata.json", marts["metadata"])


def _specs(analysis_config, design):
    from .policy import default_policy_specs
    specs = default_policy_specs(design)
    for spec in specs:
        spec["seed"] = analysis_config["policy_random_seed"]
    if ([row["model"] for row in specs if row["kind"] == "uplift"][::4] != analysis_config["candidate_models"]
            or sorted({row["penalty_lambda"] for row in specs if row["kind"] == "uplift"}) != analysis_config["penalty_lambdas"]
            or [row["kind"] for row in specs if row["kind"] != "uplift"] != analysis_config["baseline_kinds"]
            or analysis_config["risk_filter"] is not True or analysis_config["baseline_model"] != "hgb"
            or analysis_config["evaluation_nuisance_model"] != "hgb"):
        raise ValueError("Candidate definitions must match the prespecified policy grid")
    return specs


def flat_predictions(predictions, model):
    return {**predictions[model], "risk": 1 - predictions["control_repeat_risk"],
            "evaluation_profit": predictions["hgb"]["profit"]}


def select_policy(results, specs):
    """Predeclared conservative screen followed by a one-SE simplicity rule."""
    candidates = []
    for result in results:
        profit = result["primary"]
        profit_pass = profit["ci_lower"] is not None and profit["ci_lower"] > result["rollout"]["setup_per_eligible_krw"]
        harm_pass = all(row["assessment"] == "within_tolerance" for row in result["guardrails"])
        eligible = profit_pass and harm_pass and result["exposure"]["caps_ok"]
        result["screen"] = {"profit_pass": profit_pass, "harm_pass": harm_pass, "eligible": eligible}
        if eligible:
            candidates.append(result)
    if not candidates:
        return {"chosen_policy": next(row for row in specs if row["kind"] == "control"),
                "reason": "no_candidate_passed_validation_screen", "feasible_ids": [], "one_se_ids": [],
                "selection_uses_final_test": False}
    best = max(candidates, key=lambda row: row["primary"]["estimate"])
    threshold = best["primary"]["estimate"] - best["primary"]["score_standard_error"]
    near_best = [row for row in candidates if row["primary"]["estimate"] >= threshold]
    simple = [row for row in near_best if row["policy_spec"]["model"] == "ridge"]
    ranked = sorted(simple or near_best, key=lambda row: (-row["primary"]["estimate"],
                    row["policy_spec"]["penalty_lambda"], row["policy_id"]))
    return {"chosen_policy": ranked[0]["policy_spec"], "reason": "prefer_ridge_within_one_se" if simple else "best_feasible_hgb",
            "feasible_ids": [row["policy_id"] for row in candidates], "one_se_ids": [row["policy_id"] for row in near_best],
            "best_validation_id": best["policy_id"], "one_se_threshold_krw": threshold,
            "selection_uses_final_test": False}


def fit_select_lock(train_run, validation_run, output, analysis_config_path, final_run):
    """Never open final data: require its destination to be absent before fitting."""
    import joblib
    from .policy import prepare_policy_inputs
    from .policy_evaluation import evaluate_policy
    from .uplift import fit_uplift_models, predict_uplift_models

    output, final_run = Path(output).resolve(), Path(final_run).resolve()
    if output.exists() or final_run.exists():
        raise ValueError("Selection requires new output and an absent final run; do not select after final exposure")
    settings_path = Path(analysis_config_path).resolve()
    settings = _read(settings_path)
    final_profile = settings_path.parent / settings["final_profile"]
    final_config = load_config(final_profile)
    _progress("Loading train and validation observed-only marts")
    train, train_config = _load_split(train_run, "train")
    validation, validation_config = _load_split(validation_run, "validation")
    expected_val = load_config(settings_path.parent / settings["validation_profile"])
    if config_hash(validation_config) != config_hash(expected_val):
        raise ValueError("Validation run differs from the prespecified profile")
    seeds = [c["reproducibility"]["base_seed"] for c in (train_config, validation_config, final_config)]
    if len(set(seeds)) != 3:
        raise ValueError("Train/validation/final populations require independent distinct seeds")
    train_ids = {row["customer_id"] for row in train["features"]}
    if train_ids.intersection(row["customer_id"] for row in validation["features"]):
        raise ValueError("Overlapping training and validation customers")
    for key in ("experiment", "offer", "policy_constraints", "inference", "splits"):
        if not train_config[key] == validation_config[key] == final_config[key]:
            raise ValueError("Split designs differ: " + key)
    specs = _specs(settings, train_config)
    _progress("Fitting two model families using train only")
    bundle = fit_uplift_models(train, settings["model_spec"])
    predictions = predict_uplift_models(bundle, validation["features"])
    prepared = {name: prepare_policy_inputs(validation["features"], flat_predictions(predictions, name), train_config)
                for name in settings["candidate_models"]}
    results = []
    candidates = [spec for spec in specs if spec["kind"] == "uplift"]
    guardrail_confidence = 1 - settings["validation_selection"]["harm_familywise_alpha"] / (len(candidates) * 2)
    for spec in candidates:
        results.append(evaluate_policy(spec, validation["features"], validation["outcomes"],
            flat_predictions(predictions, spec["model"]), train_config,
            {"repetitions": 0, "prepared": prepared[spec["model"]], "guardrail_confidence": guardrail_confidence,
             "evaluation_role": "validation_screen_not_confirmatory"}))
    selection = select_policy(results, specs)
    output.mkdir(parents=True, exist_ok=False)
    _save_marts(output / "train", train)
    _save_marts(output / "validation", validation)
    joblib.dump(bundle, output / "models.joblib", compress=3)
    _write(output / "model_manifest.json", bundle["manifest"])
    _write(output / "validation.json", {"results": results, "selection": selection})
    lock = {
        "version": "0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "simulated_policy_lock_at": train_config["splits"]["policy_lock_at"],
        "selected_policy": selection["chosen_policy"], "selection": selection,
        "baselines": [spec for spec in specs if spec["kind"] != "uplift"], "settings": settings,
        "constraints": train_config["policy_constraints"], "final_run": str(final_run),
        "final_config": final_config, "final_config_sha256": config_hash(final_config),
        "final_generated_before_lock": False, "final_used_for_selection": False, "oracle_used": False,
        "input_splits": {"train": train["metadata"], "validation": validation["metadata"]},
        "model_sha256": file_hash(output / "models.joblib"),
        "model_manifest_sha256": file_hash(output / "model_manifest.json"),
        "validation_sha256": file_hash(output / "validation.json"),
        "decision_source_sha256": _decision_hashes(),
        "spec_sha256": file_hash(ROOT / "docs/STAGE_4_POLICY_SPEC.md"),
        "analysis_config_path": str(settings_path), "analysis_config_sha256": file_hash(settings_path),
        "final_profile_path": str(final_profile), "final_profile_sha256": file_hash(final_profile),
    }
    _write(output / "policy.lock.json", lock)
    _write(output / "policy.lock.digest.json", {"sha256": file_hash(output / "policy.lock.json")})
    _progress("Locked policy: " + selection["chosen_policy"]["id"])
    return {"policy_id": selection["chosen_policy"]["id"], "reason": selection["reason"],
            "lock": str(output / "policy.lock.json"), "validation_n": len(validation["features"])}


def verify_policy_lock(output):
    output = Path(output)
    lock = _read(output / "policy.lock.json")
    if file_hash(output / "policy.lock.json") != _read(output / "policy.lock.digest.json")["sha256"]:
        raise ValueError("Policy lock digest changed")
    for file, key in (("models.joblib", "model_sha256"), ("model_manifest.json", "model_manifest_sha256"),
                      ("validation.json", "validation_sha256")):
        if file_hash(output / file) != lock[key]:
            raise ValueError("Locked artifact changed: " + file)
    if _decision_hashes() != lock["decision_source_sha256"]:
        raise ValueError("Decision code changed after lock; never silently refit or reselect")
    for path, key in ((lock["analysis_config_path"], "analysis_config_sha256"),
                      (lock["final_profile_path"], "final_profile_sha256"),
                      (ROOT / "docs/STAGE_4_POLICY_SPEC.md", "spec_sha256")):
        if file_hash(path) != lock[key]:
            raise ValueError("Locked analysis specification changed")
    validation_selection = _read(output / "validation.json")["selection"]
    if lock["selection"] != validation_selection or lock["selected_policy"] != validation_selection["chosen_policy"]:
        raise ValueError("Locked policy differs from validation selection")
    if lock["settings"] != _read(lock["analysis_config_path"]):
        raise ValueError("Locked settings differ from the hashed analysis configuration")
    if (config_hash(lock["final_config"]) != lock["final_config_sha256"]
            or config_hash(load_config(lock["final_profile_path"])) != lock["final_config_sha256"]):
        raise ValueError("Locked final generator configuration changed")
    expected_baselines = [row for row in _specs(lock["settings"], lock["final_config"]) if row["kind"] != "uplift"]
    if lock["baselines"] != expected_baselines or lock["constraints"] != lock["final_config"]["policy_constraints"]:
        raise ValueError("Locked baseline definitions or constraints changed")
    return lock


def evaluate_locked_policy(output, *, generate_final=False):
    """Create final data only after lock verification, then evaluate fixed policies once."""
    import joblib
    import numpy as np
    from .policy import allocate_policy, prepare_policy_inputs
    from .policy_evaluation import evaluate_policy, make_bootstrap_indices
    from .uplift import predict_uplift_models

    output = Path(output).resolve()
    lock = verify_policy_lock(output)
    if (output / "analysis.json").exists():
        raise ValueError("Final analysis already exists; render it without evaluating or selecting again")
    final_run = Path(lock["final_run"])
    if not final_run.exists():
        if not generate_final:
            raise ValueError("Use --generate-final to create the locked independent evaluation population")
        from .simulation import generate_dataset
        from .storage import write_run
        _progress("Generating final population after policy lock")
        observed, oracle = generate_dataset(lock["final_config"])
        validation = validate_dataset(observed, lock["final_config"])
        write_run(final_run, observed, oracle, lock["final_config"], validation,
                  oracle_output=ROOT / "data/oracle" / final_run.name)
        del observed, oracle
    manifest = _read(final_run / "manifest.json")
    if datetime.fromisoformat(manifest["created_at_utc"]) <= datetime.fromisoformat(lock["created_at_utc"]):
        raise ValueError("Final source must have been created after the policy lock")
    final, config = _load_split(final_run, "final_test")
    if config_hash(config) != lock["final_config_sha256"]:
        raise ValueError("Final run does not match the locked profile")
    if final["metadata"]["identity_namespace"] in {row["identity_namespace"] for row in lock["input_splits"].values()}:
        raise ValueError("Final population overlaps earlier simulation identities")
    if not (output / "final_test").exists():
        _save_marts(output / "final_test", final)
    # Models are loaded only from this local run after their digest has been verified.
    bundle = joblib.load(output / "models.joblib")
    predictions = predict_uplift_models(bundle, final["features"])
    prepared = {name: prepare_policy_inputs(final["features"], flat_predictions(predictions, name), config)
                for name in ("ridge", "hgb")}
    bootstrap = lock["settings"]["final_bootstrap"]
    pool = make_bootstrap_indices(final["features"], bootstrap["repetitions"], bootstrap["seed"])
    specs = [lock["selected_policy"]] + [row for row in lock["baselines"] if row["id"] != lock["selected_policy"]["id"]]
    results = []
    for index, spec in enumerate(specs):
        _progress(f"Final evaluation {index + 1}/{len(specs)}: {spec['id']} ({bootstrap['repetitions']} resamples)")
        cache = output / f"final-{spec['id']}.json"
        flat = flat_predictions(predictions, spec["model"])
        if cache.exists():
            cached = _read(cache)
            if cached["lock_sha256"] != file_hash(output / "policy.lock.json") or cached["source_sha256"] != file_hash(final_run / "manifest.json"):
                raise ValueError("Incomplete-run checkpoint differs from locked inputs")
            result = cached["result"]
        else:
            result = evaluate_policy(spec, final["features"], final["outcomes"], flat, config,
                {"repetitions": bootstrap["repetitions"], "seed": bootstrap["seed"], "indices": pool,
                 "prepared": prepared[spec["model"]], "evaluation_role": "locked_primary" if index == 0 else "exploratory_baseline"})
            allocation = allocate_policy(final["features"], flat, spec, config, prepared=prepared[spec["model"]])
            result["allocation"] = {key: value for key, value in allocation.items() if key != "actions"}
            result["segments"] = []
            for pack in (200, 500, 1000):
                mask = np.asarray([row["first_pack_grams"] == pack for row in final["features"]])
                counts = np.bincount(allocation["actions"][mask], minlength=3)
                result["segments"].append({"first_pack_grams": pack, "n": int(mask.sum()),
                    **{arm: int(counts[code]) for code, arm in enumerate(("control", "info", "coupon"))}})
            if index == 0:
                action_text = "".join(json.dumps({"customer_id": row["customer_id"], "assigned_at": row["assigned_at"],
                    "action": ("control", "info", "coupon")[int(action)]}, ensure_ascii=False) + "\n"
                    for row, action in zip(final["features"], allocation["actions"]))
                action_path = output / "selected_customer_actions.jsonl"
                if action_path.exists():
                    if action_path.read_text(encoding="utf-8") != action_text:
                        raise ValueError("Recovered allocation differs from the frozen policy")
                else:
                    action_path.write_text(action_text, encoding="utf-8")
            _write(cache, {"lock_sha256": file_hash(output / "policy.lock.json"),
                          "source_sha256": file_hash(final_run / "manifest.json"), "result": result})
        results.append(result)
    verify_policy_lock(output)
    analysis = {"version": "0.1.0", "metadata": {"synthetic": True, "oracle_used": False,
        "final_test_used": True, "models_refit_after_validation": False,
        "splits": {**lock["input_splits"], "final_test": final["metadata"]}},
        "model_manifest": bundle["manifest"], "selection": lock["selection"],
        "validation": _read(output / "validation.json")["results"], "final": results,
        "constraints": lock["constraints"], "lock": {key: value for key, value in lock.items()
            if key not in {"final_run", "analysis_config_path", "final_profile_path", "final_config"}},
        "lock_sha256": file_hash(output / "policy.lock.json")}
    _write(output / "analysis.json", analysis)
    _write(output / "analysis.digest.json", {"sha256": file_hash(output / "analysis.json"),
        "lock_sha256": file_hash(output / "policy.lock.json"), "final_source_sha256": file_hash(final_run / "manifest.json")})
    return {"analysis": str(output / "analysis.json"), "chosen_policy": lock["selected_policy"]["id"],
            "primary": results[0]["primary"], "guardrails": results[0]["guardrails"], "rollout": results[0]["rollout"]}
