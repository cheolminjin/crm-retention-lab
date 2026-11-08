"""Hand-accounted examples for checks that must not change the ITT population."""

import copy
from datetime import timedelta
import importlib.util
import json
import math
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, load_config, parse_ts
from crm_retention_lab.experiment_checks import _moments, _smd, summarize_experiment_checks
from crm_retention_lab.schema import TABLE_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
HAS_SCIPY = importlib.util.find_spec("scipy") is not None


def fixture():
    config = load_config(ROOT / "configs" / "train_diagnostic_v0_1.json")
    observed = {table: [] for table in TABLE_COLUMNS}
    features, outcomes = [], []
    start = parse_ts("2025-01-15T09:00:00+09:00")
    freeze = start + timedelta(days=90)
    for arm in ("control", "info", "coupon"):
        for index in range(2):
            customer, aid = f"private-{arm}-{index}", f"assignment-{arm}-{index}"
            common = {"customer_id": customer, "assignment_id": aid, "arm": arm, "assigned_at": iso(start)}
            observed["assignments"].append({**common, "first_order_id": customer + "-first",
                                            "p_control": 1 / 3, "p_info": 1 / 3, "p_coupon": 1 / 3})
            features.append({**common, "feature_cutoff_at": iso(start), "first_pack_grams": 200 if index == 0 else 500,
                             "first_quantity": 1, "first_paid_amount_krw": 28000, "first_discount_rate": 0,
                             "delivery_lead_days": 2, "acquisition_channel": "search", "sessions_d0_d13": index,
                             "tip_views_d0_d13": 0, "cart_events_d0_d13": 0,
                             "days_since_last_session": None if index == 0 else 2, "first_delivery_month": 1})
            send = 0 if arm == "control" else 20
            outcome = {**common, "is_outcome_mature": True, "is_profit_settled": True,
                       "label_freeze_at": iso(freeze), "contribution_profit_60d_krw": -send,
                       "repeat_paid_within_60d": 0, "order_count_60d": 0, "refund_amount_krw": 0,
                       "refund_customer_flag": 0, "actual_campaign_spend_krw": send}
            outcomes.append(outcome)
            if arm != "control":
                observed["contacts"].append({"contact_id": aid + "-contact", "assignment_id": aid,
                    "attempted_at": iso(start + timedelta(minutes=5)),
                    "delivered_at": iso(start + timedelta(minutes=6)) if index == 0 else None,
                    "opened_at": iso(start + timedelta(days=1)) if arm == "info" and index == 0 else None,
                    "clicked_at": None, "coupon_issued_at": iso(start + timedelta(minutes=6)) if arm == "coupon" and index == 0 else None,
                    "send_cost_krw": send})
            if index != 0:
                continue
            paid = start + timedelta(days=10)
            coupon = 3000 if arm == "coupon" else 0
            net = 28000 - coupon
            order_id = customer + "-repeat"
            order = {"order_id": order_id, "customer_id": customer, "paid_at": iso(paid), "paid_recorded_at": iso(paid),
                     "list_subtotal_krw": 28000, "other_discount_krw": 0, "crm_coupon_discount_krw": coupon,
                     "item_revenue_after_discount_krw": net, "customer_shipping_charge_krw": 3000,
                     "coupon_assignment_id": aid if coupon else None}
            observed["orders"].append(order)
            amounts = {"net_item_revenue": net, "customer_shipping_charge": 3000, "cogs": -12000,
                       "outbound_shipping": -3000, "fulfillment": -700, "payment_fee": -700 if coupon else -775}
            if arm == "info":
                amounts.update(refund=-31000, cogs_recovery=6000, return_handling=-3000)
            for kind, amount in amounts.items():
                observed["order_ledger"].append({"entry_id": order_id + "-" + kind, "order_id": order_id,
                    "entry_type": kind, "amount_krw": amount, "occurred_at": iso(paid), "recorded_at": iso(paid)})
            # Independent hand totals: normal=14525; full refund=-13475; coupon=11600.
            outcome.update(contribution_profit_60d_krw={"control": 14525, "info": -13495, "coupon": 11580}[arm],
                           repeat_paid_within_60d=1, order_count_60d=1,
                           refund_amount_krw=31000 if arm == "info" else 0,
                           refund_customer_flag=int(arm == "info"), actual_campaign_spend_krw=send + coupon)
            # Poison rows must not enter first-order/60-day/frozen financial windows.
            first = dict(order, order_id=customer + "-first", paid_at=iso(start - timedelta(days=15)), paid_recorded_at=iso(start - timedelta(days=15)))
            late = dict(order, order_id=customer + "-late", paid_at=iso(start + timedelta(days=60)), paid_recorded_at=iso(start + timedelta(days=60)))
            observed["orders"].extend([first, late])
            for ignored in (first, late):
                observed["order_ledger"].append({"entry_id": ignored["order_id"] + "-poison", "order_id": ignored["order_id"],
                    "entry_type": "net_item_revenue", "amount_krw": 99999999,
                    "occurred_at": ignored["paid_at"], "recorded_at": ignored["paid_at"]})
            observed["order_ledger"].append({"entry_id": order_id + "-freeze-boundary", "order_id": order_id,
                "entry_type": "refund", "amount_krw": -99999999, "occurred_at": iso(freeze), "recorded_at": iso(freeze)})
    marts = {"features": features, "outcomes": outcomes,
             "metadata": {"analysis_scope": "train", "as_of": "2025-10-01T00:00:00+09:00"}}
    return observed, marts, config


class StandardizedDifferenceTests(unittest.TestCase):
    def test_numeric_smd_uses_mean_of_sample_variances(self):
        smd, status = _smd(_moments([20, 24]), _moments([10, 14]))
        self.assertEqual(status, "defined")
        self.assertAlmostEqual(smd, 10 / math.sqrt(8))
        self.assertEqual(_smd(_moments([2, 2]), _moments([2, 2])), (0, "defined"))
        self.assertEqual(_smd(_moments([2, 2]), _moments([1, 1])), (None, "undefined_constant_difference"))
        self.assertEqual(_smd(_moments([2]), _moments([1, 1])), (None, "insufficient_n"))


@unittest.skipUnless(HAS_SCIPY, "Optional SciPy analysis dependency is not installed")
class ExperimentChecksTests(unittest.TestCase):
    def test_signed_finance_matches_hand_totals_and_excludes_boundary_rows(self):
        observed, marts, config = fixture()
        before = copy.deepcopy((observed, marts, config))
        result = summarize_experiment_checks(observed, marts, config)
        self.assertEqual(before, (observed, marts, config))
        finance = result["finance_reconciliation"]
        self.assertEqual((finance["status"], finance["mismatch_customers"]), ("passed", 0))
        arms = {row["arm"]: row for row in finance["arms"]}
        self.assertEqual([arms[arm]["total_profit_krw"] for arm in ("control", "info", "coupon")], [14525, -13515, 11560])
        comparison = next(row for row in finance["comparisons"] if row["contrast"] == "coupon_vs_info")
        self.assertEqual(comparison["profit_mean_difference_krw"], 12537.5)
        self.assertAlmostEqual(sum(comparison["components_mean_difference_krw"].values()), 12537.5)
        self.assertEqual(arms["coupon"]["components_total_krw"]["net_item_revenue"], 25000)
        self.assertNotIn("crm_coupon_discount_krw", finance["components_order"])
        supporting = next(row for row in finance["supporting_accounting"]["arms"] if row["arm"] == "coupon")
        self.assertEqual(supporting["totals_krw"], {"list_subtotal_krw": 28000, "other_discount_krw": 0, "crm_coupon_discount_krw": 3000})

    def test_delivery_uses_itt_and_redemption_need_not_follow_open(self):
        observed, marts, config = fixture()
        funnel = summarize_experiment_checks(observed, marts, config)["delivery_funnel"]
        self.assertFalse(funnel["strictly_nested"])
        arms = {row["arm"]: row for row in funnel["arms"]}
        self.assertEqual(arms["coupon"]["counts"]["opened"], 0)
        self.assertEqual(arms["coupon"]["counts"]["redeemed"], 1)
        self.assertEqual(arms["coupon"]["rates_per_assigned"]["redeemed"], 0.5)
        self.assertEqual(arms["coupon"]["counts"]["attempted"], 2)
        self.assertEqual(arms["coupon"]["counts"]["reached"], 1)
        self.assertIsNone(arms["control"]["rates_per_assigned"]["opened"])

    def test_srm_uses_configured_probabilities_and_flags_without_deleting(self):
        observed, marts, config = fixture()
        balanced = summarize_experiment_checks(observed, marts, config)["randomization"]
        self.assertEqual((balanced["chi_square"], balanced["p_value"], balanced["srm_flag"]), (0, 1, False))
        for specification, probability in zip(config["experiment"]["arms"], (0.5, 0.25, 0.25)):
            specification["probability"] = probability
            for assignment in observed["assignments"]:
                assignment["p_" + specification["id"]] = probability
        different_design = summarize_experiment_checks(observed, marts, config)["randomization"]
        self.assertAlmostEqual(different_design["chi_square"], 2 / 3)
        # The chi-square survival function for two degrees of freedom is exp(-x/2).
        self.assertAlmostEqual(different_design["p_value"], math.exp(-1 / 3))
        observed, marts, config = fixture()
        for index in range(100):
            aid, customer = f"new-assignment-{index}", f"private-new-{index}"
            for rows, template in ((observed["assignments"], observed["assignments"][1]),
                                   (marts["features"], marts["features"][1]), (marts["outcomes"], marts["outcomes"][1])):
                rows.append(dict(template, assignment_id=aid, customer_id=customer))
        flagged = summarize_experiment_checks(observed, marts, config)
        self.assertTrue(flagged["randomization"]["srm_flag"])
        self.assertEqual(flagged["randomization"]["n_assigned"], 106)
        self.assertEqual(flagged["finance_reconciliation"]["n_customers_checked"], 106)

    def test_balance_reports_missingness_and_categorical_maximum(self):
        observed, marts, config = fixture()
        info = [row for row in marts["features"] if row["arm"] == "info"]
        info[0]["days_since_last_session"] = 4
        info[0]["acquisition_channel"] = "ads"
        for row in info:
            row["first_delivery_month"] = 2
        balance = summarize_experiment_checks(observed, marts, config)["balance"]
        rows = {row["feature"]: row for row in balance["features"]}
        self.assertEqual(len(rows), 12)
        missing = next(row for row in rows["days_since_last_session__missing"]["comparisons"] if row["contrast"] == "info_vs_control")
        self.assertEqual(missing["smd"], -1)
        category = next(row for row in rows["acquisition_channel"]["comparisons"] if row["contrast"] == "info_vs_control")
        self.assertEqual((category["level"], category["smd"]), ("ads", 1))
        self.assertIsNone(rows["first_delivery_month"]["max_abs_smd"])
        self.assertTrue(balance["has_undefined_smd"])

    def test_mismatch_is_public_count_only_and_json_is_finite(self):
        observed, marts, config = fixture()
        marts["outcomes"][0]["contribution_profit_60d_krw"] += 1
        result = summarize_experiment_checks(observed, marts, config)
        finance = result["finance_reconciliation"]
        self.assertEqual((finance["status"], finance["mismatch_customers"]), ("mismatch", 1))
        self.assertEqual(finance["mismatch_counts"], {"contribution_profit_60d_krw": 1})
        output = json.dumps(result, allow_nan=False)
        self.assertNotIn("private-", output)
        self.assertNotIn("assignment-control", output)

    def test_rejects_partial_maturity_changed_membership_or_assignment_contract(self):
        modifications = (
            lambda observed, marts, config: marts["outcomes"][0].update(is_profit_settled=False),
            lambda observed, marts, config: marts["outcomes"].pop(),
            lambda observed, marts, config: observed["assignments"][0].update(p_control=0),
            lambda observed, marts, config: observed["assignments"][0].update(arm="unknown"),
            lambda observed, marts, config: marts["features"].append(copy.deepcopy(marts["features"][0])),
            lambda observed, marts, config: marts["metadata"].update(as_of="2026-01-01T00:00:00+09:00"),
            lambda observed, marts, config: observed.update(oracle=[]),
        )
        for modify in modifications:
            observed, marts, config = fixture()
            modify(observed, marts, config)
            with self.subTest(modification=modify), self.assertRaises(ValueError):
                summarize_experiment_checks(observed, marts, config)

    def test_payment_recording_at_freeze_is_excluded(self):
        observed, marts, config = fixture()
        original = next(order for order in observed["orders"] if order["order_id"] == "private-control-0-repeat")
        poison = dict(original, order_id="recorded-at-freeze", paid_recorded_at=marts["outcomes"][0]["label_freeze_at"])
        observed["orders"].append(poison)
        observed["order_ledger"].append({"entry_id": "late-record", "order_id": poison["order_id"],
            "entry_type": "net_item_revenue", "amount_krw": 9999999,
            "occurred_at": poison["paid_at"], "recorded_at": poison["paid_recorded_at"]})
        result = summarize_experiment_checks(observed, marts, config)
        self.assertEqual(result["finance_reconciliation"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
