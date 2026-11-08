"""Ensure policy plots keep selection/final inference and budget units apart."""

import copy
import importlib.util
import unittest

HAS_PLOTLY = importlib.util.find_spec("plotly") is not None
if HAS_PLOTLY:
    from crm_retention_lab.policy_visuals import FIGURE_IDS, create_policy_figures


def _fixture():
    chosen = {"id": "uplift_ridge_lambda_0p5", "kind": "uplift", "model": "ridge", "penalty_lambda": 0.5}
    validation = []
    for spec, point, low, eligible in ((chosen, 200, 100, True),
                                      ({"id": "uplift_hgb_lambda_0p5", "kind": "uplift", "model": "hgb", "penalty_lambda": 0.5}, 300, 150, False)):
        validation.append({"policy_id": spec["id"], "policy_spec": spec, "n": 100,
                           "primary": {"estimate": point, "ci_lower": low, "ci_upper": point+100},
                           "screen": {"profit_pass": True, "harm_pass": eligible, "eligible": eligible}})
    final = []
    for spec, point, low, high, ipw, counts in (
        ({"id": "control", "kind": "control", "model": "hgb", "penalty_lambda": 0}, 0, 0, 0, 0, {"control": 100, "info": 0, "coupon": 0}),
        (chosen, 200, 50, 350, 180, {"control": 70, "info": 25, "coupon": 5}),
        ({"id": "random_info", "kind": "random_info", "model": "hgb", "penalty_lambda": 0}, 70, -20, 160, 90, {"control": 70, "info": 30, "coupon": 0}),
    ):
        final.append({
            "policy_id": spec["id"], "policy_spec": spec, "n": 100,
            "primary": {"estimate": point, "ci_lower": low, "ci_upper": high},
            "ipw_check": {"estimate": ipw}, "bootstrap": {"repetitions": 2000},
            "exposure": {"counts": counts, "contact_n": counts["info"]+counts["coupon"],
                         "reservation_total_krw": counts["info"]*20+counts["coupon"]*3020,
                         "budget_cap_total_krw": 30000, "contact_cap_total": 30},
            "guardrails": [{"metric": metric, "estimate": estimate, "ci_upper": upper,
                            "tolerance": tolerance, "one_sided_confidence": 0.975}
                           for metric, estimate, upper, tolerance in (("unsubscribe_60d", 0.001, 0.004, 0.005),
                                                                      ("refund_customer_flag", 0.003, 0.008, 0.01))],
            "segments": [{"first_pack_grams": 200, "n": 40, "control": 25, "info": 15, "coupon": 0},
                         {"first_pack_grams": 500, "n": 30, "control": 20, "info": 8, "coupon": 2},
                         {"first_pack_grams": 1000, "n": 30, "control": 25, "info": 2, "coupon": 3}],
        })
    return {"metadata": {"synthetic": True, "splits": {
                "train": {"as_of": "2025-10-01T00:00:00+09:00", "input_simulation_id": "sim-train"},
                "validation": {"as_of": "2026-03-01T00:00:00+09:00", "input_simulation_id": "sim-validation"},
                "final_test": {"as_of": "2026-08-01T00:00:00+09:00", "input_simulation_id": "sim-final"}}},
            "selection": {"chosen_policy": chosen}, "validation": validation, "final": final,
            "constraints": {"fixed_setup_cost_krw_per_rollout": 100000, "rollout_eligible_customers": 10000}}


@unittest.skipUnless(HAS_PLOTLY, "Install Plotly to run policy visual tests")
class PolicyVisualTests(unittest.TestCase):
    def test_five_figures_separate_validation_and_final_snapshot(self):
        data = _fixture()
        before = copy.deepcopy(data)
        figures = create_policy_figures(data)
        self.assertEqual(tuple(figures), FIGURE_IDS)
        self.assertEqual(data, before)
        self.assertEqual(figures["policy_validation"].layout.meta["analysis_scope"], "validation")
        for key in FIGURE_IDS[1:]:
            self.assertEqual(figures[key].layout.meta["analysis_scope"], "final_test")
            self.assertIn("sim-final", figures[key].layout.annotations[0].text)
        self.assertIn("2026-03-01", figures["policy_validation"].layout.annotations[0].text)

    def test_validation_is_selection_only_lower_bound_not_final_interval(self):
        figure = create_policy_figures(_fixture())["policy_validation"]
        self.assertEqual(figure.data[0].x[0], 200)
        self.assertEqual(figure.data[0].error_x.arrayminus[0], 100)
        self.assertEqual(figure.data[0].error_x.array[0], 0)
        self.assertTrue(any(shape.x0 == 10 for shape in figure.layout.shapes))

    def test_final_profit_shows_paired_dr_interval_and_separate_ipw_point(self):
        figure = create_policy_figures(_fixture())["policy_profit"]
        self.assertEqual(figure.data[0].x[0], 200)
        self.assertEqual(figure.data[0].error_x.arrayminus[0], 150)
        self.assertEqual(figure.data[0].error_x.array[0], 150)
        self.assertEqual(figure.data[-1].x[0], 180)
        self.assertEqual(figure.data[0].customdata[0][2], 2000)

    def test_allocation_uses_full_reservation_and_actual_floor_cap_denominators(self):
        figure = create_policy_figures(_fixture())["policy_allocation"]
        self.assertEqual([trace.x[0] for trace in figure.data[:3]], [0.7, 0.25, 0.05])
        self.assertAlmostEqual(figure.data[3].x[0], 15600/30000)
        self.assertEqual(figure.data[4].x[0], 1)

    def test_selected_policy_guardrails_convert_fraction_to_percentage_points(self):
        figure = create_policy_figures(_fixture())["policy_guardrails"]
        self.assertAlmostEqual(figure.data[0].x[0], 0.1)
        self.assertAlmostEqual(figure.data[0].error_x.array[0], 0.3)
        self.assertEqual(figure.data[0].error_x.arrayminus[0], 0)
        self.assertEqual(figure.data[1].x[0], 0.5)
        self.assertEqual(figure.data[3].x[0], 1)

    def test_segment_fractions_are_within_group_and_zero_denominators_are_missing(self):
        data = _fixture()
        chosen = next(row for row in data["final"] if row["policy_id"] == data["selection"]["chosen_policy"]["id"])
        chosen["segments"][2].update(n=0, control=0, info=0, coupon=0)
        figure = create_policy_figures(data)["policy_segments"]
        self.assertEqual(figure.data[0].x[0], 25/40)
        self.assertIsNone(figure.data[0].x[2])
        self.assertTrue(any("distinct from actual sending performance" in note.text for note in figure.layout.annotations))

    def test_duplicate_policies_and_missing_locked_policy_are_rejected(self):
        data = _fixture()
        data["final"].append(copy.deepcopy(data["final"][0]))
        with self.assertRaisesRegex(ValueError, "deduplicated"):
            create_policy_figures(data)
        data = _fixture()
        data["selection"]["chosen_policy"]["id"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing"):
            create_policy_figures(data)


if __name__ == "__main__":
    unittest.main()
