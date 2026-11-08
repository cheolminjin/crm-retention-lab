"""Reconstruct eligibility using only records available before assignment."""

from datetime import datetime

from .config import iso, parse_ts
from .schema import OPERATIONAL_CUSTOMER_EVENTS


def _timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value
    return parse_ts(value)


def evaluate_eligibility(customer_id, first_order, orders, order_events, customer_events, assigned_at):
    """Return a metadata-free audit row; never revise an existing assignment.

    Both occurrence and availability must be strictly before the cutoff. A
    subsequent cancellation/refund does not erase an earlier paid-order event.
    Missing permission and missing email status are treated as ineligible.
    """
    cutoff = _timestamp(assigned_at)
    reasons = []
    available_records = []

    def available(occurred, recorded):
        if occurred is None or recorded is None:
            return False
        happened, received = _timestamp(occurred), _timestamp(recorded)
        if happened < cutoff and received < cutoff:
            if received < happened:
                raise ValueError("A record cannot be available before its event")
            available_records.append(received)
            return True
        return False

    customer_orders = [order for order in orders if order["customer_id"] == customer_id]
    known_orders = [order for order in customer_orders if available(order["paid_at"], order["paid_recorded_at"])]
    order_ids = {order["order_id"] for order in customer_orders}
    relevant_order_events = [
        event for event in order_events
        if event["order_id"] in order_ids
        and event["event_type"] in {"paid", "delivered", "cancelled", "fully_refunded"}
        and available(event["occurred_at"], event["recorded_at"])
    ]
    first_id = None if first_order is None else first_order["order_id"]
    if first_order is None:
        reasons.append("first_order_missing")
    elif first_order["customer_id"] != customer_id:
        raise ValueError("first_order must belong to customer_id")
    else:
        known_ids = {order["order_id"] for order in known_orders}
        if first_id not in known_ids:
            reasons.append("first_order_not_available")
        if known_orders:
            earliest = min(known_orders, key=lambda order: (_timestamp(order["paid_at"]), order["order_id"]))
            if earliest["order_id"] != first_id:
                reasons.append("not_first_paid_order")
        if any(order["order_id"] != first_id for order in known_orders):
            reasons.append("additional_paid_order")
        delivered = available(first_order.get("delivered_at"), first_order.get("delivery_recorded_at"))
        first_events = [event for event in relevant_order_events if event["order_id"] == first_id]
        if not delivered and not any(event["event_type"] == "delivered" for event in first_events):
            reasons.append("first_delivery_not_available")
        if any(event["event_type"] == "cancelled" for event in first_events):
            reasons.append("first_order_cancelled")
        if any(event["event_type"] == "fully_refunded" for event in first_events):
            reasons.append("first_order_fully_refunded")

    state_events = [
        event for event in customer_events
        if event["customer_id"] == customer_id
        and event["event_type"] in OPERATIONAL_CUSTOMER_EVENTS
        and available(event["occurred_at"], event["recorded_at"])
    ]

    def state_is_enabled(positive, negative):
        events = [event for event in state_events if event["event_type"] in {positive, negative}]
        if not events:
            return False
        # Equal-time contradictory records resolve conservatively, independent
        # of file order. An event ID only settles otherwise identical records.
        latest = max(events, key=lambda event: (
            _timestamp(event["occurred_at"]), _timestamp(event["recorded_at"]),
            event["event_type"] == negative, event.get("event_id", ""),
        ))
        return latest["event_type"] == positive

    if not state_is_enabled("consent_granted", "consent_revoked"):
        reasons.append("consent_not_granted")
    if not state_is_enabled("email_enabled", "email_disabled"):
        reasons.append("email_not_enabled")
    return {
        "customer_id": customer_id,
        "evaluated_at": iso(cutoff),
        "eligible": not reasons,
        "reason_codes": reasons,
        "latest_available_record_at": iso(max(available_records)) if available_records else None,
    }
