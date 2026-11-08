"""As-of leakage, frozen labels, censoring and cohort-denominator checks."""

import copy
import json
from datetime import timedelta
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, parse_ts
from crm_retention_lab.finance import build_ledger, price_order
from crm_retention_lab.marts import FEATURE_COLUMNS, build_marts
from crm_retention_lab.schema import TABLE_COLUMNS, observed_row


class MartsTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).resolve().parents[1] / "configs/design_v0_1.json").read_text(encoding="utf-8"))
        self.observed = {table: [] for table in TABLE_COLUMNS}
        self.product = self.config["catalog"][1]
        self.start = parse_ts("2025-01-20T09:00:00+09:00")
        self.first, self.assignment = self.customer("c1", self.start, arm="coupon")
        self.append("contacts", contact_id="contact1", assignment_id="c1-a", attempted_at=iso(self.start),
                    delivered_at=None, opened_at=None, clicked_at=None, send_cost_krw=20,
                    coupon_issued_at=None, coupon_expires_at=None)

    def append(self, table, **values):
        row = observed_row(table, "fixture", **values)
        self.observed[table].append(row)
        return row

    def customer(self, cid, assigned_at, arm="control", eligible=True, reasons=None):
        delivered = assigned_at - timedelta(days=14)
        paid = delivered - timedelta(days=3)
        self.append("customers", customer_id=cid, created_at=iso(paid - timedelta(days=1)),
                    acquisition_channel="organic", acquisition_recorded_at=iso(paid - timedelta(days=1)))
        first = self.order(cid + "-first", paid, cid=cid, delivery=delivered)
        self.append("eligibility_audit", customer_id=cid, evaluated_at=iso(assigned_at),
                    eligible=eligible, reason_codes=reasons or [], latest_available_record_at=iso(delivered))
        assignment = None
        if eligible:
            assignment = self.append("assignments", assignment_id=cid + "-a", customer_id=cid,
                                     first_order_id=first["order_id"], first_delivered_at=iso(delivered),
                                     assigned_at=iso(assigned_at), arm=arm, p_control=1 / 3,
                                     p_info=1 / 3, p_coupon=1 / 3, eligibility_version="0.1.0")
        return first, assignment

    def order(self, oid, paid, cid="c1", coupon=0, delivery=None, refund=None, quantity=1, other=0):
        row = self.append(
            "orders", order_id=oid, customer_id=cid, paid_at=iso(paid), paid_recorded_at=iso(paid),
            delivered_at=iso(delivery) if delivery else None,
            delivery_recorded_at=iso(delivery) if delivery else None,
            sku=self.product["sku"], quantity=quantity,
            coupon_assignment_id=cid + "-a" if coupon else None,
            **price_order(self.product, quantity, other, coupon, self.config["unit_economics"]),
        )
        self.observed["order_ledger"].extend(build_ledger(row, self.product, self.config, refund_at=refund))
        return row

    def event(self, kind, occurred, recorded=None, cid="c1"):
        return self.append("customer_events", event_id="e" + str(len(self.observed["customer_events"])),
                           customer_id=cid, event_type=kind, occurred_at=iso(occurred),
                           recorded_at=iso(recorded or occurred), order_id=None)

    def test_mature_hand_calculated_profit_and_separate_campaign_spend(self):
        self.order("repeat", self.start + timedelta(days=1), coupon=3000)
        marts = build_marts(self.observed, self.config)
        feature, outcome = marts["features"][0], marts["outcomes"][0]
        self.assertEqual(outcome["contribution_profit_60d_krw"], 11580)
        self.assertEqual(outcome["actual_campaign_spend_krw"], 3020)
        self.assertEqual(outcome["repeat_paid_within_60d"], 1)
        self.assertEqual(outcome["order_count_60d"], 1)
        self.assertEqual(outcome["label_freeze_at"], iso(self.start + timedelta(days=90)))
        self.assertEqual(feature["first_pack_grams"], 500)
        self.assertEqual(feature["first_quantity"], 1)
        self.assertEqual(feature["first_paid_amount_krw"], 31000)
        self.assertEqual(feature["delivery_lead_days"], 3.0)
        self.assertIsNone(feature["days_since_last_session"])

    def test_pre_assignment_features_require_both_times_and_delivery_window(self):
        delivery = parse_ts(self.first["delivered_at"])
        self.event("session", delivery)
        self.event("session", self.start - timedelta(days=2), self.start - timedelta(days=1))
        self.event("session", self.start - timedelta(days=1), self.start)
        self.event("session", self.start)
        self.event("session", delivery - timedelta(seconds=1))
        self.event("tip_view", self.start - timedelta(hours=4))
        self.event("cart", self.start - timedelta(hours=2), self.start + timedelta(days=1))
        self.event("consent_revoked", self.start + timedelta(days=1))
        feature = build_marts(self.observed, self.config)["features"][0]
        self.assertEqual(feature["sessions_d0_d13"], 2)
        self.assertEqual(feature["tip_views_d0_d13"], 1)
        self.assertEqual(feature["cart_events_d0_d13"], 0)
        self.assertEqual(feature["days_since_last_session"], 2.0)

    def test_future_recorded_acquisition_is_missing_and_required_order_is_rejected(self):
        self.observed["customers"][0]["acquisition_recorded_at"] = iso(self.start)
        self.assertIsNone(build_marts(self.observed, self.config)["features"][0]["acquisition_channel"])
        self.first["paid_recorded_at"] = iso(self.start)
        with self.assertRaisesRegex(ValueError, "known before assignment"):
            build_marts(self.observed, self.config)

    def test_all_final_labels_stay_null_until_ninety_days(self):
        self.order("repeat", self.start + timedelta(days=4))
        outcome = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=70)))["outcomes"][0]
        self.assertTrue(outcome["is_outcome_mature"])
        self.assertFalse(outcome["is_profit_settled"])
        self.assertTrue(outcome["repeat_event_observed"])
        self.assertEqual(outcome["days_to_first_repeat_paid"], 4.0)
        for column in ("repeat_paid_within_60d", "order_count_60d", "contribution_profit_60d_krw", "refund_amount_krw", "refund_customer_flag", "unsubscribe_60d", "actual_campaign_spend_krw", "label_freeze_at"):
            self.assertIsNone(outcome[column], column)
        exact = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=90)))["outcomes"][0]
        self.assertTrue(exact["is_profit_settled"])
        self.assertEqual(exact["repeat_paid_within_60d"], 1)

    def test_partial_followup_censors_at_snapshot_and_excludes_exact_boundary(self):
        self.order("at_cutoff", self.start + timedelta(days=10))
        outcome = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=10)))["outcomes"][0]
        self.assertFalse(outcome["repeat_event_observed"])
        self.assertEqual(outcome["days_to_first_repeat_paid"], 10.0)
        self.assertFalse(outcome["is_outcome_mature"])
        outcome = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=11)))["outcomes"][0]
        self.assertTrue(outcome["repeat_event_observed"])
        self.assertEqual(outcome["days_to_first_repeat_paid"], 10.0)

    def test_partial_survival_cannot_use_a_late_payment_record(self):
        order = self.order("late", self.start + timedelta(days=3))
        order["paid_recorded_at"] = iso(self.start + timedelta(days=12))
        outcome = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=10)))["outcomes"][0]
        self.assertFalse(outcome["repeat_event_observed"])
        self.assertEqual(outcome["days_to_first_repeat_paid"], 10.0)

    def test_day_sixty_is_excluded_and_no_purchase_retains_send_cost(self):
        self.order("day60", self.start + timedelta(days=60), coupon=3000)
        outcome = build_marts(self.observed, self.config)["outcomes"][0]
        self.assertEqual(outcome["repeat_paid_within_60d"], 0)
        self.assertEqual(outcome["order_count_60d"], 0)
        self.assertEqual(outcome["contribution_profit_60d_krw"], -20)
        self.assertEqual(outcome["actual_campaign_spend_krw"], 20)
        self.assertEqual(outcome["days_to_first_repeat_paid"], 60.0)

    def test_repeat_paid_event_survives_refund_but_first_refund_is_excluded(self):
        first_entries = build_ledger(self.first, self.product, self.config, refund_at=self.start + timedelta(days=1))
        self.observed["order_ledger"] = first_entries
        self.order("repeat", self.start + timedelta(days=2), coupon=3000, refund=self.start + timedelta(days=5))
        outcome = build_marts(self.observed, self.config)["outcomes"][0]
        self.assertTrue(outcome["repeat_event_observed"])
        self.assertEqual(outcome["repeat_paid_within_60d"], 1)
        self.assertEqual(outcome["refund_customer_flag"], 1)
        self.assertEqual(outcome["refund_amount_krw"], 28000)
        self.assertEqual(outcome["contribution_profit_60d_krw"], -19420)
        self.assertEqual(len(build_marts(self.observed, self.config)["features"]), 1)

    def test_only_initial_order_refund_does_not_create_outcome_refund(self):
        self.observed["order_ledger"] = build_ledger(self.first, self.product, self.config, refund_at=self.start + timedelta(days=1))
        outcome = build_marts(self.observed, self.config)["outcomes"][0]
        self.assertEqual(outcome["refund_amount_krw"], 0)
        self.assertEqual(outcome["refund_customer_flag"], 0)
        self.assertEqual(outcome["contribution_profit_60d_krw"], -20)

    def test_labels_freeze_before_settlement_including_nonledger_events(self):
        self.order("repeat", self.start + timedelta(days=2), coupon=3000)
        settlement = self.start + timedelta(days=90)
        self.append("order_ledger", entry_id="late-refund", order_id="repeat", entry_type="refund", amount_krw=-28000,
                    occurred_at=iso(self.start + timedelta(days=10)), recorded_at=iso(settlement))
        self.event("consent_revoked", self.start + timedelta(days=2), settlement)
        self.event("consent_revoked", self.start + timedelta(days=60))
        outcome = build_marts(self.observed, self.config)["outcomes"][0]
        self.assertEqual(outcome["refund_amount_krw"], 0)
        self.assertEqual(outcome["contribution_profit_60d_krw"], 11580)
        self.assertEqual(outcome["unsubscribe_60d"], 0)
        self.event("consent_revoked", self.start + timedelta(days=3), settlement - timedelta(seconds=1))
        self.assertEqual(build_marts(self.observed, self.config)["outcomes"][0]["unsubscribe_60d"], 1)

    def test_flow_keeps_pending_ineligible_and_overlapping_reasons(self):
        self.customer("pending", self.start + timedelta(days=9))
        self.customer("excluded", self.start - timedelta(days=1), eligible=False,
                      reasons=["additional_paid_order", "consent_not_granted"])
        marts = build_marts(self.observed, self.config, as_of=iso(self.start + timedelta(days=5)))
        flow = marts["eligibility_flow"]
        self.assertEqual(flow["first_delivery_customers"], 3)
        self.assertEqual(flow["d14_reached"], 2)
        self.assertEqual(flow["d14_pending"], 1)
        self.assertEqual(flow["eligible"], 1)
        self.assertEqual(flow["ineligible"], 1)
        self.assertEqual(flow["assigned_total"], 1)
        self.assertEqual(flow["assigned_by_arm"], {"control": 0, "info": 0, "coupon": 1})
        self.assertTrue(flow["exclusion_reasons_overlap"])
        self.assertEqual(sum(flow["exclusion_reason_counts"].values()), 2)

    def test_train_end_assignment_and_later_cohorts_never_enter_analysis(self):
        self.customer("train_end", parse_ts(self.config["splits"]["train"]["end_exclusive"]))
        self.customer("validation", parse_ts("2025-10-02T09:00:00+09:00"))
        marts = build_marts(self.observed, self.config)
        self.assertEqual([row["customer_id"] for row in marts["features"]], ["c1"])
        self.assertEqual(marts["eligibility_flow"]["first_delivery_customers"], 1)
        self.assertEqual(marts["metadata"]["input_first_delivery_customers_known_as_of"], 3)
        self.assertEqual(marts["metadata"]["analysis_scope"], "train")
        with self.assertRaisesRegex(ValueError, "only the train"):
            build_marts(self.observed, self.config, split="validation")

    def test_requested_date_cannot_mature_a_stale_snapshot_or_access_test_period(self):
        capped = build_marts(self.observed, self.config, as_of="2030-01-01T00:00:00+09:00")
        self.assertEqual(capped["metadata"]["as_of"], self.config["splits"]["train_labels_available_by"])
        self.config["population"]["observation_end_exclusive"] = iso(self.start + timedelta(days=70))
        stale = build_marts(self.observed, self.config, as_of="2030-01-01T00:00:00+09:00")
        self.assertFalse(stale["outcomes"][0]["is_profit_settled"])
        self.assertIsNone(stale["outcomes"][0]["contribution_profit_60d_krw"])

    def test_feature_allowlist_excludes_metadata_posttreatment_and_oracle(self):
        marts = build_marts(self.observed, self.config)
        self.assertEqual(marts["metadata"]["feature_columns"], list(FEATURE_COLUMNS))
        for forbidden in ("arm", "customer_id", "assignment_id", "coupon_used", "price_sensitivity", "opened_at"):
            self.assertNotIn(forbidden, marts["metadata"]["feature_columns"])
        self.observed["oracle"] = []
        with self.assertRaisesRegex(ValueError, "Only observed"):
            build_marts(self.observed, self.config)

    def test_snapshot_before_assignment_has_pending_flow_and_no_features(self):
        marts = build_marts(self.observed, self.config, as_of=iso(self.start))
        self.assertEqual(marts["features"], [])
        self.assertEqual(marts["outcomes"], [])
        self.assertEqual(marts["eligibility_flow"]["d14_pending"], 1)
        self.assertEqual(marts["eligibility_flow"]["assigned_total"], 0)

    def test_build_is_pure_and_rejects_mixed_runs_or_naive_timestamps(self):
        snapshot = copy.deepcopy(self.observed)
        build_marts(self.observed, self.config)
        self.assertEqual(self.observed, snapshot)
        with self.assertRaises(ValueError):
            build_marts(self.observed, self.config, as_of="2025-10-01T00:00:00")
        self.observed["contacts"][0]["simulation_id"] = "another-run"
        with self.assertRaisesRegex(ValueError, "multiple simulation"):
            build_marts(self.observed, self.config)


if __name__ == "__main__":
    unittest.main()
