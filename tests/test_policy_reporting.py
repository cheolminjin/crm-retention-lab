"""Decision narrative checks with invented aggregate fixtures only."""

import copy
import unittest

from crm_retention_lab.policy_reporting import build_policy_section
from crm_retention_lab.uplift import DEFAULT_MODEL_SPEC


FIGURES = ("policy_validation", "policy_profit", "policy_allocation", "policy_guardrails", "policy_segments")


def analysis_fixture():
    spec = {"id": "uplift_ridge_lambda_0p5", "kind": "uplift", "model": "ridge", "penalty_lambda": 0.5}
    primary = {"estimate": 40.0, "ci_lower": 15.0, "ci_upper": 70.0, "confidence_level": 0.95}
    final = {
        "policy_id": spec["id"], "policy_spec": spec.copy(), "n": 30, "primary": primary,
        "ipw_check": {**primary, "estimate": 35.0, "ci_lower": -10.0, "ci_upper": 80.0},
        "guardrails": [
            {"metric": "unsubscribe_60d", "estimate": 0.001, "ci_upper": 0.004, "one_sided_confidence": 0.975,
             "tolerance": 0.005, "assessment": "within_tolerance"},
            {"metric": "refund_customer_flag", "estimate": -0.001, "ci_upper": 0.009, "one_sided_confidence": 0.975,
             "tolerance": 0.01, "assessment": "within_tolerance"},
        ],
        "exposure": {"counts": {"control": 24, "info": 6, "coupon": 0}, "contact_n": 6, "contact_fraction": 0.2,
                     "contact_cap_total": 9, "reservation_total_krw": 120, "budget_cap_total_krw": 9000,
                     "violating_batches": 0},
        "rollout": {"eligible_customers": 10000, "setup_cost_krw": 100000, "incremental_profit_krw": 300000,
                    "ci_lower": 50000, "ci_upper": 600000, "caps_ok": True, "decision": "candidate"},
        "bootstrap": {"repetitions": 2000, "cap_violating_resamples": 0},
        "overlap": {"policy": {"matched_n": 10, "effective_sample_size": 10.0}},
        "segments": [{"first_pack_grams": 500, "n": 30, "control": 24, "info": 6, "coupon": 0}],
        "allocation": {"summary": {}, "batch_audit": [{"customer_id": "private-customer-never-render"}]},
    }
    validation = copy.deepcopy(final)
    validation["bootstrap"]["repetitions"] = 0
    validation["screen"] = {"profit_pass": True, "harm_pass": True, "eligible": True}
    for guardrail in validation["guardrails"]:
        guardrail["one_sided_confidence"] = 0.996875
    control = copy.deepcopy(final)
    control.update(policy_id="control", policy_spec={"id": "control", "kind": "control", "model": "hgb", "penalty_lambda": 0.0})
    control["primary"].update(estimate=0, ci_lower=0, ci_upper=0)
    control["ipw_check"].update(estimate=0, ci_lower=0, ci_upper=0)
    control["rollout"].update(setup_cost_krw=0, incremental_profit_krw=0, ci_lower=0, ci_upper=0, decision="modify_or_collect_more_evidence")
    control["exposure"].update(counts={"control": 30, "info": 0, "coupon": 0}, contact_n=0, contact_fraction=0, reservation_total_krw=0)
    for guardrail in control["guardrails"]:
        guardrail.update(estimate=0, ci_upper=0)
    splits = {}
    for name, start, end, readout in (("train", "2025-01-15", "2025-07-01", "2025-10-01"),
                                    ("validation", "2025-10-01", "2025-12-01", "2026-03-01"),
                                    ("final_test", "2026-03-01", "2026-05-01", "2026-08-01")):
        prefix = "train" if name == "train" else "split"
        splits[name] = {"selected_assignments": 36 if name == "train" else 30,
                        prefix + "_start_inclusive": start + "T00:00:00+09:00",
                        prefix + "_end_exclusive": end + "T00:00:00+09:00",
                        ("train_labels_available_by" if name == "train" else "split_readout_at"): readout + "T00:00:00+09:00"}
    return {
        "metadata": {"synthetic": True, "splits": splits},
        "model_manifest": {"n_train": 36, "model_spec": copy.deepcopy(DEFAULT_MODEL_SPEC)},
        "selection": {"chosen_policy": spec.copy(), "reason": "prespecified_choice", "feasible_ids": [spec["id"]], "one_se_ids": [spec["id"]]},
        "validation": [validation], "final": [final, control], "lock": {},
        "constraints": {"max_contact_fraction": 0.3, "budget_reservation_cap_krw_per_10000": 3000000,
                        "fixed_setup_cost_krw_per_rollout": 100000},
    }


class PolicyReportingTests(unittest.TestCase):
    def test_aggregate_evidence_and_conditional_scope_are_preserved(self):
        source = analysis_fixture()
        before = copy.deepcopy(source)
        result = build_policy_section(source, {name: f"<p>{name}</p>" for name in FIGURES})
        self.assertIn("**+40 KRW/eligible customer**", result)
        self.assertIn("**+300,000 KRW**", result)
        self.assertIn("Reservation budgets and λ penalties are not deducted again", result)
        self.assertIn("not observed individual true effects", result)
        self.assertIn("exploratory baselines", result)
        self.assertIn("full training uncertainty", result)
        self.assertIn("does not guarantee a global optimum", result)
        self.assertIn("Validation intervals are normal approximations for fixed action scores", result)
        self.assertNotIn("private-customer-never-render", result)
        self.assertEqual(source, before)

    def test_control_fallback_never_claims_active_policy_success(self):
        source = analysis_fixture()
        source["selection"].update(chosen_policy=source["final"][1]["policy_spec"].copy(), feasible_ids=[], one_se_ids=[])
        result = build_policy_section(source)
        self.assertIn("**Keep no contact.**", result)
        self.assertIn("effectiveness of an active campaign", result)
        self.assertNotIn("A rollout candidate within this synthetic environment", result)

    def test_hold_and_insufficient_evidence_have_distinct_conclusions(self):
        for decision, expected in (("hold", "**Hold the current policy.**"),
                                   ("modify_or_collect_more_evidence", "**Modify operating conditions or collect more evidence.**")):
            source = analysis_fixture()
            source["final"][0]["rollout"]["decision"] = decision
            with self.subTest(decision=decision):
                self.assertIn(expected, build_policy_section(source))

    def test_missing_duplicate_or_mismatched_locked_policy_cannot_be_reported(self):
        for mutate in (lambda a: a["final"].pop(0),
                       lambda a: a["final"].append(copy.deepcopy(a["final"][0])),
                       lambda a: a["final"][0]["policy_spec"].update(penalty_lambda=2.0)):
            source = analysis_fixture()
            mutate(source)
            with self.assertRaises(ValueError):
                build_policy_section(source)

    def test_screening_partial_population_and_real_world_input_are_rejected(self):
        for mutate in (lambda a: a["final"][0]["bootstrap"].update(repetitions=0),
                       lambda a: a["final"][0].update(n=29),
                       lambda a: a["metadata"].update(synthetic=False)):
            source = analysis_fixture()
            mutate(source)
            with self.assertRaises(ValueError):
                build_policy_section(source)


if __name__ == "__main__":
    unittest.main()
