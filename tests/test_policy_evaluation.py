"""Hand-calculated off-policy scores and allocation-aware resampling tests."""

import copy
import importlib.util
import json
import unittest

from crm_retention_lab.policy_evaluation import (
    bootstrap_policy, evaluate_policy, make_bootstrap_indices, policy_scores,
)


HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    import numpy as np


def example():
    features = [{"customer_id": f"private-{index}", "assigned_at": f"2025-01-{15 + index // 2:02d}T09:00:00+09:00"}
                for index in range(6)]
    outcomes = [{**feature, "arm": "control" if index % 2 == 0 else "info",
                 "contribution_profit_60d_krw": 10 if index % 2 == 0 else 20,
                 "unsubscribe_60d": int(index % 2 == 0), "refund_customer_flag": 0,
                 "is_outcome_mature": True, "is_profit_settled": True}
                for index, feature in enumerate(features)]
    predictions = {"profit": np.tile([0.0, 10.0, 8.0], (6, 1)), "evaluation_profit": np.zeros((6, 3))}
    config = {
        "experiment": {"arms": [{"id": arm, "probability": 1 / 3} for arm in ("control", "info", "coupon")]},
        "offer": {"send_cost_krw_per_attempt": 20, "coupon_discount_krw": 3000},
        "policy_constraints": {"rollout_eligible_customers": 10000,
                               "budget_reservation_cap_krw_per_10000": 3000000,
                               "max_contact_fraction": 0.5, "fixed_setup_cost_krw_per_rollout": 100000},
        "inference": {"confidence_level": 0.95, "guardrail_bonferroni_individual_one_sided_confidence": 0.975,
                      "guardrail_max_increase_unsubscribe_pp": 0.5, "guardrail_max_increase_refund_customer_pp": 1.0,
                      "bootstrap_repetitions": 2000},
        "reproducibility": {"base_seed": 19},
    }
    return features, outcomes, predictions, config


class RecordingAllocator:
    """A tiny fixed positive-gain rule; occurrences, not distinct IDs, fill slots."""

    def __init__(self):
        self.calls = []

    def __call__(self, features, predictions, spec, config, *, indices=None, return_audit=True, prepared=None):
        selected = np.arange(len(features)) if indices is None else np.asarray(indices)
        self.calls.append((spec.copy(), selected.copy(), prepared))
        actions = np.zeros(len(selected), dtype=np.int8)
        if spec["kind"] == "control":
            return {"actions": actions, "caps_ok": True}
        groups = {}
        for occurrence, source in enumerate(selected):
            groups.setdefault(features[source]["assigned_at"], []).append(occurrence)
        for group in groups.values():
            limit = int(len(group) * config["policy_constraints"]["max_contact_fraction"])
            gains = predictions["profit"][selected[group], 1] - predictions["profit"][selected[group], 0]
            ordered = sorted(zip(group, gains), key=lambda row: (-row[1], row[0]))
            for occurrence, gain in ordered[:limit]:
                if gain > 0:
                    actions[occurrence] = 1
        return {"actions": actions, "caps_ok": True}


@unittest.skipUnless(HAS_NUMPY, "Optional NumPy analysis dependency is not installed")
class PolicyEvaluationTests(unittest.TestCase):
    def test_hand_calculated_three_arm_dr_ipw_and_full_denominator(self):
        scores = policy_scores([10, 20, 30], [0, 1, 2], [1, 1, 0],
                               [[1, 2, 3], [4, 5, 6], [7, 8, 9]], [1 / 3] * 3)
        np.testing.assert_allclose(scores["dr"], [2, 50, 7])
        np.testing.assert_allclose(scores["dr_control"], [28, 4, 7])
        np.testing.assert_allclose(scores["dr_difference"], [-26, 46, 0])
        np.testing.assert_allclose(scores["ipw_difference"], [-30, 60, 0])
        self.assertAlmostEqual(float(scores["dr_difference"].mean()), 20 / 3)
        self.assertEqual(float(scores["ipw"].mean()), 20)  # 60 / all three customers.
        np.testing.assert_array_equal(scores["matched"], [False, True, False])
        np.testing.assert_array_equal(scores["weights"], [0, 3, 0])

    def test_all_control_has_exact_zero_differences_and_no_setup(self):
        features, outcomes, predictions, config = example()
        predictions["evaluation_profit"][:] = [[10000, -500, 1]] * 6
        allocator = RecordingAllocator()
        result = evaluate_policy({"id": "control", "kind": "control"}, features, outcomes, predictions, config,
                                 {"allocator": allocator, "repetitions": 25, "include_draws": True})
        for metric in ("primary", "ipw_check"):
            for key in ("estimate", "ci_lower", "ci_upper", "standard_error"):
                self.assertEqual(result[metric][key], 0)
        for guardrail in result["guardrails"]:
            self.assertEqual((guardrail["estimate"], guardrail["ci_upper"]), (0, 0))
        self.assertEqual(result["rollout"]["setup_cost_krw"], 0)
        self.assertEqual(result["rollout"]["ci_lower"], 0)
        self.assertEqual(result["rollout"]["ci_upper"], 0)
        self.assertEqual(result["overlap"]["policy"]["matched_n"], 3)
        self.assertEqual(result["overlap"]["policy"]["effective_sample_size"], 3)
        self.assertNotIn("private-", json.dumps(result, allow_nan=False))

    def test_shared_resampling_preserves_interleaved_batches_and_reproducibility(self):
        features, _, _, _ = example()
        interleaved = [features[index] for index in (0, 2, 4, 1, 3, 5)]
        pool = make_bootstrap_indices(interleaved, 100, 51)
        np.testing.assert_array_equal(pool, make_bootstrap_indices(interleaved, 100, 51))
        self.assertFalse(np.array_equal(pool, make_bootstrap_indices(interleaved, 100, 52)))
        for replicate in pool:
            self.assertTrue(all(interleaved[source]["assigned_at"] == interleaved[position]["assigned_at"]
                                for position, source in enumerate(replicate)))
        self.assertTrue(any(len(set(row)) < len(row) for row in pool))

    def test_duplicate_occurrences_reallocate_with_daily_caps_and_shared_scores(self):
        features, outcomes, predictions, config = example()
        pool = np.asarray([[0, 0, 2, 2, 4, 4], [1, 1, 3, 3, 5, 5]], dtype=np.int32)
        allocator, cached = RecordingAllocator(), object()
        spec = {"id": "fixed-rule", "kind": "rule", "penalty_lambda": 0.5}
        spec_before = copy.deepcopy(spec)
        draws = bootstrap_policy(spec, features, outcomes, predictions, config,
                                 {"allocator": allocator, "prepared": cached, "indices": pool, "repetitions": 2})
        # Each two-occurrence batch contacts one; collapsing duplicate IDs would yield no contact.
        np.testing.assert_array_equal(draws["draws"]["dr_difference"], [-15, 30])
        np.testing.assert_array_equal(draws["draws"]["ipw_difference"], [-15, 30])
        self.assertEqual(draws["cap_violating_resamples"], 0)
        self.assertEqual(len(allocator.calls), 2)
        self.assertTrue(all(call[0] == spec_before and call[2] is cached for call in allocator.calls))
        self.assertEqual(spec, spec_before)
        control = bootstrap_policy({"id": "control", "kind": "control"}, features, outcomes, predictions, config,
                                   {"allocator": RecordingAllocator(), "indices": pool, "repetitions": 2})
        self.assertEqual(draws["resampling_sha256"], control["resampling_sha256"])
        np.testing.assert_array_equal(control["draws"]["dr_difference"], [0, 0])

    def test_percentile_ci_and_ipw_guardrails_use_paired_draws(self):
        features, outcomes, predictions, config = example()
        pool = np.asarray([[0, 0, 2, 2, 4, 4], [1, 1, 3, 3, 5, 5]], dtype=np.int32)
        result = evaluate_policy({"id": "rule", "kind": "rule"}, features, outcomes, predictions, config,
                                 {"allocator": RecordingAllocator(), "indices": pool, "repetitions": 2})
        np.testing.assert_allclose([result["primary"]["ci_lower"], result["primary"]["ci_upper"]],
                                   np.quantile([-15, 30], [0.025, 0.975]))
        self.assertEqual(result["guardrails"][0]["one_sided_confidence"], 0.975)
        self.assertAlmostEqual(result["guardrails"][0]["ci_upper"], float(np.quantile([-1.5, 0], 0.975)))
        self.assertEqual(result["rollout"]["setup_per_eligible_krw"], 10)
        self.assertEqual(result["exposure"]["contact_n"], 3)
        self.assertEqual(result["exposure"]["reservation_total_krw"], 60)

    def test_setup_is_recomputed_when_a_resampled_policy_makes_no_contacts(self):
        features, outcomes, predictions, config = example()
        predictions["profit"][1::2, 1] = -1
        pool = np.asarray([[0, 0, 2, 2, 4, 4], [1, 1, 3, 3, 5, 5]], dtype=np.int32)
        draws = bootstrap_policy({"id": "rule", "kind": "rule"}, features, outcomes, predictions, config,
                                 {"allocator": RecordingAllocator(), "indices": pool, "repetitions": 2})
        np.testing.assert_array_equal(draws["draws"]["rollout_net_profit"], [-250000, 0])

    def test_common_nuisance_is_separate_from_ranking_and_screening_is_not_approval(self):
        features, outcomes, predictions, config = example()
        predictions["evaluation_profit"][:, 1] = 100
        allocator = RecordingAllocator()
        result = evaluate_policy({"id": "rule", "kind": "rule"}, features, outcomes, predictions, config,
                                 {"allocator": allocator, "repetitions": 0, "guardrail_confidence": 1 - 0.05 / 16})
        expected = policy_scores([row["contribution_profit_60d_krw"] for row in outcomes],
                                 [row["arm"] for row in outcomes], [1, 0, 1, 0, 1, 0],
                                 predictions["evaluation_profit"], [1 / 3] * 3)
        self.assertEqual(result["primary"]["estimate"], float(expected["dr_difference"].mean()))
        self.assertEqual(result["rollout"]["decision"], "screening_only")
        self.assertEqual(result["primary"]["interval_method"], "normal_fixed_action_score_approximation")
        self.assertEqual(len(allocator.calls), 1)
        self.assertEqual(result["guardrails"][0]["one_sided_confidence"], 1 - 0.05 / 16)

    def test_rejects_invalid_propensities_immature_rows_and_cross_batch_samples(self):
        with self.assertRaises(ValueError):
            policy_scores([1], [0], [1], [[1, 2, 3]], [0, 0.5, 0.5])
        features, outcomes, predictions, config = example()
        outcomes[0]["is_profit_settled"] = False
        with self.assertRaises(ValueError):
            evaluate_policy({"kind": "control"}, features, outcomes, predictions, config,
                            {"allocator": RecordingAllocator(), "repetitions": 0})
        outcomes[0]["is_profit_settled"] = True
        with self.assertRaises(ValueError):
            bootstrap_policy({"kind": "control"}, features, outcomes, predictions, config,
                             {"allocator": RecordingAllocator(), "repetitions": 2,
                              "indices": np.asarray([[2, 1, 0, 3, 4, 5], [0, 1, 2, 3, 4, 5]])})

    def test_independent_cap_check_catches_an_allocator_overrun(self):
        features, outcomes, predictions, config = example()

        def invalid_allocator(*args, **kwargs):
            return {"actions": np.full(6, 2, dtype=np.int8), "caps_ok": True}

        result = evaluate_policy({"id": "invalid", "kind": "rule"}, features, outcomes, predictions, config,
                                 {"allocator": invalid_allocator, "repetitions": 2})
        self.assertFalse(result["exposure"]["caps_ok"])
        self.assertEqual(result["bootstrap"]["cap_violating_resamples"], 2)
        self.assertEqual(result["rollout"]["decision"], "hold")


if __name__ == "__main__":
    unittest.main()
