"""Policy wrapper isolation checks using hand-built rows, never final-run data."""

import copy
from datetime import timedelta
import unittest

import test_marts as fixtures
from crm_retention_lab.config import iso, parse_ts
from crm_retention_lab.marts import FEATURE_COLUMNS, build_marts, build_policy_marts
from crm_retention_lab.schema import TABLE_COLUMNS


def fixture(split="validation"):
    source = fixtures.MartsTests()
    source.setUp()
    source.observed = {table: [] for table in TABLE_COLUMNS}
    source.start = parse_ts(source.config["splits"][split]["start_inclusive"]) + timedelta(days=1)
    source.first, source.assignment = source.customer("c1", source.start, arm="coupon")
    source.append("contacts", contact_id="contact1", assignment_id="c1-a", attempted_at=iso(source.start),
                  delivered_at=None, opened_at=None, clicked_at=None, send_cost_krw=20,
                  coupon_issued_at=None, coupon_expires_at=None)
    return source


class PolicyMartsTests(unittest.TestCase):
    def test_each_split_uses_assignment_start_inclusive_end_exclusive(self):
        for split in ("train", "validation", "final_test"):
            with self.subTest(split=split):
                source = fixture(split)
                source.observed = {table: [] for table in TABLE_COLUMNS}
                start = parse_ts(source.config["splits"][split]["start_inclusive"])
                end = parse_ts(source.config["splits"][split]["end_exclusive"])
                source.customer("before", start - timedelta(seconds=1))
                source.customer("first", start)
                source.customer("last", end - timedelta(seconds=1))
                source.customer("after", end)
                result = build_policy_marts(source.observed, source.config, split=split)
                self.assertEqual([row["customer_id"] for row in result["features"]], ["fixture:first", "fixture:last"])
                self.assertEqual(result["eligibility_flow"]["first_delivery_customers"], 2)
                self.assertEqual(result["eligibility_flow"]["assigned_total"], 2)
                self.assertEqual(result["metadata"]["analysis_scope"], split)

    def test_split_specific_readout_caps_requested_future_and_metadata(self):
        readouts = {"train": "train_labels_available_by", "validation": "policy_lock_at", "final_test": "final_readout_at"}
        for split, key in readouts.items():
            with self.subTest(split=split):
                source = fixture(split)
                result = build_policy_marts(source.observed, source.config, split=split, as_of="2030-01-01T00:00:00+09:00")
                metadata = result["metadata"]
                self.assertEqual(metadata["as_of"], source.config["splits"][key])
                self.assertEqual(metadata["feature_columns"], list(FEATURE_COLUMNS))
                if split != "train":
                    self.assertNotIn("train_labels_available_by", metadata)
                    self.assertNotIn("train_start_inclusive", metadata)
                    self.assertEqual(metadata["split_readout_at"], source.config["splits"][key])
                    self.assertEqual(metadata["split_start_inclusive"], source.config["splits"][split]["start_inclusive"])

    def test_stale_source_cannot_be_matured_by_later_requested_date(self):
        for split in ("train", "validation", "final_test"):
            with self.subTest(split=split):
                source = fixture(split)
                cutoff = iso(source.start + timedelta(days=70))
                source.config["population"]["observation_end_exclusive"] = cutoff
                result = build_policy_marts(source.observed, source.config, split=split, as_of="2030-01-01T00:00:00+09:00")
                self.assertEqual(result["metadata"]["as_of"], cutoff)
                outcome = result["outcomes"][0]
                self.assertTrue(outcome["is_outcome_mature"])
                self.assertFalse(outcome["is_profit_settled"])
                for field in ("repeat_paid_within_60d", "contribution_profit_60d_krw", "refund_customer_flag", "unsubscribe_60d"):
                    self.assertIsNone(outcome[field])

    def test_ninety_day_settlement_is_required_in_every_policy_split(self):
        for split in ("train", "validation", "final_test"):
            with self.subTest(split=split):
                source = fixture(split)
                source.order("repeat", source.start + timedelta(days=2), coupon=3000)
                freeze = source.start + timedelta(days=90)
                before = build_policy_marts(source.observed, source.config, split=split, as_of=iso(freeze - timedelta(seconds=1)))
                self.assertTrue(before["outcomes"][0]["repeat_event_observed"])
                self.assertIsNone(before["outcomes"][0]["contribution_profit_60d_krw"])
                exact = build_policy_marts(source.observed, source.config, split=split, as_of=iso(freeze))
                self.assertEqual(exact["outcomes"][0]["contribution_profit_60d_krw"], 11580)
                self.assertEqual(exact["outcomes"][0]["label_freeze_at"], iso(freeze))

    def test_validation_features_and_finalized_ledger_keep_pre_cutoff_rules(self):
        source = fixture()
        source.event("session", source.start - timedelta(days=1))
        source.event("session", source.start - timedelta(hours=1), source.start)
        source.event("session", source.start + timedelta(days=1))
        source.order("repeat", source.start + timedelta(days=1), coupon=3000)
        freeze = source.start + timedelta(days=90)
        source.append("order_ledger", entry_id="too-late-refund", order_id="repeat", entry_type="refund",
                      amount_krw=-28000, occurred_at=iso(source.start + timedelta(days=10)), recorded_at=iso(freeze))
        source.event("consent_revoked", source.start + timedelta(days=2), freeze)
        result = build_policy_marts(source.observed, source.config, split="validation")
        self.assertEqual(result["features"][0]["sessions_d0_d13"], 1)
        self.assertEqual(result["outcomes"][0]["contribution_profit_60d_krw"], 11580)
        self.assertEqual(result["outcomes"][0]["refund_customer_flag"], 0)
        self.assertEqual(result["outcomes"][0]["unsubscribe_60d"], 0)

    def test_assignment_exactly_at_snapshot_is_pending_not_selected(self):
        source = fixture()
        result = build_policy_marts(source.observed, source.config, split="validation", as_of=iso(source.start))
        self.assertEqual(result["features"], [])
        self.assertEqual(result["outcomes"], [])
        self.assertEqual(result["eligibility_flow"]["d14_pending"], 1)
        self.assertEqual(result["eligibility_flow"]["assigned_total"], 0)
        partial = build_policy_marts(source.observed, source.config, split="validation", as_of=iso(source.start + timedelta(days=10)))
        self.assertEqual(partial["outcomes"][0]["days_to_first_repeat_paid"], 10.0)
        self.assertFalse(partial["outcomes"][0]["repeat_event_observed"])

    def test_simulation_namespace_separates_reused_local_ids_without_source_mutation(self):
        first = fixture("train")
        second = fixture("validation")
        for table in second.observed.values():
            for row in table:
                row["simulation_id"] = "validation-fixture"
        first_before, second_before = copy.deepcopy(first.observed), copy.deepcopy(second.observed)
        train = build_policy_marts(first.observed, first.config, split="train")
        validation = build_policy_marts(second.observed, second.config, split="validation")
        self.assertEqual(train["features"][0]["customer_id"], "fixture:c1")
        self.assertEqual(validation["features"][0]["customer_id"], "validation-fixture:c1")
        self.assertNotEqual(train["features"][0]["assignment_id"], validation["features"][0]["assignment_id"])
        for result in (train, validation):
            self.assertEqual(result["features"][0]["assignment_id"], result["outcomes"][0]["assignment_id"])
            self.assertEqual(result["metadata"]["identity_rule"], "simulation_id:local_id")
        again = build_policy_marts(first.observed, first.config, split="train")
        self.assertEqual(again, train)
        self.assertEqual(first.observed, first_before)
        self.assertEqual(second.observed, second_before)

    def test_legacy_train_entry_point_preserves_ids_and_rejects_other_splits(self):
        source = fixture("train")
        legacy = build_marts(source.observed, source.config)
        qualified = build_policy_marts(source.observed, source.config, split="train")
        self.assertEqual(legacy["features"][0]["customer_id"], "c1")
        for table in ("features", "outcomes"):
            for unqualified, namespaced in zip(legacy[table], qualified[table]):
                expected = dict(unqualified)
                for key in ("customer_id", "assignment_id"):
                    expected[key] = "fixture:" + expected[key]
                self.assertEqual(namespaced, expected)
        self.assertEqual(legacy["eligibility_flow"], qualified["eligibility_flow"])
        for split in ("validation", "final_test"):
            with self.assertRaisesRegex(ValueError, "only the train"):
                build_marts(source.observed, source.config, split=split)

    def test_invalid_scopes_mixed_namespaces_and_oracle_are_rejected(self):
        source = fixture()
        for split in ("all", "monitoring_only", "test", "embargo"):
            with self.subTest(split=split), self.assertRaises(ValueError):
                build_policy_marts(source.observed, source.config, split=split)
        mixed = copy.deepcopy(source.observed)
        mixed["customers"][0]["simulation_id"] = "another-simulation"
        with self.assertRaisesRegex(ValueError, "multiple simulation"):
            build_policy_marts(mixed, source.config, split="validation")
        with self.assertRaisesRegex(ValueError, "simulation identity"):
            build_policy_marts({table: [] for table in TABLE_COLUMNS}, source.config, split="validation")
        with self.assertRaisesRegex(ValueError, "Only observed"):
            build_policy_marts({**source.observed, "oracle": []}, source.config, split="validation")


if __name__ == "__main__":
    unittest.main()
