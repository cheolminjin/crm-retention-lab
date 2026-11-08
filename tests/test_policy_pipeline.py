"""Selection rules and lock guards using temporary artifacts only.

These tests never generate, load, or evaluate the actual final population.
"""

import copy
from contextlib import ExitStack, contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crm_retention_lab.config import config_hash
from crm_retention_lab import policy_pipeline as pipeline
from crm_retention_lab.storage import file_hash


HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_JOBLIB = importlib.util.find_spec("joblib") is not None


@contextmanager
def project_temporary_directory():
    base = (Path(__file__).resolve().parents[1] / ".test-tmp").resolve()
    base.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="policy-pipeline-", dir=base)
    resolved = Path(temporary.name).resolve()
    if base not in resolved.parents:
        raise RuntimeError("Temporary directory escaped the project test workspace")
    try:
        yield str(resolved)
    finally:
        temporary.cleanup()


def result(policy_id, model="hgb", estimate=100, se=10, lower=80, harm=True, caps=True, penalty=0):
    spec = {"id": policy_id, "kind": "uplift", "model": model, "penalty_lambda": penalty}
    return {"policy_id": policy_id, "policy_spec": spec,
            "primary": {"estimate": estimate, "score_standard_error": se, "ci_lower": lower},
            "rollout": {"setup_per_eligible_krw": 10},
            "guardrails": [{"metric": metric, "assessment": "within_tolerance" if harm else "not_established"}
                           for metric in ("unsubscribe_60d", "refund_customer_flag")],
            "exposure": {"caps_ok": caps}}


CONTROL = {"id": "control", "kind": "control", "model": "hgb", "penalty_lambda": 0}


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def lock_fixture(root):
    """Small fake artifacts; a mocked profile loader prevents any real source read."""
    output = root / "run"
    output.mkdir()
    (root / "docs").mkdir()
    spec_path = root / "docs" / "STAGE_4_POLICY_SPEC.md"
    spec_path.write_text("fixed test specification", encoding="utf-8")
    settings_path, profile_path = root / "settings.json", root / "final_profile.json"
    settings = {"final_profile": "final_profile.json", "test_setting": 1}
    final_config = {"policy_constraints": {"rollout_eligible_customers": 10000}, "test_seed": 123}
    _write_json(settings_path, settings)
    _write_json(profile_path, {"test_profile": True})
    chosen = result("chosen", "ridge")["policy_spec"]
    selection = {"chosen_policy": chosen, "reason": "prefer_ridge_within_one_se", "selection_uses_final_test": False}
    (output / "models.joblib").write_bytes(b"not-a-real-model")
    _write_json(output / "model_manifest.json", {"n_train": 6, "oracle_used": False})
    _write_json(output / "validation.json", {"results": [], "selection": selection})
    lock = {
        "selected_policy": chosen, "selection": selection, "settings": settings,
        "final_config": final_config, "final_config_sha256": config_hash(final_config),
        "baselines": [CONTROL], "constraints": final_config["policy_constraints"],
        "model_sha256": file_hash(output / "models.joblib"),
        "model_manifest_sha256": file_hash(output / "model_manifest.json"),
        "validation_sha256": file_hash(output / "validation.json"),
        "decision_source_sha256": {"fake-decision-source": "fixed"},
        "analysis_config_path": str(settings_path), "analysis_config_sha256": file_hash(settings_path),
        "final_profile_path": str(profile_path), "final_profile_sha256": file_hash(profile_path),
        "spec_sha256": file_hash(spec_path),
    }
    _write_json(output / "policy.lock.json", lock)
    _write_json(output / "policy.lock.digest.json", {"sha256": file_hash(output / "policy.lock.json")})
    return output, lock, final_config


def lock_patches(root, final_config):
    stack = ExitStack()
    stack.enter_context(patch.object(pipeline, "ROOT", root))
    stack.enter_context(patch.object(pipeline, "_decision_hashes", return_value={"fake-decision-source": "fixed"}))
    stack.enter_context(patch.object(pipeline, "load_config", return_value=copy.deepcopy(final_config)))
    stack.enter_context(patch.object(pipeline, "_specs", return_value=[CONTROL, result("chosen", "ridge")["policy_spec"]]))
    return stack


class PolicySelectionTests(unittest.TestCase):
    def test_profit_boundary_harm_and_caps_screen_then_control_fallback(self):
        candidates = [result("at-boundary", lower=10), result("harm-fails", harm=False),
                      result("cap-fails", caps=False), result("no-ci", lower=None)]
        selection = pipeline.select_policy(candidates, [CONTROL])
        self.assertEqual(selection["chosen_policy"], CONTROL)
        self.assertEqual(selection["reason"], "no_candidate_passed_validation_screen")
        self.assertFalse(selection["selection_uses_final_test"])
        self.assertTrue(all(not row["screen"]["eligible"] for row in candidates))

    def test_ridge_within_best_candidates_one_se_is_preferred(self):
        candidates = [result("hgb-best", estimate=100, se=12), result("ridge-near", "ridge", estimate=90),
                      result("ridge-too-low", "ridge", estimate=87)]
        selection = pipeline.select_policy(candidates, [CONTROL])
        self.assertEqual(selection["chosen_policy"]["id"], "ridge-near")
        self.assertEqual(selection["one_se_threshold_krw"], 88)
        self.assertNotIn("ridge-too-low", selection["one_se_ids"])

    def test_hgb_wins_when_ridge_is_outside_one_se(self):
        candidates = [result("hgb-best", estimate=100, se=5), result("ridge-far", "ridge", estimate=94)]
        selection = pipeline.select_policy(candidates, [CONTROL])
        self.assertEqual(selection["chosen_policy"]["id"], "hgb-best")
        self.assertEqual(selection["reason"], "best_feasible_hgb")

    def test_ties_use_lower_lambda_then_id_after_model_preference(self):
        candidates = [result("ridge-z", "ridge", estimate=100, penalty=0.5),
                      result("ridge-b", "ridge", estimate=100, penalty=0),
                      result("ridge-a", "ridge", estimate=100, penalty=0)]
        selection = pipeline.select_policy(candidates, [CONTROL])
        self.assertEqual(selection["chosen_policy"]["id"], "ridge-a")

    @unittest.skipUnless(HAS_NUMPY, "Optional NumPy analysis dependency is not installed")
    def test_ranking_family_keeps_common_hgb_nuisance_and_nonrepeat_risk(self):
        import numpy as np

        predictions = {"ridge": {"profit": np.full((2, 3), 11)}, "hgb": {"profit": np.full((2, 3), 99)},
                       "control_repeat_risk": np.asarray([0.2, 0.8])}
        flat = pipeline.flat_predictions(predictions, "ridge")
        self.assertIs(flat["profit"], predictions["ridge"]["profit"])
        self.assertIs(flat["evaluation_profit"], predictions["hgb"]["profit"])
        np.testing.assert_allclose(flat["risk"], [0.8, 0.2])


class PolicyLockTests(unittest.TestCase):
    def test_valid_fixture_verifies_without_loading_any_model_or_population(self):
        with project_temporary_directory() as directory:
            root = Path(directory)
            output, expected, config = lock_fixture(root)
            with lock_patches(root, config), patch.object(pipeline, "_load_split") as load_split:
                self.assertEqual(pipeline.verify_policy_lock(output), expected)
                load_split.assert_not_called()

    def test_lock_digest_detects_direct_policy_change(self):
        with project_temporary_directory() as directory:
            root = Path(directory)
            output, lock, config = lock_fixture(root)
            lock["selected_policy"] = CONTROL
            _write_json(output / "policy.lock.json", lock)
            with lock_patches(root, config), self.assertRaisesRegex(ValueError, "digest"):
                pipeline.verify_policy_lock(output)

    def test_semantic_lock_checks_survive_a_recomputed_sidecar(self):
        modifications = {
            "selected_policy": lambda lock: lock.update(selected_policy=CONTROL),
            "selection": lambda lock: lock["selection"].update(reason="changed-after-inspection"),
            "settings": lambda lock: lock["settings"].update(test_setting=2),
            "final_config": lambda lock: lock["final_config"].update(test_seed=456),
            "baseline": lambda lock: lock.update(baselines=[]),
            "constraints": lambda lock: lock.update(constraints={"rollout_eligible_customers": 20000}),
        }
        for name, modify in modifications.items():
            with self.subTest(change=name), project_temporary_directory() as directory:
                root = Path(directory)
                output, lock, config = lock_fixture(root)
                frozen_config = copy.deepcopy(config)
                modify(lock)
                _write_json(output / "policy.lock.json", lock)
                _write_json(output / "policy.lock.digest.json", {"sha256": file_hash(output / "policy.lock.json")})
                with lock_patches(root, frozen_config), self.assertRaises(ValueError):
                    pipeline.verify_policy_lock(output)

    def test_artifact_source_and_specification_changes_are_rejected(self):
        for name in ("models.joblib", "model_manifest.json", "validation.json", "settings.json", "spec", "code"):
            with self.subTest(change=name), project_temporary_directory() as directory:
                root = Path(directory)
                output, _, config = lock_fixture(root)
                with lock_patches(root, config):
                    if name == "code":
                        with patch.object(pipeline, "_decision_hashes", return_value={"fake-decision-source": "changed"}), self.assertRaises(ValueError):
                            pipeline.verify_policy_lock(output)
                    else:
                        path = (root / "docs/STAGE_4_POLICY_SPEC.md" if name == "spec"
                                else root / name if name == "settings.json" else output / name)
                        path.write_bytes(path.read_bytes() + b"\nchanged")
                        with self.assertRaises(ValueError):
                            pipeline.verify_policy_lock(output)

    @unittest.skipUnless(HAS_NUMPY and HAS_JOBLIB, "Optional model runtime is not installed")
    def test_preexisting_final_destination_blocks_selection_before_source_access(self):
        with project_temporary_directory() as directory:
            root = Path(directory)
            final_destination = root / "fake-final-destination"
            final_destination.mkdir()
            with patch.object(pipeline, "_load_split") as load_split, self.assertRaisesRegex(ValueError, "absent final run"):
                pipeline.fit_select_lock(root / "unread-train", root / "unread-validation", root / "new-output",
                                         root / "unread-settings.json", final_destination)
            load_split.assert_not_called()
            self.assertFalse((root / "new-output").exists())


if __name__ == "__main__":
    unittest.main()
