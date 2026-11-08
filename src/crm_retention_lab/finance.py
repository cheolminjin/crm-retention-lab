"""Integer-KRW order economics and frozen, intention-to-treat profit labels."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .config import iso, parse_ts
from .schema import observed_row


def _timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value
    return parse_ts(value)


def _decimal(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite nonnegative number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite nonnegative number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return result


def _krw(value, name):
    return int(_decimal(value, name).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("quantity must be a positive integer")
    return value


def price_order(product, quantity, other_discount_krw, crm_coupon_discount_krw, economics):
    """Snapshot price; the free-shipping threshold precedes the CRM coupon.

    Coupon eligibility/expiry and nonstacking are checked by the caller. This
    function only performs accounting and rejects discounts above the subtotal.
    """
    quantity = _quantity(quantity)
    subtotal = _krw(product["list_price_krw"], "list_price_krw") * quantity
    other = _krw(other_discount_krw, "other_discount_krw")
    coupon = _krw(crm_coupon_discount_krw, "crm_coupon_discount_krw")
    if other + coupon > subtotal:
        raise ValueError("Total discounts cannot exceed the list subtotal")
    if economics.get("shipping_threshold_basis", "pre_coupon_subtotal") != "pre_coupon_subtotal":
        raise ValueError("Only pre_coupon_subtotal shipping thresholds are supported")
    threshold = _krw(economics["free_shipping_min_subtotal_krw"], "free_shipping_min_subtotal_krw")
    shipping = 0 if subtotal - other >= threshold else _krw(
        economics["customer_shipping_charge_krw"], "customer_shipping_charge_krw"
    )
    return {
        "list_subtotal_krw": subtotal,
        "other_discount_krw": other,
        "crm_coupon_discount_krw": coupon,
        "item_revenue_after_discount_krw": subtotal - other - coupon,
        "customer_shipping_charge_krw": shipping,
    }


def build_ledger(order, product, config, refund_at=None, recovery_fraction=0.0):
    """Build signed ledger rows, retaining the order's simulation metadata.

    A full refund returns both the discounted item payment and shipping charge.
    The initial processing fee is retained. A/A changes campaign costs only;
    ordinary merchandise and fulfillment costs are identical in every scenario.
    """
    economics = config["unit_economics"]
    if economics.get("payment_fee_recovered_on_refund", False):
        raise ValueError("Stage 1 assumes payment fees are not recovered on refund")
    if economics.get("payment_fee_basis", "initial_collected_payment_including_shipping") != "initial_collected_payment_including_shipping":
        raise ValueError("Unsupported payment fee basis")
    paid_at = _timestamp(order["paid_at"])
    paid_recorded_at = _timestamp(order["paid_recorded_at"])
    if paid_recorded_at < paid_at:
        raise ValueError("Payment cannot be recorded before it occurs")
    quantity = _quantity(order["quantity"])
    item = _krw(order["item_revenue_after_discount_krw"], "item_revenue_after_discount_krw")
    shipping_charge = _krw(order["customer_shipping_charge_krw"], "customer_shipping_charge_krw")
    cogs = _krw(product["unit_cogs_krw"], "unit_cogs_krw") * quantity
    fee = _krw(Decimal(item + shipping_charge) * _decimal(economics["payment_fee_rate"], "payment_fee_rate"), "payment_fee")
    recovery = _decimal(recovery_fraction, "recovery_fraction")
    if recovery > 1:
        raise ValueError("recovery_fraction must be in [0, 1]")

    def row(entry_type, amount, occurred_at, recorded_at):
        result = observed_row(
            "order_ledger", order["simulation_id"],
            entry_id=f"{order['order_id']}:{entry_type}",
            order_id=order["order_id"], entry_type=entry_type, amount_krw=amount,
            occurred_at=iso(occurred_at), recorded_at=iso(recorded_at),
        )
        result["schema_version"] = order["schema_version"]
        return result

    amounts = (
        ("net_item_revenue", item),
        ("customer_shipping_charge", shipping_charge),
        ("cogs", -cogs),
        ("outbound_shipping", -_krw(economics["outbound_shipping_krw_per_order"], "outbound_shipping_krw_per_order")),
        ("fulfillment", -_krw(economics["fulfillment_krw_per_order"], "fulfillment_krw_per_order")),
        ("payment_fee", -fee),
    )
    rows = [row(kind, amount, paid_at, paid_recorded_at) for kind, amount in amounts]
    if refund_at is not None:
        refunded_at = _timestamp(refund_at)
        if refunded_at < paid_at:
            raise ValueError("Refund cannot occur before payment")
        refund_amounts = (
            ("refund", -(item + shipping_charge)),
            ("cogs_recovery", _krw(Decimal(cogs) * recovery, "cogs_recovery")),
            ("return_handling", -_krw(economics["return_handling_krw_per_return"], "return_handling_krw_per_return")),
        )
        rows.extend(row(kind, amount, refunded_at, refunded_at) for kind, amount in refund_amounts)
    return rows


def settled_profit(orders, ledger, contacts, assignment, config, as_of):
    """Return a mature, frozen customer outcome, or None before settlement.

    The paid-order window is [assignment, assignment + horizon). The ledger and
    payment records freeze strictly before settlement. Assignment membership is
    never changed based on subsequent delivery, opening, refund or unsubscribe.
    """
    snapshot = _timestamp(as_of)
    # A later wall-clock date cannot make a stale data snapshot mature.
    observation_cutoff = config.get("population", {}).get("observation_end_exclusive")
    if observation_cutoff is not None:
        snapshot = min(snapshot, _timestamp(observation_cutoff))
    start = _timestamp(assignment["assigned_at"])
    end = start + timedelta(days=config["experiment"]["outcome_horizon_days"])
    settlement = end + timedelta(days=config["experiment"]["settlement_lag_days"])
    if snapshot < settlement:
        return None
    included_ids = {
        order["order_id"] for order in orders
        if order["customer_id"] == assignment["customer_id"]
        and order["order_id"] != assignment["first_order_id"]
        and start <= _timestamp(order["paid_at"]) < end
        and _timestamp(order["paid_recorded_at"]) < settlement
    }
    profit = sum(
        entry["amount_krw"] for entry in ledger
        if entry["order_id"] in included_ids
        and _timestamp(entry["recorded_at"]) < settlement
    )
    send_cost = sum(
        _krw(contact["send_cost_krw"], "send_cost_krw") for contact in contacts
        if contact["assignment_id"] == assignment["assignment_id"]
        and start <= _timestamp(contact["attempted_at"]) < settlement
    )
    return profit - send_cost
