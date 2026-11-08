"""Leakage and statistical-contract tests for the frozen train-only learners."""

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import unittest
from unittest.mock import patch

from crm_retention_lab.marts import FEATURE_COLUMNS
from crm_retention_lab.uplift import (
    ARM_ORDER, DEFAULT_MODEL_SPEC, MODEL_NAMES, NUMERIC_COLUMNS,
    _model_spec, fit_uplift_models, predict_uplift_models,
)


HAS_ML = all(importlib.util.find_spec(name) is not None for name in ("numpy", "sklearn"))


def training_marts():
    features, outcomes = [], []
    for arm_index, arm in enumerate(ARM_ORDER):
        for index in range(12):
            assigned = datetime(2025, 1, 15, tzinfo=timezone.utc) + timedelta(days=index * 3)
            assigned_at = assigned.isoformat()
            freeze_at = (assigned + timedelta(days=90)).isoformat()
            common = {"customer_id": f"c-{arm}-{index}", "assignment_id": f"a-{arm}-{index}",
                      "arm": arm, "assigned_at": assigned_at}
            features.append({
                **common, "feature_cutoff_at": assigned_at, "feature_version": "v0.1",
                "first_pack_grams": 250 if index % 2 else 500,
                "first_quantity": 1 + index % 2, "first_paid_amount_krw": 28000 + 1000 * index,
                "first_discount_rate": 0.1 if index % 2 else 0.0,
                "delivery_lead_days": 2 + index % 3,
                "acquisition_channel": ("direct", "search", "social")[index % 3],
                "sessions_d0_d13": index % 7, "tip_views_d0_d13": index % 3,
                "cart_events_d0_d13": index % 2,
                "days_since_last_session": None if index % 3 == 0 else index % 5,
                "first_delivery_month": (assigned - timedelta(days=14)).month,
            })
            outcomes.append({
                **common, "is_outcome_mature": True, "is_profit_settled": True,
                "label_freeze_at": freeze_at, "settlement_end_at": freeze_at,
                "contribution_profit_60d_krw": 0 if index == 0 else -20000 + 500 * index - 600 * arm_index,
                "unsubscribe_60d": int(index % 4 == arm_index),
                "refund_customer_flag": int(index % 3 == arm_index),
                "repeat_paid_within_60d": index % 2,
            })
    return {
        "features": features, "outcomes": outcomes,
        "metadata": {
            "analysis_scope": "train", "feature_columns": list(FEATURE_COLUMNS),
            "as_of": "2025-10-01T00:00:00+00:00", "cutoff": "2025-10-01T00:00:00+00:00",
            "train_labels_available_by": "2025-10-01T00:00:00+00:00",
            "train_start_inclusive": "2025-01-15T00:00:00+00:00",
            "train_end_exclusive": "2025-07-01T00:00:00+00:00",
            "selected_assignments": len(features), "input_simulation_id": "unit-test-synthetic",
        },
        "eligibility_flow": {"assigned_total": len(features), "assigned_by_arm": {arm: 12 for arm in ARM_ORDER}},
    }


class TrainingContractTests(unittest.TestCase):
    """These guards run even when the optional modeling dependencies are absent."""

    def assert_rejected(self, mutate, text):
        marts = training_marts()
        mutate(marts)
        with self.assertRaisesRegex(ValueError, text):
            fit_uplift_models(marts)

    def test_validation_and_final_test_cannot_fit(self):
        for scope in ("validation", "final_test", "test", "all"):
            with self.subTest(scope=scope):
                self.assert_rejected(lambda m: m["metadata"].update(analysis_scope=scope), "only on train")

    def test_feature_allowlist_cannot_be_extended_or_reordered(self):
        self.assert_rejected(lambda m: m["metadata"]["feature_columns"].append("arm"), "allowlist")
        self.assert_rejected(lambda m: m["metadata"]["feature_columns"].reverse(), "allowlist")

    def test_partial_settlement_and_late_cutoff_rejected(self):
        self.assert_rejected(lambda m: m["outcomes"][0].update(is_profit_settled=False), "90-day")
        self.assert_rejected(lambda m: m["outcomes"][0].update(contribution_profit_60d_krw=None), "integer KRW")
        self.assert_rejected(lambda m: m["metadata"].update(as_of="2025-10-02T00:00:00+00:00"), "knowledge cutoff")
        self.assert_rejected(lambda m: m["metadata"].update(as_of="2025-06-30T00:00:00+00:00"), "roster")
        self.assert_rejected(lambda m: m["outcomes"][0].update(label_freeze_at="2025-04-14T00:00:00+00:00"), "90-day")

    def test_original_assignment_identity_and_denominator_required(self):
        self.assert_rejected(lambda m: m["outcomes"][0].update(arm="coupon"), "mismatch")
        self.assert_rejected(lambda m: m["outcomes"].pop(), "assignments must match")
        self.assert_rejected(lambda m: m["features"].append(copy.deepcopy(m["features"][0])), "Duplicate")
        self.assert_rejected(lambda m: m["eligibility_flow"].update(assigned_total=35), "denominators")
        self.assert_rejected(lambda m: m["eligibility_flow"]["assigned_by_arm"].update(control=11), "denominators")

    def test_assignment_and_feature_temporal_boundaries(self):
        def move_to_validation(marts):
            stamp = "2025-09-01T00:00:00+00:00"
            marts["features"][0].update(assigned_at=stamp, feature_cutoff_at=stamp)
            marts["outcomes"][0].update(assigned_at=stamp)
        self.assert_rejected(move_to_validation, "out-of-train")
        self.assert_rejected(lambda m: m["features"][0].update(feature_cutoff_at="2025-01-16T00:00:00+00:00"), "pre-assignment")

    def test_invalid_or_single_customer_arm_rejected(self):
        self.assert_rejected(lambda m: m["outcomes"][0].update(unsubscribe_60d=0.2), "binary")
        marts = training_marts()
        marts["features"] = marts["features"][:1] + marts["features"][12:]
        marts["outcomes"] = marts["outcomes"][:1] + marts["outcomes"][12:]
        marts["metadata"]["selected_assignments"] = len(marts["features"])
        marts["eligibility_flow"]["assigned_total"] = len(marts["features"])
        with self.assertRaisesRegex(ValueError, "at least two"):
            fit_uplift_models(marts)

    def test_only_two_frozen_candidates_and_seed_are_supported(self):
        self.assertEqual(_model_spec({"random_state": 123})["random_state"], 123)
        self.assertEqual(_model_spec(DEFAULT_MODEL_SPEC), DEFAULT_MODEL_SPEC)
        for spec in ({"features": ["arm"]}, {"ridge": {"alpha": 1}}, {"hgb": {"early_stopping": True}},
                     {"logistic": {"class_weight": "balanced"}}, {"random_state": True}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                _model_spec(spec)


@unittest.skipUnless(HAS_ML, "Optional numpy and scikit-learn dependencies are unavailable")
class UpliftModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.marts = training_marts()
        cls.bundle = fit_uplift_models(cls.marts)
        cls.predictions = predict_uplift_models(cls.bundle, cls.marts["features"])

    def test_shapes_probabilities_and_negative_profit_are_preserved(self):
        self.assertEqual(set(self.predictions), {"ridge", "hgb", "control_repeat_risk"})
        for family in MODEL_NAMES:
            for outcome, values in self.predictions[family].items():
                self.assertEqual(values.shape, (36, 3))
                self.assertTrue(self.np.isfinite(values).all())
                if outcome != "profit":
                    self.assertTrue(((values >= 0) & (values <= 1)).all())
            self.assertTrue((self.predictions[family]["profit"] < 0).any())
        # At this sample size each HGB arm is an unsplit leaf. Its value must be
        # the mean of the original negative AND zero labels, not a transformed target.
        for index, arm in enumerate(ARM_ORDER):
            mean = self.np.mean([r["contribution_profit_60d_krw"] for r in self.marts["outcomes"] if r["arm"] == arm])
            self.np.testing.assert_allclose(self.predictions["hgb"]["profit"][:, index], mean)
        self.assertEqual(self.predictions["control_repeat_risk"].shape, (36,))

    def test_manifest_has_only_fixed_features_and_frozen_model_parameters(self):
        manifest = self.bundle["manifest"]
        self.assertEqual(manifest["feature_columns"], list(FEATURE_COLUMNS))
        self.assertEqual(manifest["n_by_arm"], {arm: 12 for arm in ARM_ORDER})
        self.assertEqual(manifest["model_spec"], DEFAULT_MODEL_SPEC)
        self.assertFalse(manifest["validation_fit"])
        self.assertFalse(manifest["oracle_used"])
        self.assertFalse(manifest["final_test_used"])
        for family in MODEL_NAMES:
            names = manifest["training_feature_names"][family]
            self.assertFalse(any(any(forbidden in name for forbidden in ("customer_id", "assignment_id", "arm", "oracle")) for name in names))
            self.assertEqual(sum("missingindicator" in name for name in names), len(NUMERIC_COLUMNS))
        self.assertFalse(self.bundle["models"]["hgb"]["profit"][0].early_stopping)
        self.assertEqual(self.bundle["models"]["ridge"]["profit"][0].alpha, 100)
        json.dumps(manifest, allow_nan=False)

    def test_prediction_ignores_ids_assignment_arm_post_events_and_oracle(self):
        poisoned = copy.deepcopy(self.marts["features"])
        for row in poisoned:
            row.update(customer_id="another-id", assignment_id="another-assignment", arm="unknown",
                       assigned_at="2099-01-01T00:00:00+00:00", contribution_profit_60d_krw=10**12,
                       campaign_opened=True, oracle_true_uplift=10**15)
        result = predict_uplift_models(self.bundle, poisoned)
        for family in MODEL_NAMES:
            for outcome in self.predictions[family]:
                self.np.testing.assert_array_equal(result[family][outcome], self.predictions[family][outcome])

    def test_training_never_reads_extra_oracle_features_or_active_repeat_labels(self):
        poisoned = copy.deepcopy(self.marts)
        for row in poisoned["features"]:
            row.update(oracle_profit=10**14, post_campaign_clicked=True)
        for row in poisoned["outcomes"]:
            if row["arm"] != "control":
                row["repeat_paid_within_60d"] = 1 - row["repeat_paid_within_60d"]
        second = fit_uplift_models(poisoned)
        result = predict_uplift_models(second, poisoned["features"])
        for family in MODEL_NAMES:
            for outcome in self.predictions[family]:
                self.np.testing.assert_array_equal(result[family][outcome], self.predictions[family][outcome])
        self.np.testing.assert_array_equal(result["control_repeat_risk"], self.predictions["control_repeat_risk"])

    def test_unknown_future_month_channel_and_new_missing_values_never_refit(self):
        future = copy.deepcopy(self.marts["features"][:2])
        for row in future:
            row.update(first_delivery_month=11, acquisition_channel="previously-unseen", first_paid_amount_krw=None)
        processors = self.bundle["preprocessors"]
        old_categories = {name: [category.copy() for category in p.named_transformers_["categorical"].categories_]
                          for name, p in processors.items()}
        with patch.object(processors["ridge"], "fit", side_effect=AssertionError("Prediction refit preprocessing")), \
             patch.object(processors["hgb"], "fit", side_effect=AssertionError("Prediction refit preprocessing")):
            result = predict_uplift_models(self.bundle, future)
        for name, processor in processors.items():
            for before, after in zip(old_categories[name], processor.named_transformers_["categorical"].categories_):
                self.np.testing.assert_array_equal(before, after)
            self.assertTrue(self.np.isfinite(result[name]["profit"]).all())
        # The pooled train median must not move toward future/validation values.
        imputer = processors["ridge"].named_transformers_["numeric"].named_steps["impute_and_flag"].transformer_list[0][1]
        column = NUMERIC_COLUMNS.index("first_paid_amount_krw")
        self.assertEqual(imputer.statistics_[column], self.np.median([r["first_paid_amount_krw"] for r in self.marts["features"]]))

    def test_all_missing_train_column_and_single_class_outcomes_are_explicit(self):
        marts = training_marts()
        for row in marts["features"]:
            row["days_since_last_session"] = None
        for row in marts["outcomes"]:
            row.update(unsubscribe_60d=0, refund_customer_flag=1, repeat_paid_within_60d=0)
        bundle = fit_uplift_models(marts)
        future = copy.deepcopy(marts["features"][:2])
        future[0]["days_since_last_session"] = 3
        result = predict_uplift_models(bundle, future)
        for name in MODEL_NAMES:
            self.np.testing.assert_array_equal(result[name]["unsubscribe"], self.np.zeros((2, 3)))
            self.np.testing.assert_array_equal(result[name]["refund"], self.np.ones((2, 3)))
            self.assertTrue(self.np.isfinite(result[name]["profit"]).all())
            self.assertEqual(bundle["manifest"]["fit_status"][name]["control"]["unsubscribe"], "constant_probability_single_class")
        self.np.testing.assert_array_equal(result["control_repeat_risk"], self.np.zeros(2))

    def test_joblib_roundtrip_preserves_predictions(self):
        import joblib
        stream = io.BytesIO()
        joblib.dump(self.bundle, stream)
        stream.seek(0)
        restored = joblib.load(stream)
        result = predict_uplift_models(restored, self.marts["features"])
        for family in MODEL_NAMES:
            for outcome in self.predictions[family]:
                self.np.testing.assert_array_equal(result[family][outcome], self.predictions[family][outcome])
        self.np.testing.assert_array_equal(result["control_repeat_risk"], self.predictions["control_repeat_risk"])

    def test_empty_batches_and_invalid_feature_values(self):
        result = predict_uplift_models(self.bundle, [])
        self.assertEqual(result["control_repeat_risk"].shape, (0,))
        self.assertEqual(result["hgb"]["profit"].shape, (0, 3))
        for name, value in (("first_quantity", float("inf")), ("first_quantity", True),
                            ("first_quantity", "3"), ("first_delivery_month", 13), ("acquisition_channel", 8)):
            bad = copy.deepcopy(self.marts["features"][:1])
            bad[0][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                predict_uplift_models(self.bundle, bad)
        missing = copy.deepcopy(self.marts["features"][:1])
        del missing[0]["first_quantity"]
        with self.assertRaisesRegex(ValueError, "Missing required"):
            predict_uplift_models(self.bundle, missing)


if __name__ == "__main__":
    unittest.main()
