"""Observed-only contracts catch corruption and point-in-time leakage."""

import copy
from datetime import timedelta
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, load_config, parse_ts
from crm_retention_lab.contracts import validate_dataset
from crm_retention_lab.simulation import generate_dataset


ROOT = Path(__file__).resolve().parents[1]


class DatasetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT / "configs" / "smoke_v0_1.json", customers=100)
        cls.observed, cls.oracle = generate_dataset(cls.config)

    def fresh(self):
        return copy.deepcopy(self.observed)

    def assert_rule(self, data, rule):
        report = validate_dataset(data, self.config)
        self.assertFalse(report["valid"])
        self.assertTrue(any(message.startswith(rule + ":") for message in report["errors"]),
                        f"Missing {rule}: {report['errors'][:15]}")
        return report

    def test_small_generated_population_passes_without_oracle(self):
        before = copy.deepcopy(self.observed)
        report = validate_dataset(self.observed, self.config)
        self.assertTrue(report["valid"], report["errors"][:15])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["row_counts"]["customers"], 100)
        self.assertEqual(sum(report["checks"][f"assignments_{arm}"]
                             for arm in ("control", "info", "coupon")),
                         len(self.observed["assignments"]))
        self.assertEqual(self.observed, before, "validation must not mutate input")
        self.assertTrue(self.oracle)

    def test_zero_cost_and_no_behavior_effect_scenarios_pass(self):
        for scenario in ("a_a_zero_cost", "no_behavior_effect"):
            with self.subTest(scenario=scenario):
                config = load_config(ROOT / "configs" / "smoke_v0_1.json", customers=30, scenario=scenario)
                observed, _ = generate_dataset(config)
                report = validate_dataset(observed, config)
                self.assertTrue(report["valid"], report["errors"][:15])

    def test_hidden_oracle_column_is_rejected(self):
        data = self.fresh()
        data["customers"][0]["price_sensitivity"] = 0.7
        self.assert_rule(data, "columns")

    def test_hidden_oracle_table_is_rejected(self):
        data = self.fresh()
        data["oracle"] = copy.deepcopy(self.oracle)
        self.assert_rule(data, "tables")

    def test_missing_table_or_field_is_reported(self):
        data = self.fresh()
        del data["contacts"]
        self.assert_rule(data, "tables")
        data = self.fresh()
        del data["orders"][0]["paid_at"]
        self.assert_rule(data, "columns")

    def test_malformed_rows_and_non_json_cells_do_not_crash(self):
        for table, replacement in (("orders", None), ("contacts", [None]),
                                   ("customers", [{"customer_id": []}])):
            with self.subTest(table=table):
                data = self.fresh()
                data[table] = replacement
                report = validate_dataset(data, self.config)
                self.assertFalse(report["valid"])
                self.assertTrue(report["errors"])
        for value in (float("nan"), {"hidden": 1}, [1]):
            with self.subTest(value=value):
                data = self.fresh()
                data["customers"][0]["acquisition_channel"] = value
                self.assert_rule(data, "cell_type")
        self.assertFalse(validate_dataset([], self.config)["valid"])

    def test_duplicate_primary_key_and_missing_foreign_key(self):
        data = self.fresh()
        data["orders"].append(copy.deepcopy(data["orders"][0]))
        self.assert_rule(data, "primary_key_unique")
        data = self.fresh()
        data["orders"][0]["customer_id"] = "missing-customer"
        self.assert_rule(data, "foreign_key")

    def test_future_record_at_observation_boundary_is_rejected(self):
        data = self.fresh()
        data["customer_events"][0]["recorded_at"] = self.config["population"]["observation_end_exclusive"]
        self.assert_rule(data, "observation_cutoff")

    def test_future_coupon_expiry_is_allowed_as_a_known_term(self):
        config = load_config(ROOT / "configs" / "smoke_v0_1.json", customers=30)
        cutoff = parse_ts(config["population"]["observation_end_exclusive"])
        config["population"]["first_delivery_start_inclusive"] = iso(cutoff - timedelta(days=15))
        config["population"]["first_delivery_end_exclusive"] = iso(cutoff - timedelta(days=14))
        data, _ = generate_dataset(config)
        self.assertTrue(any(contact["coupon_expires_at"]
                            and parse_ts(contact["coupon_expires_at"]) >= cutoff
                            for contact in data["contacts"]))
        report = validate_dataset(data, config)
        self.assertTrue(report["valid"], report["errors"][:15])

    def test_naive_timestamp_is_rejected(self):
        data = self.fresh()
        data["orders"][0]["paid_at"] = "2025-01-01T09:00:00"
        self.assert_rule(data, "timestamp")

    def test_delivery_chronology_and_null_pair_are_checked(self):
        data = self.fresh()
        order = data["orders"][0]
        order["delivered_at"] = iso(parse_ts(order["paid_at"]) - timedelta(days=1))
        order["delivery_recorded_at"] = order["delivered_at"]
        self.assert_rule(data, "order_sequence")
        data = self.fresh()
        data["orders"][0]["delivery_recorded_at"] = None
        self.assert_rule(data, "delivery_nullability")

    def test_analytics_lag_and_recording_before_occurrence(self):
        for lag, rule in ((timedelta(days=8), "analytics_lag"),
                          (timedelta(seconds=-1), "recording_order")):
            with self.subTest(rule=rule):
                data = self.fresh()
                event = next(row for row in data["customer_events"] if row["event_type"] == "session")
                event["recorded_at"] = iso(parse_ts(event["occurred_at"]) + lag)
                self.assert_rule(data, rule)

    def test_late_consent_record_cannot_create_eligibility(self):
        data = self.fresh()
        assignment = data["assignments"][0]
        consent = next(row for row in data["customer_events"]
                       if row["customer_id"] == assignment["customer_id"] and row["event_type"] == "consent_granted")
        consent["recorded_at"] = iso(parse_ts(assignment["assigned_at"]) + timedelta(seconds=1))
        report = self.assert_rule(data, "operational_lag")
        self.assertTrue(any(error.startswith("eligibility_recomputed:") for error in report["errors"]))
        self.assertTrue(any(error.startswith("assignment_eligibility:") for error in report["errors"]))

    def test_duplicate_customer_assignment_is_rejected(self):
        data = self.fresh()
        duplicate = copy.deepcopy(data["assignments"][0])
        duplicate["assignment_id"] += "-duplicate"
        data["assignments"].append(duplicate)
        self.assert_rule(data, "assignment_unique_customer")

    def test_assignment_probability_and_time_are_checked(self):
        data = self.fresh()
        data["assignments"][0]["p_coupon"] = 0.5
        self.assert_rule(data, "assignment_probability")
        data = self.fresh()
        assignment = data["assignments"][0]
        assignment["assigned_at"] = iso(parse_ts(assignment["assigned_at"]) + timedelta(days=1))
        self.assert_rule(data, "assignment_time")

    def test_coupon_double_subtraction_is_rejected(self):
        data = self.fresh()
        order = next(row for row in data["orders"] if row["crm_coupon_discount_krw"] > 0)
        revenue = next(row for row in data["order_ledger"]
                       if row["order_id"] == order["order_id"] and row["entry_type"] == "net_item_revenue")
        revenue["amount_krw"] -= order["crm_coupon_discount_krw"]
        self.assert_rule(data, "ledger_amount")
        data = self.fresh()
        extra_cost = copy.deepcopy(data["order_ledger"][0])
        extra_cost.update(entry_id="illegal-coupon-cost", entry_type="coupon_cost", amount_krw=-3000)
        data["order_ledger"].append(extra_cost)
        self.assert_rule(data, "ledger_type")

    def test_duplicate_cost_entry_is_rejected(self):
        data = self.fresh()
        duplicate = copy.deepcopy(next(row for row in data["order_ledger"] if row["entry_type"] == "cogs"))
        duplicate["entry_id"] += "-duplicate"
        data["order_ledger"].append(duplicate)
        self.assert_rule(data, "ledger_entry_unique")

    def test_coupon_cannot_be_redeemed_twice_or_by_another_customer(self):
        data = self.fresh()
        redeemed = next(row for row in data["orders"] if row["coupon_assignment_id"])
        other = next(row for row in data["orders"] if row["customer_id"] != redeemed["customer_id"])
        other["coupon_assignment_id"] = redeemed["coupon_assignment_id"]
        other["crm_coupon_discount_krw"] = redeemed["crm_coupon_discount_krw"]
        report = self.assert_rule(data, "coupon_single_use")
        self.assertTrue(any(error.startswith("coupon_ownership:") for error in report["errors"]))

    def test_coupon_expiry_is_exclusive(self):
        data = self.fresh()
        redeemed = next(row for row in data["orders"] if row["coupon_assignment_id"])
        contact = next(row for row in data["contacts"] if row["assignment_id"] == redeemed["coupon_assignment_id"])
        redeemed["paid_at"] = contact["coupon_expires_at"]
        redeemed["paid_recorded_at"] = contact["coupon_expires_at"]
        self.assert_rule(data, "coupon_window")

    def test_missing_ledger_entry_and_excessive_recovery_are_rejected(self):
        data = self.fresh()
        data["order_ledger"].pop(0)
        self.assert_rule(data, "ledger_completeness")
        data = self.fresh()
        recovery = next(row for row in data["order_ledger"] if row["entry_type"] == "cogs_recovery")
        recovery["amount_krw"] = 10**9
        self.assert_rule(data, "cogs_recovery")

    def test_financial_adjustment_after_30_days_is_rejected(self):
        data = self.fresh()
        refund = next(row for row in data["order_ledger"] if row["entry_type"] == "refund")
        order = next(row for row in data["orders"] if row["order_id"] == refund["order_id"])
        refund["recorded_at"] = iso(parse_ts(order["paid_at"]) + timedelta(days=31))
        self.assert_rule(data, "settlement_limit")

    def test_contact_counts_costs_and_open_sequence(self):
        data = self.fresh()
        data["contacts"].pop(0)
        self.assert_rule(data, "contact_count")
        data = self.fresh()
        data["contacts"][0]["send_cost_krw"] = 0
        self.assert_rule(data, "contact_cost")
        data = self.fresh()
        contact = next(row for row in data["contacts"] if row["delivered_at"])
        contact["opened_at"] = iso(parse_ts(contact["delivered_at"]) - timedelta(seconds=1))
        self.assert_rule(data, "contact_time")
        data = self.fresh()
        control = next(row for row in data["assignments"] if row["arm"] == "control")
        data["contacts"][0]["assignment_id"] = control["assignment_id"]
        self.assert_rule(data, "control_contact")

    def test_audit_cannot_be_overwritten_to_make_customer_eligible(self):
        data = self.fresh()
        audit = next(row for row in data["eligibility_audit"] if not row["eligible"])
        audit["eligible"], audit["reason_codes"] = True, []
        self.assert_rule(data, "eligibility_recomputed")

    def test_missing_and_additional_audits_are_rejected(self):
        data = self.fresh()
        data["eligibility_audit"].pop(0)
        self.assert_rule(data, "audit_completeness")
        data = self.fresh()
        extra = copy.deepcopy(data["eligibility_audit"][0])
        extra["customer_id"] = "unknown-customer"
        data["eligibility_audit"].append(extra)
        self.assert_rule(data, "audit_population")


if __name__ == "__main__":
    unittest.main()
