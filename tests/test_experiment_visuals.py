"""Verify ITT units, interval semantics, signed accounting and missingness."""

import copy
import importlib.util
import unittest

HAS_ANALYSIS = all(importlib.util.find_spec(name) is not None for name in ("plotly", "scipy"))
if HAS_ANALYSIS:
    from crm_retention_lab.experiment_visuals import FIGURE_IDS, create_experiment_figures


def _fixture():
    arms = ("control", "info", "coupon")
    means = {"control": 1000, "info": 1100, "coupon": 1150}
    counts = {"control": 10, "info": 20, "coupon": 30}
    contrast_arms = [("info", "control"), ("coupon", "control"), ("coupon", "info")]
    experiment = {
        "status": "ready",
        "metadata": {"analysis_scope": "train", "input_simulation_id": "sim-fixture",
                     "as_of": "2025-10-01T00:00:00+09:00", "confidence_level": 0.95},
        "population": {"total_assigned": 60, "total_mature": 60, "total_immature": 0},
        "arm_summaries": [{"arm": arm, "n": counts[arm],
                           "primary": {"mean": means[arm], "ci_lower": means[arm] - 40,
                                       "ci_upper": means[arm] + 70, "sum": means[arm] * counts[arm]}}
                          for arm in arms],
        "primary_comparisons": [{"comparison": f"{t}_vs_{r}", "treatment_arm": t, "reference_arm": r,
                                 "estimate": means[t] - means[r], "ci_lower": means[t] - means[r] - 120,
                                 "ci_upper": means[t] - means[r] + 150,
                                 "p_value_holm": 0.18, "n_treatment": counts[t], "n_reference": counts[r],
                                 "status": "ok"} for t, r in contrast_arms],
        "guardrails": [{"metric": metric, "comparison": f"{arm}_vs_control", "treatment_arm": arm,
                        "reference_arm": "control", "estimate": 0.002, "ci_upper": 0.008,
                        "tolerance": tolerance, "n_treatment": counts[arm], "n_reference": counts["control"],
                        "one_sided_confidence": 0.9875, "assessment": "not_established", "status": "ok"}
                       for metric, tolerance in (("unsubscribe_60d", 0.005), ("refund_customer_flag", 0.01))
                       for arm in ("info", "coupon")],
    }
    components = ["net_item_revenue", "customer_shipping_charge", "refund", "cogs", "cogs_recovery",
                  "outbound_shipping", "fulfillment", "payment_fee", "return_handling", "send_cost"]
    differences = dict(zip(components, [200, 5, -20, -60, 0, -30, -20, -10, -15, 0]))
    info = dict(zip(components, [1500, 100, -40, -200, 0, -100, -60, -40, -40, -20]))
    coupon = {key: info[key] + differences[key] for key in components}
    finance_arms = [{"arm": arm, "n": counts[arm], "components_mean_krw": values,
                     "components_total_krw": {key: value * counts[arm] for key, value in values.items()},
                     "mean_profit_krw": sum(values.values())} for arm, values in (("info", info), ("coupon", coupon))]
    checks = {
        "finance_reconciliation": {"status": "passed", "components_order": components, "arms": finance_arms,
                                   "comparisons": [{"contrast": "coupon_vs_info", "components_mean_difference_krw": differences,
                                                    "profit_mean_difference_krw": 50}]},
        "balance": {"reference_threshold": 0.1, "features": [
            {"feature": "first_pack_grams", "max_abs_smd": 0.04, "undefined_comparisons": [],
             "comparisons": [{"contrast": f"{t}_vs_{r}", "smd": value, "level": 500}
                             for (t, r), value in zip(contrast_arms, (0.03, -0.04, 0.01))]},
            {"feature": "days_since_last_session__missing", "max_abs_smd": None,
             "undefined_comparisons": ["info_vs_control"], "comparisons": []},
        ]},
    }
    return experiment, checks


@unittest.skipUnless(HAS_ANALYSIS, "Install analysis dependencies for experiment visual tests")
class ExperimentVisualTests(unittest.TestCase):
    def test_figure_ids_metadata_and_input_immutability(self):
        experiment, checks = _fixture()
        before = copy.deepcopy((experiment, checks))
        figures = create_experiment_figures(experiment, checks)
        self.assertEqual(tuple(figures), FIGURE_IDS)
        self.assertEqual((experiment, checks), before)
        for figure in figures.values():
            self.assertEqual(figure.layout.meta["analysis_scope"], "train")
            self.assertTrue(figure.layout.meta["synthetic"])
            captions = " ".join(annotation.text for annotation in figure.layout.annotations)
            self.assertIn("2025-10-01", captions)
            self.assertIn("All ITT assignments: 60", captions)

    def test_arm_plot_uses_means_not_unequal_arm_totals(self):
        experiment, checks = _fixture()
        figure = create_experiment_figures(experiment, checks)["arm_profit"]
        self.assertEqual([trace.x[0] for trace in figure.data], [1000, 1100, 1150])
        self.assertEqual([trace.customdata[0][0] for trace in figure.data], [10, 20, 30])
        self.assertEqual(figure.data[1].error_x.array[0], 70)
        self.assertEqual(figure.data[1].error_x.arrayminus[0], 40)

    def test_effect_plot_preserves_individual_intervals_and_holm_p(self):
        figure = create_experiment_figures(*_fixture())["profit_effects"]
        self.assertEqual([trace.x[0] for trace in figure.data], [100, 150, 50])
        self.assertEqual(figure.data[2].error_x.array[0], 150)
        self.assertEqual(figure.data[2].error_x.arrayminus[0], 120)
        self.assertEqual(figure.data[0].customdata[0][2], "0.18")
        self.assertTrue(any(shape.x0 == shape.x1 == 0 for shape in figure.layout.shapes))

    def test_missing_interval_is_not_rendered_as_zero_uncertainty(self):
        experiment, checks = _fixture()
        experiment["primary_comparisons"][0].update(ci_lower=None, ci_upper=None, p_value_holm=None)
        experiment["arm_summaries"][0]["primary"].update(mean=0, ci_lower=None, ci_upper=None)
        figures = create_experiment_figures(experiment, checks)
        self.assertEqual(figures["arm_profit"].data[0].x[0], 0)
        self.assertIsNone(figures["arm_profit"].data[0].error_x.array)
        self.assertIsNone(figures["profit_effects"].data[0].error_x.array)

    def test_waterfall_uses_signed_per_customer_differences_and_excludes_second_discount(self):
        experiment, checks = _fixture()
        # Gross totals intentionally differ greatly because the two arm Ns differ.
        for arm in checks["finance_reconciliation"]["arms"]:
            arm["components_total_krw"]["net_item_revenue"] = 999999999 if arm["arm"] == "coupon" else 0
        trace = create_experiment_figures(experiment, checks)["coupon_info_waterfall"].data[0]
        self.assertEqual(list(trace.x[:-1]), [200, 5, -20, -60, 0, -30, -20, -10, -15, 0])
        self.assertEqual(trace.measure[-1], "total")
        self.assertEqual(trace.customdata[-1][2], 50)
        self.assertEqual(len(trace.x), 11)
        self.assertFalse(any("Coupon discount" in label for label in trace.y))

    def test_unreconciled_finance_cannot_produce_a_waterfall(self):
        experiment, checks = _fixture()
        checks["finance_reconciliation"]["status"] = "mismatch"
        self.assertFalse(create_experiment_figures(experiment, checks)["coupon_info_waterfall"].data)
        checks["finance_reconciliation"]["status"] = "passed"
        checks["finance_reconciliation"]["comparisons"][0]["profit_mean_difference_krw"] = 999
        with self.assertRaisesRegex(ValueError, "reconcile"):
            create_experiment_figures(experiment, checks)

    def test_safety_plot_uses_percentage_points_and_only_upper_bound(self):
        figure = create_experiment_figures(*_fixture())["safety_effects"]
        self.assertEqual(len(figure.data), 4)
        for trace in figure.data:
            self.assertAlmostEqual(trace.x[0], 0.2)
            self.assertAlmostEqual(trace.error_x.array[0], 0.6)
            self.assertEqual(trace.error_x.arrayminus[0], 0)
            self.assertAlmostEqual(trace.customdata[0][4], 98.75)
        thresholds = {shape.x0 for shape in figure.layout.shapes if shape.line.dash == "dash"}
        self.assertEqual(thresholds, {0.5, 1.0})
        self.assertEqual({trace.xaxis for trace in figure.data}, {"x", "x2"})

    def test_balance_preserves_maximum_and_undefined_smd(self):
        figure = create_experiment_figures(*_fixture())["balance"]
        self.assertEqual(len(figure.data), 1)
        self.assertEqual(figure.data[0].x[0], 0.04)
        self.assertIn("Category 500", figure.data[0].hovertemplate)
        self.assertTrue(any(annotation.text == "NA · Undefined" for annotation in figure.layout.annotations))
        self.assertTrue(any(shape.x0 == 0.1 for shape in figure.layout.shapes))

    def test_not_ready_does_not_plot_mature_subset_effects(self):
        experiment, checks = _fixture()
        experiment["status"] = "not_ready"
        experiment["population"].update(total_mature=45, total_immature=15)
        # Even stale estimates in a not-ready object must never be displayed.
        figures = create_experiment_figures(experiment, checks)
        for name in FIGURE_IDS[:-1]:
            self.assertFalse(figures[name].data, name)
        self.assertTrue(figures["balance"].data)

    def test_holdout_input_is_rejected(self):
        experiment, checks = _fixture()
        experiment["metadata"]["analysis_scope"] = "final_holdout"
        with self.assertRaisesRegex(ValueError, "training"):
            create_experiment_figures(experiment, checks)


if __name__ == "__main__":
    unittest.main()
