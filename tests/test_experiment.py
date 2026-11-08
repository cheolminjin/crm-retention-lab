"""Numerical references, ITT denominators and no-partial-readout safeguards."""

import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, parse_ts
from crm_retention_lab.experiment import (
    PRIMARY, holm_adjust, newcombe_interval, summarize_experiment, welch_comparison,
)


ROOT = Path(__file__).resolve().parents[1]
HAS_SCIPY = importlib.util.find_spec("scipy") is not None


def config_fixture():
    return json.loads((ROOT / "configs/design_v0_1.json").read_text(encoding="utf-8"))


def mart_fixture(arm_profits=None):
    arm_profits = arm_profits or {"control": [-20, 0, 200, 100], "info": [0, 120, 350, 150], "coupon": [-20, 80, 280, 110]}
    features, outcomes = [], []
    assigned = "2025-01-20T09:00:00+09:00"
    freeze = iso(parse_ts(assigned) + timedelta(days=90))
    for arm, profits in arm_profits.items():
        for index, profit in enumerate(profits):
            common = {"assignment_id": f"a-{arm}-{index}", "customer_id": f"c-{arm}-{index}", "arm": arm, "assigned_at": assigned}
            features.append(dict(common))
            outcomes.append({
                **common, "is_outcome_mature": True, "is_profit_settled": True,
                "label_freeze_at": freeze, PRIMARY: profit,
                "repeat_paid_within_60d": int(profit > 0), "order_count_60d": index % 3,
                "unsubscribe_60d": int(arm == "coupon" and index == 0),
                "refund_customer_flag": int(arm == "coupon" and index == 2),
            })
    return {
        "features": features, "outcomes": outcomes,
        "eligibility_flow": {"assigned_total": len(features)},
        "metadata": {"analysis_scope": "train", "as_of": "2025-10-01T00:00:00+09:00",
                     "cutoff": "2025-10-01T00:00:00+09:00", "input_simulation_id": "sim-fixture",
                     "selected_assignments": len(features)},
    }


class ExperimentGuardAndScoreTests(unittest.TestCase):
    def test_holm_known_example_retains_order_and_full_family(self):
        self.assertEqual(holm_adjust([0.03, 0.01, 0.04]), [0.06, 0.03, 0.06])
        self.assertEqual(holm_adjust([0.01, None, 0.02]), [0.03, None, 0.04])
        self.assertEqual(holm_adjust([0.9, 0.8, 0.95]), [1.0, 1.0, 1.0])
        self.assertEqual(holm_adjust([]), [])
        with self.assertRaises(ValueError):
            holm_adjust([float("nan")])

    def test_newcombe_matches_published_example_used_by_statsmodels(self):
        # Fagerland et al. (2015), reproduced in the official statsmodels test:
        # https://github.com/statsmodels/statsmodels/blob/main/statsmodels/stats/tests/test_proportion.py
        # test_confint_2indep: 7/34 versus 1/34; published limits .019, .340.
        estimate, lower, upper = newcombe_interval(7, 34, 1, 34)
        self.assertAlmostEqual(estimate, 6 / 34)
        self.assertAlmostEqual(lower, 0.019, delta=0.005)
        self.assertAlmostEqual(upper, 0.340, delta=0.005)
        reverse = newcombe_interval(1, 34, 7, 34)
        self.assertAlmostEqual(reverse[0], -estimate)
        self.assertAlmostEqual(reverse[1], -upper)
        self.assertAlmostEqual(reverse[2], -lower)

    def test_binary_score_boundaries_never_claim_zero_uncertainty(self):
        estimate, lower, upper = newcombe_interval(0, 100, 0, 100)
        self.assertEqual(estimate, 0)
        self.assertLess(lower, 0)
        self.assertGreater(upper, 0)
        full = newcombe_interval(100, 100, 0, 100)
        self.assertEqual(full[0], 1)
        self.assertGreater(full[1], 0.9)
        self.assertLessEqual(full[2], 1)
        self.assertEqual(newcombe_interval(0, 0, 2, 10), (None, None, None))
        for args in ((-1, 10, 0, 10), (11, 10, 0, 10), (1.5, 10, 0, 10)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                newcombe_interval(*args)

    def test_one_immature_customer_blocks_every_effect_without_dropping_anyone(self):
        marts = mart_fixture()
        marts["outcomes"][-1].update(is_profit_settled=False, label_freeze_at=None, **{PRIMARY: None})
        result = summarize_experiment(marts, config_fixture())
        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["population"]["total_assigned"], 12)
        self.assertEqual(result["population"]["total_mature"], 11)
        self.assertEqual(result["population"]["by_arm"]["coupon"], {"n_assigned": 4, "n_mature": 3, "n_immature": 1})
        for key in ("arm_summaries", "primary_comparisons", "secondary_comparisons", "guardrails"):
            self.assertEqual(result[key], [])

    def test_early_snapshot_cannot_estimate_only_the_already_seen_training_roster(self):
        marts = mart_fixture()
        marts["metadata"]["as_of"] = "2025-06-01T00:00:00+09:00"
        result = summarize_experiment(marts, config_fixture())
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("training_roster_not_complete", result["readiness_reasons"])
        self.assertEqual(result["population"]["total_mature"], 12)

    def test_empty_arm_reports_readiness_without_crashing_or_estimating(self):
        marts = mart_fixture({"control": [0, 10], "info": [0, 20], "coupon": []})
        result = summarize_experiment(marts, config_fixture())
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("empty_randomized_arm", result["readiness_reasons"])
        self.assertEqual(result["population"]["by_arm"]["coupon"]["n_assigned"], 0)
        self.assertEqual(result["primary_comparisons"], [])

    def test_scope_duplicate_join_and_denominator_mismatch_are_rejected(self):
        cases = []
        case = mart_fixture(); case["metadata"]["analysis_scope"] = "final_test"; cases.append(case)
        case = mart_fixture(); case["outcomes"].append(dict(case["outcomes"][0])); cases.append(case)
        case = mart_fixture(); case["outcomes"][0]["arm"] = "info"; cases.append(case)
        case = mart_fixture(); case["features"].pop(); case["outcomes"].pop(); cases.append(case)
        case = mart_fixture(); case["metadata"]["as_of"] = "2026-01-01T00:00:00+09:00"; cases.append(case)
        case = mart_fixture(); case["outcomes"][0]["label_freeze_at"] = "2025-03-01T00:00:00+09:00"; cases.append(case)
        case = mart_fixture(); case["eligibility_flow"]["assigned_by_arm"] = {"control": 3, "info": 5, "coupon": 4}; cases.append(case)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                summarize_experiment(case, config_fixture())

    def test_undefined_variance_and_single_customer_are_explicit_json_null(self):
        zero = welch_comparison([1, 1], [0, 0])
        self.assertEqual(zero["estimate"], 1)
        self.assertEqual(zero["standard_error"], 0)
        self.assertEqual(zero["status"], "undefined_zero_standard_error")
        self.assertIsNone(zero["p_value"])
        self.assertIsNone(zero["ci_lower"])
        one = welch_comparison([4], [1, 2])
        self.assertEqual(one["estimate"], 2.5)
        self.assertEqual(one["status"], "insufficient_sample")
        json.dumps([zero, one, welch_comparison([], [1])], allow_nan=False)
        single = summarize_experiment(mart_fixture({"control": [0], "info": [1], "coupon": [2]}), config_fixture())
        self.assertEqual(single["status"], "ready")
        self.assertTrue(all(row["p_value_holm"] is None for row in single["primary_comparisons"]))
        json.dumps(single, allow_nan=False)


@unittest.skipUnless(HAS_SCIPY, "Optional SciPy is required for Student-t inference references")
class ExperimentInferenceTests(unittest.TestCase):
    def test_welch_matches_scipy_ttest_and_confidence_interval(self):
        from scipy.stats import ttest_ind

        samples = [([1., 2., 3.], [1.1, 2.9, 4.2]),
                   ([-20, 0, 10, 40, 1000], [-20, -20, 0, 10]),
                   ([0, 0, 0, 0], [1, 2, 3])]
        for treatment, reference in samples:
            with self.subTest(treatment=treatment, reference=reference):
                actual = welch_comparison(treatment, reference)
                expected = ttest_ind(treatment, reference, equal_var=False)
                interval = expected.confidence_interval(0.95)
                self.assertAlmostEqual(actual["t_statistic"], expected.statistic, places=12)
                self.assertAlmostEqual(actual["p_value"], expected.pvalue, places=12)
                self.assertAlmostEqual(actual["degrees_of_freedom"], expected.df, places=12)
                self.assertAlmostEqual(actual["ci_lower"], interval.low, places=10)
                self.assertAlmostEqual(actual["ci_upper"], interval.high, places=10)
        # Published R t.test reference retained in SciPy's own regression tests.
        known = welch_comparison([1., 2., 3.], [1.1, 2.9, 4.2])
        self.assertAlmostEqual(known["p_value"], 0.53619490753126686, places=12)
        self.assertAlmostEqual(known["t_statistic"], -0.686495127355726265, places=12)

    def test_guardrail_one_sided_zero_event_bound_matches_independent_scipy_wilson(self):
        from scipy.stats import binomtest

        difference, lower, upper = newcombe_interval(0, 100, 0, 100, 0.9875, one_sided=True)
        expected = binomtest(0, 100).proportion_ci(confidence_level=0.975, method="wilson")
        self.assertEqual(difference, 0)
        self.assertIsNone(lower)
        self.assertAlmostEqual(upper, expected.high, places=12)

    def test_itt_preserves_all_assigned_rows_and_negative_nonbuyer_costs(self):
        marts = mart_fixture()
        before = copy.deepcopy(marts)
        result = summarize_experiment(marts, config_fixture())
        self.assertEqual(marts, before)
        self.assertEqual(result["status"], "ready")
        arms = {row["arm"]: row for row in result["arm_summaries"]}
        self.assertEqual(arms["control"]["primary"]["sum"], 280)
        self.assertEqual(arms["info"]["primary"]["sum"], 620)
        self.assertEqual(arms["coupon"]["primary"]["sum"], 450)
        self.assertTrue(all(row["n"] == 4 for row in arms.values()))
        contrasts = {row["comparison"]: row for row in result["primary_comparisons"]}
        self.assertEqual(contrasts["info_vs_control"]["estimate"], 85)
        self.assertEqual(contrasts["coupon_vs_control"]["estimate"], 42.5)
        self.assertEqual(contrasts["coupon_vs_info"]["estimate"], -42.5)
        self.assertEqual(len(result["secondary_comparisons"]), 12)
        self.assertEqual(len(result["guardrails"]), 4)
        self.assertFalse(result["methods"]["policy_approval"])
        json.dumps(result, allow_nan=False)

    def test_primary_totals_remain_exact_integer_krw(self):
        large = 2 ** 54
        marts = mart_fixture({"control": [large, large + 4, large + 8], "info": [0, 4, 8], "coupon": [1, 5, 9]})
        result = summarize_experiment(marts, config_fixture())
        total = result["arm_summaries"][0]["primary"]["sum"]
        self.assertIs(type(total), int)
        self.assertEqual(total, 3 * large + 12)

    def test_guardrails_use_four_comparison_family_and_fraction_units(self):
        cfg = config_fixture()
        self.assertEqual(cfg["inference"]["guardrail_bonferroni_individual_one_sided_confidence"], 0.975)
        result = summarize_experiment(mart_fixture(), cfg)
        for guardrail in result["guardrails"]:
            self.assertEqual(guardrail["family_size"], 4)
            self.assertEqual(guardrail["one_sided_confidence"], 0.9875)
            self.assertEqual(guardrail["familywise_alpha"], 0.05)
            self.assertEqual(guardrail["tolerance"], 0.005 if guardrail["metric"] == "unsubscribe_60d" else 0.01)
            # Four-person samples cannot establish a narrow no-harm margin.
            self.assertEqual(guardrail["assessment"], "not_established")
        self.assertTrue(all(row["p_value_holm"] >= row["p_value"] for row in result["primary_comparisons"]))

    def test_validated_rare_event_upper_can_establish_tolerance_without_claiming_policy_approval(self):
        marts = mart_fixture({arm: [0, 1] * 1000 for arm in ("control", "info", "coupon")})
        for outcome in marts["outcomes"]:
            outcome["unsubscribe_60d"] = 0
            outcome["refund_customer_flag"] = 0
        result = summarize_experiment(marts, config_fixture())
        self.assertTrue(all(row["assessment"] == "within_tolerance" for row in result["guardrails"]))
        self.assertFalse(result["methods"]["policy_approval"])

    def test_invalid_settled_outcomes_are_not_silently_dropped(self):
        for metric, value in ((PRIMARY, None), (PRIMARY, float("nan")), ("repeat_paid_within_60d", 2), ("order_count_60d", -1)):
            marts = mart_fixture()
            marts["outcomes"][0][metric] = value
            with self.subTest(metric=metric, value=value), self.assertRaises(ValueError):
                summarize_experiment(marts, config_fixture())


if __name__ == "__main__":
    unittest.main()
