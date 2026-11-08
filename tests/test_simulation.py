"""Mechanism and observation-contract tests, not claims about marketing effects."""

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from crm_retention_lab.config import load_config, parse_ts
from crm_retention_lab.schema import TABLE_COLUMNS
from crm_retention_lab.simulation import generate_dataset


ROOT = Path(__file__).resolve().parents[1]


def _without_metadata(records):
    return [{k: v for k, v in record.items() if k not in ("simulation_id", "schema_version")}
            for record in records]


class SimulationTests(unittest.TestCase):
    def config(self, count=80, scenario="base"):
        return load_config(ROOT / "configs" / "smoke_v0_1.json", customers=count, scenario=scenario)

    def test_reproducible_and_seed_changes_population(self):
        cfg = self.config()
        observed, oracle = generate_dataset(cfg)
        self.assertEqual((observed, oracle), generate_dataset(cfg))
        different = copy.deepcopy(cfg)
        different["reproducibility"]["base_seed"] += 1
        changed, changed_oracle = generate_dataset(different)
        self.assertNotEqual(_without_metadata(observed["orders"]), _without_metadata(changed["orders"]))
        self.assertNotEqual([x["consumption_grams_daily"] for x in oracle],
                            [x["consumption_grams_daily"] for x in changed_oracle])

    def test_observed_allowlist_and_oracle_separation(self):
        observed, oracle = generate_dataset(self.config())
        self.assertEqual(set(observed), set(TABLE_COLUMNS))
        hidden = {"consumption_grams_daily", "product_preference", "price_sensitivity", "oracle_scope"}
        self.assertTrue(oracle)
        self.assertTrue(hidden.issubset(oracle[0]))
        for table, records in observed.items():
            for record in records:
                self.assertEqual(set(record), set(TABLE_COLUMNS[table]))
                self.assertFalse(set(record) & hidden)

    def test_no_future_observations_or_pending_audit(self):
        cfg = self.config(180)
        cutoff = parse_ts(cfg["population"]["observation_end_exclusive"])
        observed, _ = generate_dataset(cfg)
        for records in observed.values():
            for record in records:
                for key, value in record.items():
                    if value is not None and key.endswith("_at") and key != "coupon_expires_at":
                        timestamp = parse_ts(value)
                        self.assertLess(timestamp, cutoff, (key, value))
        first_orders = {}
        for order in observed["orders"]:
            first_orders.setdefault(order["customer_id"], order)
            self.assertEqual(order["delivered_at"] is None, order["delivery_recorded_at"] is None)
        audited = {row["customer_id"] for row in observed["eligibility_audit"]}
        pending = {cid for cid, order in first_orders.items()
                   if (cutoff - parse_ts(order["delivered_at"])).total_seconds() <= 14 * 86400}
        self.assertTrue(pending)
        self.assertFalse(pending & audited)
        for assignment in observed["assignments"]:
            self.assertEqual(parse_ts(assignment["assigned_at"]).hour, 9)
            self.assertEqual((parse_ts(assignment["assigned_at"]) - parse_ts(assignment["first_delivered_at"])).days, 14)

    def test_aa_arm_does_not_change_commercial_or_customer_behavior(self):
        cfg = self.config(100, "a_a_zero_cost")
        with patch("crm_retention_lab.simulation._choose_arm", return_value="control"):
            control, _ = generate_dataset(cfg)
        for arm in ("info", "coupon"):
            with patch("crm_retention_lab.simulation._choose_arm", return_value=arm):
                active, _ = generate_dataset(cfg)
            for table in ("orders", "order_events", "order_ledger", "customer_events", "eligibility_audit"):
                self.assertEqual(control[table], active[table], (arm, table))
            self.assertTrue(active["contacts"])
            self.assertTrue(all(contact["send_cost_krw"] == 0 for contact in active["contacts"]))
            self.assertTrue(all(order["crm_coupon_discount_krw"] == 0 for order in active["orders"]))

    def test_no_behavior_effect_keeps_purchase_draws_and_applies_real_discount(self):
        cfg = self.config(180, "no_behavior_effect")
        # Force sufficient delivery/redemption for a deterministic mechanism check.
        cfg["generator"]["contact"]["delivery_success_probability"] = 1.0
        cfg["generator"]["contact"]["coupon_redeem_probability_intercept"] = 1.0
        cfg["generator"]["behavior"]["daily_base_odds"] = 0.3
        with patch("crm_retention_lab.simulation._choose_arm", return_value="coupon"):
            coupon, _ = generate_dataset(cfg)
        with patch("crm_retention_lab.simulation._choose_arm", return_value="control"):
            control, _ = generate_dataset(cfg)
        shape = lambda rows: [(x["customer_id"], x["order_id"], x["paid_at"], x["sku"], x["quantity"]) for x in rows]
        self.assertEqual(shape(coupon["orders"]), shape(control["orders"]))
        self.assertTrue(any(x["crm_coupon_discount_krw"] > 0 for x in coupon["orders"]))
        self.assertEqual(coupon["customer_events"], control["customer_events"])
        self.assertEqual(coupon["order_events"], control["order_events"])

    def test_customer_stream_prefix_stable_when_population_grows(self):
        small, _ = generate_dataset(self.config(20))
        larger, _ = generate_dataset(self.config(30))
        prefix = {row["customer_id"] for row in small["customers"]}
        for table in ("customers", "orders", "customer_events", "assignments", "eligibility_audit"):
            matching = [row for row in larger[table] if row["customer_id"] in prefix]
            self.assertEqual(_without_metadata(small[table]), _without_metadata(matching), table)


if __name__ == "__main__":
    unittest.main()
