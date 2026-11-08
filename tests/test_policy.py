"""Hand-check policy budgets, tie rules, risk screening and bootstrap copies."""

import copy
import importlib.util
from pathlib import Path
import unittest

from crm_retention_lab.config import load_config

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
if HAS_NUMPY:
    import numpy as np
    from crm_retention_lab.policy import allocate_policy, default_policy_specs, prepare_policy_inputs

ROOT = Path(__file__).resolve().parents[1]


def _inputs(n=20):
    config = load_config(ROOT / "configs" / "smoke_v0_1.json", customers=max(n, 1))
    features = [{"customer_id": f"C{index:04d}", "assigned_at": "2025-10-01T09:00:00+09:00",
                 "first_pack_grams": 500, "tip_views_d0_d13": 0} for index in range(n)]
    predictions = {"profit": np.tile([100, 200, 500], (n, 1)).astype(float),
                   "unsubscribe": np.full((n, 3), 0.01), "refund": np.full((n, 3), 0.04),
                   "risk": np.linspace(0.1, 0.9, n)}
    return features, predictions, config


def _spec(kind="uplift", **changes):
    return {"id": "test", "kind": kind, "model": "hgb", "penalty_lambda": 0.0,
            "risk_filter": True, "seed": 123, **changes}


@unittest.skipUnless(HAS_NUMPY, "Install NumPy to run policy allocation tests")
class PolicyTests(unittest.TestCase):
    def test_default_candidate_family_is_finite_and_guardrail_screened(self):
        _, _, config = _inputs()
        specs = default_policy_specs(config)
        self.assertEqual(len(specs), 13)
        self.assertEqual(len({spec["id"] for spec in specs}), 13)
        self.assertTrue(all(spec["risk_filter"] for spec in specs))
        candidates = [spec for spec in specs if spec["kind"] == "uplift"]
        self.assertEqual({(spec["model"], spec["penalty_lambda"]) for spec in candidates},
                         {(model, penalty) for model in ("ridge", "hgb") for penalty in (0, 0.5, 1, 2)})

    def test_daily_contact_and_full_coupon_reservation_caps(self):
        features, predictions, config = _inputs(20)
        result = allocate_policy(features, predictions, _spec(), config)
        self.assertTrue(result["caps_ok"])
        self.assertEqual(result["summary"]["action_counts"], {"control": 14, "info": 5, "coupon": 1})
        self.assertEqual(result["summary"]["reserved_cost_krw"], 3020 + 5 * 20)
        self.assertEqual(result["batch_audit"][0]["contact_cap"], 6)
        self.assertEqual(result["batch_audit"][0]["reservation_cap_krw"], 6000)
        self.assertEqual(result["summary"]["predicted_incremental_profit_krw"], 400 + 5 * 100)

    def test_unaffordable_highest_action_can_fall_back_to_lower_scored_arm(self):
        features, predictions, config = _inputs(10)
        result = allocate_policy(features, predictions, _spec(), config)
        self.assertEqual(result["summary"]["action_counts"], {"control": 7, "info": 3, "coupon": 0})
        self.assertEqual(result["summary"]["reserved_cost_krw"], 60)

    def test_coupon_budget_does_not_use_expected_redemption_or_actual_spend(self):
        features, predictions, config = _inputs(10)
        for row in features:
            row.update(actual_campaign_spend_krw=0, coupon_used=False)
        predictions["expected_redemption"] = np.zeros(10)
        result = allocate_policy(features, predictions, _spec("random_coupon"), config)
        self.assertEqual(result["summary"]["contacts"], 0, "3000 reserved cannot pay a 3020 coupon offer")
        features, predictions, config = _inputs(11)
        result = allocate_policy(features, predictions, _spec("random_coupon"), config)
        self.assertEqual(result["summary"]["contacts"], 1)
        self.assertEqual(result["summary"]["reserved_cost_krw"], 3020)

    def test_zero_or_negative_predicted_gains_block_every_operating_policy(self):
        features, predictions, config = _inputs()
        predictions["profit"][:] = [100, 100, 90]
        for spec in default_policy_specs(config):
            with self.subTest(kind=spec["kind"]):
                result = allocate_policy(features, predictions, spec, config)
                self.assertFalse(np.any(result["actions"]))

    def test_penalty_requires_strictly_positive_adjusted_score(self):
        features, predictions, config = _inputs(20)
        predictions["profit"][:] = [0, 20, 3020]
        result = allocate_policy(features, predictions, _spec(penalty_lambda=1), config)
        self.assertFalse(np.any(result["actions"]))

    def test_risk_screen_uses_positive_parts_and_cannot_spend_negative_credits(self):
        features, predictions, config = _inputs(10)
        predictions["profit"][:] = [0, -1, -1]
        predictions["profit"][0, 1], predictions["profit"][1, 1] = 100, 50
        predictions["unsubscribe"][:] = 0.2
        predictions["unsubscribe"][0, 1], predictions["unsubscribe"][1, 1] = 0.1, 0.28
        result = allocate_policy(features, predictions, _spec(), config)
        self.assertEqual(result["actions"].tolist(), [1] + [0] * 9)
        self.assertEqual(result["summary"]["predicted_unsubscribe_positive_mass"], 0)
        self.assertAlmostEqual(result["summary"]["predicted_incremental_unsubscribe_mass"], -0.1)
        unfiltered = allocate_policy(features, predictions, _spec(risk_filter=False), config)
        self.assertEqual(np.count_nonzero(unfiltered["actions"]), 2)

    def test_refund_risk_and_daily_risk_limits_are_enforced(self):
        features, predictions, config = _inputs(20)
        for index in range(10, 20):
            features[index]["assigned_at"] = "2025-10-02T09:00:00+09:00"
        predictions["profit"][:] = [0, 100, -1]
        predictions["refund"][:] = [0, 0.06, 0]
        result = allocate_policy(features, predictions, _spec(), config)
        self.assertEqual(result["summary"]["contacts"], 2)
        self.assertTrue(all(row["contacts"] == 1 and row["refund_positive_mass"] <= 0.1
                            for row in result["batch_audit"]))

    def test_bootstrap_duplicates_are_distinct_occurrences_and_recompute_capacity(self):
        features, predictions, config = _inputs(4)
        prepared = prepare_policy_inputs(features, predictions, config)
        indices = np.array([0] * 10, dtype=np.int32)
        result = allocate_policy(None, None, _spec(), None, prepared=prepared, indices=indices)
        self.assertEqual(result["actions"].tolist(), [1, 1, 1] + [0] * 7)
        self.assertEqual(result["summary"]["n_eligible"], 10)
        self.assertEqual(result["batch_audit"][0]["contact_cap"], 3)
        self.assertEqual(result["batch_audit"][0]["reservation_cap_krw"], 3000)

    def test_exact_ties_use_customer_then_arm_and_ignore_input_order(self):
        features, predictions, config = _inputs(20)
        predictions["profit"][:] = [0, 100, 100]
        result = allocate_policy(features, predictions, _spec(), config)
        self.assertEqual(result["actions"].tolist(), [1] * 6 + [0] * 14)
        reverse = np.arange(19, -1, -1)
        changed = allocate_policy([features[index] for index in reverse],
                                  {key: value[reverse] for key, value in predictions.items()}, _spec(), config)
        np.testing.assert_array_equal(changed["actions"][reverse], result["actions"])

    def test_future_batches_cannot_change_previous_days_allocation(self):
        features, predictions, config = _inputs(20)
        baseline = allocate_policy(features, predictions, _spec(), config)["actions"]
        future, future_predictions, _ = _inputs(30)
        for row in future:
            row["assigned_at"] = "2026-03-01T09:00:00+09:00"
            row["customer_id"] = "A" + row["customer_id"]
        combined = {key: np.concatenate([predictions[key], future_predictions[key]]) for key in predictions}
        changed = allocate_policy(features + future, combined, _spec(), config)["actions"]
        np.testing.assert_array_equal(changed[:20], baseline)

    def test_random_baselines_are_stable_and_do_not_consume_global_rng(self):
        features, predictions, config = _inputs(50)
        np.random.seed(42)
        before = np.random.get_state()
        first = allocate_policy(features, predictions, _spec("random_info"), config)["actions"]
        np.testing.assert_array_equal(first, allocate_policy(features, predictions, _spec("random_info"), config)["actions"])
        after = np.random.get_state()
        self.assertEqual(before[0], after[0])
        np.testing.assert_array_equal(before[1], after[1])
        self.assertEqual(before[2:], after[2:])
        self.assertFalse(np.array_equal(first, allocate_policy(features, predictions, _spec("random_info", seed=124), config)["actions"]))

    def test_rule_and_high_nonrepurchase_risk_baselines(self):
        features, predictions, config = _inputs(40)
        features[0].update(first_pack_grams=200, tip_views_d0_d13=0)
        features[1].update(first_pack_grams=200, tip_views_d0_d13=1)
        result = allocate_policy(features, predictions, _spec("rule"), config)["actions"]
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], 0)
        self.assertTrue(all(action in (0, 2) for action in result[2:]))
        result = allocate_policy(features, predictions, _spec("risk_coupon"), config)["actions"]
        self.assertEqual(np.flatnonzero(result).tolist(), [37, 38, 39])

    def test_prepared_fast_mode_matches_full_mode_and_does_not_mutate_inputs(self):
        features, predictions, config = _inputs(30)
        before_features, before_profit = copy.deepcopy(features), predictions["profit"].copy()
        predictions["evaluation_profit"] = np.full((30, 3), 999999.0)
        prepared = prepare_policy_inputs(features, predictions, config)
        indices = np.array([3, 3, 7, 8, 10, 20, 21, 22, 23, 25, 29])
        full = allocate_policy(features, predictions, _spec(), config, indices=indices)
        fast = allocate_policy(None, None, _spec(), None, indices=indices, prepared=prepared, return_audit=False)
        np.testing.assert_array_equal(full["actions"], fast["actions"])
        self.assertEqual(set(fast), {"actions", "caps_ok"})
        self.assertEqual(features, before_features)
        np.testing.assert_array_equal(predictions["profit"], before_profit)
        self.assertTrue(predictions["profit"].flags.writeable)

    def test_observed_assignment_and_outcome_metadata_are_not_used(self):
        features, predictions, config = _inputs()
        baseline = allocate_policy(features, predictions, _spec(), config)["actions"]
        for row in features:
            row.update(arm="coupon", contribution_profit_60d_krw=10**9, opened_at="future", hidden_true_effect=10**6)
        np.testing.assert_array_equal(allocate_policy(features, predictions, _spec(), config)["actions"], baseline)

    def test_small_empty_invalid_and_out_of_range_inputs(self):
        features, predictions, config = _inputs(3)
        self.assertFalse(np.any(allocate_policy(features, predictions, _spec(), config)["actions"]))
        self.assertEqual(len(allocate_policy(features, predictions, _spec(), config, indices=[])["actions"]), 0)
        predictions["refund"][0, 1] = 1.1
        with self.assertRaisesRegex(ValueError, "no implicit clipping"):
            allocate_policy(features, predictions, _spec(), config)
        predictions["refund"][0, 1] = 0.01
        with self.assertRaisesRegex(ValueError, "valid source"):
            allocate_policy(features, predictions, _spec(), config, indices=[100])
        with self.assertRaisesRegex(ValueError, "fixed HGB"):
            allocate_policy(features, predictions, _spec("random_info", model="ridge"), config)
        features, predictions, config = _inputs(0)
        self.assertEqual(allocate_policy(features, predictions, _spec(), config)["summary"]["contacts"], 0)


if __name__ == "__main__":
    unittest.main()
