"""Hand-calculated accounting and label-boundary regression cases."""

import copy
import json
from datetime import timedelta
from pathlib import Path
import unittest

from crm_retention_lab.config import iso, parse_ts
from crm_retention_lab.finance import build_ledger, price_order, settled_profit
from crm_retention_lab.schema import TABLE_COLUMNS, observed_row


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).resolve().parents[1] / "configs/design_v0_1.json").read_text(encoding="utf-8"))
        self.product = self.config["catalog"][1]
        self.start = "2025-01-20T09:00:00+09:00"
        self.assignment = {
            "assignment_id": "a1", "customer_id": "c1", "first_order_id": "first",
            "assigned_at": self.start, "arm": "coupon",
        }
        self.end = iso(parse_ts(self.start) + timedelta(days=60))
        self.settlement = iso(parse_ts(self.start) + timedelta(days=90))

    def order(self, order_id="repeat", paid_at=None, coupon=3000, customer_id="c1"):
        paid_at = paid_at or self.start
        return observed_row(
            "orders", "fixture", order_id=order_id, customer_id=customer_id,
            paid_at=paid_at, paid_recorded_at=paid_at, delivered_at=None,
            delivery_recorded_at=None, sku=self.product["sku"], quantity=1,
            coupon_assignment_id="a1" if coupon else None,
            **price_order(self.product, 1, 0, coupon, self.config["unit_economics"]),
        )

    def contact(self, **overrides):
        contact = {
            "assignment_id": "a1", "attempted_at": self.start,
            "delivered_at": None, "opened_at": None, "send_cost_krw": 20,
            "coupon_issued_at": self.start,
        }
        contact.update(overrides)
        return contact

    def test_hand_calculated_discounted_order_and_send_cost(self):
        order = self.order()
        ledger = build_ledger(order, self.product, self.config)
        # 25,000 + 3,000 - 12,000 - 3,000 - 700 - 700 = 11,600.
        self.assertEqual(sum(row["amount_krw"] for row in ledger), 11600)
        self.assertEqual(settled_profit([order], ledger, [self.contact()], self.assignment, self.config, self.settlement), 11580)
        self.assertEqual({row["entry_type"] for row in ledger}, {
            "net_item_revenue", "customer_shipping_charge", "cogs", "outbound_shipping", "fulfillment", "payment_fee",
        })
        for row in ledger:
            self.assertEqual(set(row), set(TABLE_COLUMNS["order_ledger"]))
            self.assertEqual(row["simulation_id"], "fixture")
            self.assertEqual(row["entry_id"], f"repeat:{row['entry_type']}")
            self.assertIs(type(row["amount_krw"]), int)

    def test_full_refund_and_partial_inventory_recovery(self):
        order = self.order()
        refund_at = parse_ts(self.start) + timedelta(days=7)
        ledger = build_ledger(order, self.product, self.config, refund_at, 0.5)
        amounts = {row["entry_type"]: row["amount_krw"] for row in ledger}
        self.assertEqual(amounts["refund"], -28000)
        self.assertEqual(amounts["cogs_recovery"], 6000)
        self.assertEqual(amounts["return_handling"], -3000)
        self.assertEqual(amounts["payment_fee"], -700)
        self.assertEqual(sum(amounts.values()), -13400)
        self.assertEqual(settled_profit([order], ledger, [self.contact()], self.assignment, self.config, self.settlement), -13420)

    def test_payment_fee_uses_decimal_half_up(self):
        order = self.order(coupon=0)
        order["item_revenue_after_discount_krw"] = 10
        order["customer_shipping_charge_krw"] = 0
        self.config["unit_economics"]["payment_fee_rate"] = 0.05
        ledger = build_ledger(order, self.product, self.config)
        self.assertEqual(next(row["amount_krw"] for row in ledger if row["entry_type"] == "payment_fee"), -1)

    def test_shipping_threshold_is_after_other_discount_before_coupon(self):
        product = {"list_price_krw": 40000}
        economics = self.config["unit_economics"]
        self.assertEqual(price_order(product, 1, 0, 3000, economics)["customer_shipping_charge_krw"], 0)
        self.assertEqual(price_order(product, 1, 1, 0, economics)["customer_shipping_charge_krw"], 3000)

    def test_quantity_multiplies_product_revenue_and_cogs_only(self):
        order = self.order(coupon=0)
        order.update(price_order(self.product, 2, 0, 0, self.config["unit_economics"]))
        order["quantity"] = 2
        ledger = build_ledger(order, self.product, self.config)
        # 56,000 - 24,000 - 3,000 - 700 - 1,400; shipping is free.
        self.assertEqual(sum(row["amount_krw"] for row in ledger), 26900)

    def test_unredeemed_coupon_and_failed_delivery_still_cost_only_send(self):
        self.assertEqual(settled_profit([], [], [self.contact()], self.assignment, self.config, self.settlement), -20)

    def test_later_clock_cannot_mature_an_older_observation_snapshot(self):
        order = self.order()
        ledger = build_ledger(order, self.product, self.config)
        self.config["population"]["observation_end_exclusive"] = iso(parse_ts(self.start) + timedelta(days=30))
        self.assertIsNone(settled_profit([order], ledger, [self.contact()], self.assignment,
                                        self.config, self.settlement))

    def test_immature_profit_is_null_even_with_known_purchases(self):
        order = self.order()
        ledger = build_ledger(order, self.product, self.config)
        before = iso(parse_ts(self.settlement) - timedelta(seconds=1))
        self.assertIsNone(settled_profit([order], ledger, [], self.assignment, self.config, before))
        self.assertEqual(settled_profit([order], ledger, [], self.assignment, self.config, self.settlement), 11600)

    def test_paid_window_includes_start_excludes_end_and_first_order(self):
        orders = [
            self.order("first", self.start), self.order("at_start", self.start),
            self.order("at_end", self.end),
            self.order("before", iso(parse_ts(self.start) - timedelta(seconds=1))),
            self.order("other_customer", self.start, customer_id="c2"),
        ]
        ledger = [entry for order in orders for entry in build_ledger(order, self.product, self.config)]
        self.assertEqual(settled_profit(orders, ledger, [], self.assignment, self.config, self.settlement), 11600)

    def test_ledger_freeze_excludes_exact_settlement_and_stays_frozen(self):
        order = self.order()
        ledger = build_ledger(order, self.product, self.config)
        ledger.extend([
            {"order_id": "repeat", "amount_krw": -10, "recorded_at": iso(parse_ts(self.settlement) - timedelta(seconds=1))},
            {"order_id": "repeat", "amount_krw": -100, "recorded_at": self.settlement},
            {"order_id": "repeat", "amount_krw": -1000, "recorded_at": iso(parse_ts(self.settlement) + timedelta(seconds=1))},
        ])
        later = iso(parse_ts(self.settlement) + timedelta(days=30))
        self.assertEqual(settled_profit([order], ledger, [], self.assignment, self.config, self.settlement), 11590)
        self.assertEqual(settled_profit([order], ledger, [], self.assignment, self.config, later), 11590)

    def test_late_payment_record_cannot_enter_a_frozen_label(self):
        order = self.order()
        ledger = build_ledger(order, self.product, self.config)
        order["paid_recorded_at"] = self.settlement
        self.assertEqual(settled_profit([order], ledger, [], self.assignment, self.config, self.settlement), 0)

    def test_contact_cost_is_linked_to_assignment(self):
        contacts = [self.contact(), self.contact(assignment_id="a2", send_cost_krw=999)]
        self.assertEqual(settled_profit([], [], contacts, self.assignment, self.config, self.settlement), -20)

    def test_a_a_keeps_normal_merchandise_costs(self):
        order = self.order(coupon=0)
        base_ledger = build_ledger(order, self.product, self.config)
        aa_config = copy.deepcopy(self.config)
        aa_config["runtime"] = {"scenario": "a_a_zero_cost"}
        self.assertEqual(build_ledger(order, self.product, aa_config), base_ledger)
        self.assertEqual(next(row["amount_krw"] for row in base_ledger if row["entry_type"] == "cogs"), -12000)

    def test_invalid_financial_inputs_are_rejected(self):
        for quantity in (0, -1, 1.5, True):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                price_order(self.product, quantity, 0, 0, self.config["unit_economics"])
        with self.assertRaises(ValueError):
            price_order(self.product, 1, 28000, 1, self.config["unit_economics"])
        for recovery in (-0.1, 1.1, float("nan")):
            with self.subTest(recovery=recovery), self.assertRaises(ValueError):
                build_ledger(self.order(), self.product, self.config, recovery_fraction=recovery)
        with self.assertRaises(ValueError):
            settled_profit([], [], [], self.assignment, self.config, "2026-01-01T00:00:00")


if __name__ == "__main__":
    unittest.main()
