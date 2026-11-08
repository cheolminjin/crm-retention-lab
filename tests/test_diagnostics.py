"""Independent numerical examples and analysis-scope checks for diagnostics."""

import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, load_config, parse_ts
from crm_retention_lab.diagnostics import kaplan_meier_curve, summarize_diagnostics, wilson_interval


ROOT = Path(__file__).resolve().parents[1]


def _example_marts():
    features, outcomes = [], []
    cases = [
        ("one", "2025-01-20", "control", 200, 7.0, True, True, 1),
        ("two", "2025-01-20", "control", 500, 60.0, False, True, 0),
        ("three", "2025-03-01", "control", 1000, 20.0, True, True, 0),
        ("four", "2025-03-31", "control", 200, 60.0, False, False, 1),
        ("active", "2025-01-20", "coupon", 200, 1.0, True, True, 1),
    ]
    for customer, date, arm, grams, duration, event, settled, tips in cases:
        assigned = date + "T09:00:00+09:00"
        common = {"customer_id": customer, "assignment_id": "a-" + customer,
                  "assigned_at": assigned, "arm": arm}
        features.append({**common, "first_pack_grams": grams, "tip_views_d0_d13": tips})
        outcomes.append({
            **common, "label_freeze_at": iso(parse_ts(assigned) + timedelta(days=90)) if settled else None,
            "is_outcome_mature": True, "is_profit_settled": settled,
            "repeat_paid_within_60d": int(event) if settled else None,
            "days_to_first_repeat_paid": duration, "repeat_event_observed": event,
            "contribution_profit_60d_krw": 999999 if arm == "coupon" else None,
        })
    return {
        "features": features, "outcomes": outcomes,
        "eligibility_flow": {"assigned_total": 5, "exclusion_reasons_overlap": True},
        "metadata": {"analysis_scope": "train", "as_of": "2025-06-15T00:00:00+09:00",
                     "cutoff": "2025-06-15T00:00:00+09:00", "input_simulation_id": "sim-test"},
        "oracle": [{"hidden_consumption_speed": 999}],
    }


class DiagnosticsTests(unittest.TestCase):
    def config(self):
        return load_config(ROOT / "configs" / "smoke_v0_1.json")

    def test_km_hand_calculation_with_tied_event_and_censor(self):
        curve = kaplan_meier_curve([1, 2, 2, 4, 5], [True, True, False, True, False])
        by_day = {row["day"]: row for row in curve["points"]}
        self.assertEqual(by_day[0]["survival"], 1)
        self.assertAlmostEqual(by_day[1]["survival"], 4 / 5)
        # At t=2 the event sees four at risk, including the simultaneous censor.
        self.assertEqual(by_day[2]["at_risk"], 4)
        self.assertAlmostEqual(by_day[2]["survival"], 3 / 5)
        self.assertEqual((by_day[2]["events"], by_day[2]["censored"]), (1, 1))
        self.assertAlmostEqual(by_day[4]["survival"], 3 / 10)
        self.assertEqual(curve["median_repurchase_days"], 4)
        self.assertEqual(curve["censor_marks"][0]["n"], 1)
        self.assertAlmostEqual(curve["censor_marks"][0]["cumulative_repurchase"], 0.4)
        self.assertIsNone(by_day[6]["survival"])
        for point in curve["points"]:
            if point["survival"] is not None:
                self.assertLessEqual(point["survival_ci_lower"], point["survival"])
                self.assertGreaterEqual(point["survival_ci_upper"], point["survival"])
                self.assertAlmostEqual(point["cumulative_repurchase_ci_lower"], 1 - point["survival_ci_upper"])

    def test_km_no_events_all_events_empty_and_at_risk_endpoints(self):
        no_events = kaplan_meier_curve([14, 60], [False, False])
        self.assertEqual(no_events["median_repurchase_status"], "not_reached")
        self.assertIsNone(no_events["median_repurchase_days"])
        self.assertEqual(no_events["at_risk"], [
            {"day": 0, "n": 2}, {"day": 14, "n": 2},
            {"day": 30, "n": 1}, {"day": 60, "n": 1},
        ])
        for point in no_events["points"]:
            self.assertEqual((point["survival"], point["survival_ci_lower"], point["survival_ci_upper"]), (1, 1, 1))
        all_events = kaplan_meier_curve([2, 2], [True, True])
        terminal = next(point for point in all_events["points"] if point["day"] == 2)
        self.assertEqual((terminal["survival"], terminal["survival_ci_lower"], terminal["survival_ci_upper"]), (0, 0, 0))
        self.assertEqual(all_events["median_repurchase_days"], 2)
        empty = kaplan_meier_curve([], [])
        self.assertEqual(empty["median_repurchase_status"], "no_customers")
        self.assertTrue(all(point["survival"] is None for point in empty["points"]))
        json.dumps([no_events, all_events, empty], allow_nan=False)

    def test_wilson_reference_values_and_empty_denominator(self):
        rate, lower, upper = wilson_interval(2, 5)
        self.assertEqual(rate, 0.4)
        self.assertAlmostEqual(lower, 0.11762077423264783)
        self.assertAlmostEqual(upper, 0.769275718723987)
        self.assertEqual(wilson_interval(0, 0), (None, None, None))
        self.assertAlmostEqual(wilson_interval(0, 10)[1], 0)
        self.assertAlmostEqual(wilson_interval(10, 10)[2], 1)

    def test_summary_uses_control_only_and_whole_cohort_freeze(self):
        marts = _example_marts()
        original = copy.deepcopy(marts)
        result = summarize_diagnostics(marts, self.config())
        self.assertEqual(marts, original)
        self.assertEqual(result["summary"]["control_customers"], 4)
        self.assertEqual(result["summary"]["control_mature_customers"], 3)
        self.assertEqual(result["summary"]["control_repurchase_60d_rate"], 2 / 3)
        cohorts = {row["assigned_month"]: row for row in result["cohorts"]}
        # Windows are [assignment, assignment + day), so exactly day 7 is excluded.
        self.assertEqual([cell["rate"] for cell in cohorts["2025-01"]["cells"]], [0, 0.5, 0.5, 0.5])
        self.assertFalse(cohorts["2025-03"]["is_fully_mature"])
        self.assertTrue(all(cell["rate"] is None for cell in cohorts["2025-03"]["cells"]))
        pack_200 = next(row for row in result["segments"] if row["feature"] == "first_pack_grams" and row["value"] == 200)
        self.assertEqual((pack_200["n_eligible_control"], pack_200["n_mature"], pack_200["events"]), (2, 1, 1))
        encoded = json.dumps(result, allow_nan=False)
        self.assertNotIn("hidden_consumption_speed", encoded)
        self.assertNotIn("999999", encoded)
        self.assertFalse(result["methods"]["treatment_comparisons_performed"])

    def test_rejects_wrong_scope_invalid_join_and_post_cutoff_event(self):
        cfg = self.config()
        wrong_scope = _example_marts()
        wrong_scope["metadata"]["analysis_scope"] = "final_test"
        duplicate = _example_marts()
        duplicate["features"].append(copy.deepcopy(duplicate["features"][0]))
        late_event = _example_marts()
        late_event["outcomes"][0]["days_to_first_repeat_paid"] = 60.0
        out_of_train = _example_marts()
        for key in ("features", "outcomes"):
            out_of_train[key][0]["assigned_at"] = "2025-01-14T09:00:00+09:00"
        for case in (wrong_scope, duplicate, late_event, out_of_train):
            with self.subTest(case=case), self.assertRaises(ValueError):
                summarize_diagnostics(case, cfg)

    @unittest.skipUnless(importlib.util.find_spec("lifelines"), "Optional independent lifelines reference is not installed")
    def test_km_matches_lifelines_on_ties_censoring_and_endpoints(self):
        from lifelines import KaplanMeierFitter

        cases = [
            ([1, 2, 2, 4, 5], [True, True, False, True, False]),
            ([14, 60], [False, False]),
            ([2, 2], [True, True]),
            ([0, 0, 3, 60], [True, False, True, False]),
        ]
        for durations, events in cases:
            with self.subTest(durations=durations, events=events):
                curve = kaplan_meier_curve(durations, events)
                points = [point for point in curve["points"] if point["survival"] is not None]
                reference = KaplanMeierFitter().fit(durations, events, timeline=[point["day"] for point in points])
                for point in points:
                    day = point["day"]
                    self.assertAlmostEqual(point["survival"], reference.survival_function_.loc[day].iloc[0], places=12)
                    self.assertAlmostEqual(point["survival_ci_lower"], reference.confidence_interval_.loc[day].iloc[0], places=12)
                    self.assertAlmostEqual(point["survival_ci_upper"], reference.confidence_interval_.loc[day].iloc[1], places=12)


if __name__ == "__main__":
    unittest.main()
