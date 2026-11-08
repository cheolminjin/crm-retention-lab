"""As-of eligibility, payment history and immutable-assignment safeguards."""

import copy
import unittest

from crm_retention_lab.eligibility import evaluate_eligibility


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = "2025-01-20T09:00:00+09:00"
        self.first = {
            "order_id": "first", "customer_id": "c1",
            "paid_at": "2025-01-01T09:00:00+09:00",
            "paid_recorded_at": "2025-01-01T09:00:00+09:00",
            "delivered_at": "2025-01-06T09:00:00+09:00",
            "delivery_recorded_at": "2025-01-06T09:00:00+09:00",
        }
        self.orders = [self.first]
        self.order_events = []
        self.events = [self.event("consent_granted", "2025-01-01T08:00:00+09:00"), self.event("email_enabled", "2025-01-01T08:00:00+09:00")]

    def event(self, kind, when, recorded_at=None, customer_id="c1"):
        return {
            "event_id": kind + when, "customer_id": customer_id, "event_type": kind,
            "occurred_at": when, "recorded_at": recorded_at or when, "order_id": None,
        }

    def order_event(self, kind, when, order_id="first", recorded_at=None):
        return {
            "order_event_id": kind + when, "order_id": order_id,
            "event_type": kind, "occurred_at": when, "recorded_at": recorded_at or when,
        }

    def evaluate(self):
        return evaluate_eligibility("c1", self.first, self.orders, self.order_events, self.events, self.cutoff)

    def test_eligible_first_buyer_has_deterministic_audit(self):
        result = self.evaluate()
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["latest_available_record_at"], self.first["delivery_recorded_at"])
        self.assertEqual(set(result), {"customer_id", "evaluated_at", "eligible", "reason_codes", "latest_available_record_at"})

    def test_additional_payment_excludes_even_if_refunded(self):
        second = dict(self.first, order_id="second", paid_at="2025-01-02T09:00:00+09:00", paid_recorded_at="2025-01-02T09:00:00+09:00")
        self.orders.append(second)
        self.order_events.append(self.order_event("fully_refunded", "2025-01-03T09:00:00+09:00", "second"))
        self.assertIn("additional_paid_order", self.evaluate()["reason_codes"])

    def test_proposed_first_order_must_be_earliest_paid_order(self):
        earlier = dict(self.first, order_id="earlier", paid_at="2024-12-30T09:00:00+09:00", paid_recorded_at="2024-12-30T09:00:00+09:00")
        self.orders.append(earlier)
        self.assertIn("not_first_paid_order", self.evaluate()["reason_codes"])

    def test_missing_first_order_and_unknown_permissions_fail_closed(self):
        result = evaluate_eligibility("c1", None, [], [], [], self.cutoff)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_codes"], ["first_order_missing", "consent_not_granted", "email_not_enabled"])
        self.assertIsNone(result["latest_available_record_at"])

    def test_missing_or_late_first_delivery_is_ineligible(self):
        self.first["delivery_recorded_at"] = self.cutoff
        self.assertIn("first_delivery_not_available", self.evaluate()["reason_codes"])
        self.first["delivered_at"] = None
        self.first["delivery_recorded_at"] = None
        self.order_events.append(self.order_event("delivered", "2025-01-06T09:00:00+09:00"))
        self.assertTrue(self.evaluate()["eligible"])

    def test_first_order_cancellation_and_full_refund_exclude(self):
        for kind, reason in (("cancelled", "first_order_cancelled"), ("fully_refunded", "first_order_fully_refunded")):
            with self.subTest(kind=kind):
                self.order_events = [self.order_event(kind, "2025-01-19T09:00:00+09:00")]
                self.assertIn(reason, self.evaluate()["reason_codes"])

    def test_future_and_exact_cutoff_events_do_not_change_assignment_eligibility(self):
        frozen = self.evaluate()
        self.events.extend([
            self.event("consent_revoked", self.cutoff),
            self.event("email_disabled", "2025-01-21T09:00:00+09:00"),
        ])
        self.order_events.append(self.order_event("fully_refunded", "2025-01-21T09:00:00+09:00"))
        self.orders.append(dict(self.first, order_id="at_assignment", paid_at=self.cutoff, paid_recorded_at=self.cutoff))
        self.assertEqual(self.evaluate(), frozen)

    def test_late_recording_is_not_backfilled_into_eligibility(self):
        frozen = self.evaluate()
        self.events.append(self.event("consent_revoked", "2025-01-19T09:00:00+09:00", self.cutoff))
        self.order_events.append(self.order_event("fully_refunded", "2025-01-19T09:00:00+09:00", recorded_at=self.cutoff))
        self.orders.append(dict(self.first, order_id="late", paid_at="2025-01-19T09:00:00+09:00", paid_recorded_at=self.cutoff))
        self.assertEqual(self.evaluate(), frozen)

    def test_current_permission_state_can_be_revoked_and_restored(self):
        self.events.append(self.event("consent_revoked", "2025-01-18T09:00:00+09:00"))
        self.assertIn("consent_not_granted", self.evaluate()["reason_codes"])
        self.events.append(self.event("consent_granted", "2025-01-19T09:00:00+09:00"))
        self.assertTrue(self.evaluate()["eligible"])
        self.events.append(self.event("email_disabled", "2025-01-19T10:00:00+09:00"))
        self.assertIn("email_not_enabled", self.evaluate()["reason_codes"])

    def test_conflicting_same_time_permission_is_conservative_and_order_invariant(self):
        when = "2025-01-19T09:00:00+09:00"
        self.events.extend([self.event("consent_granted", when), self.event("consent_revoked", when)])
        result = self.evaluate()
        self.assertFalse(result["eligible"])
        self.events.reverse()
        self.assertEqual(self.evaluate(), result)

    def test_unrelated_people_and_analytics_do_not_leak_into_audit(self):
        frozen = self.evaluate()
        self.events.append(self.event("session", "2025-01-19T09:00:00+09:00"))
        self.events.append(self.event("consent_revoked", "2025-01-19T09:00:00+09:00", customer_id="c2"))
        self.orders.append(dict(self.first, order_id="other", customer_id="c2"))
        self.assertEqual(self.evaluate(), frozen)

    def test_evaluation_does_not_mutate_inputs(self):
        snapshot = copy.deepcopy((self.first, self.orders, self.order_events, self.events))
        self.evaluate()
        self.assertEqual((self.first, self.orders, self.order_events, self.events), snapshot)

    def test_timezone_and_customer_mismatch_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_eligibility("c1", self.first, self.orders, [], self.events, "2025-01-20T09:00:00")
        with self.assertRaises(ValueError):
            evaluate_eligibility("c2", self.first, self.orders, [], self.events, self.cutoff)


if __name__ == "__main__":
    unittest.main()
