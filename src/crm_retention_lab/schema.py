"""Public observed tables. Oracle state must never be added to this allowlist."""

SCHEMA_VERSION = "0.1.0"
COMMON = ("simulation_id", "schema_version")
TABLE_COLUMNS = {
    "customers": COMMON + (
        "customer_id", "created_at", "acquisition_channel", "acquisition_recorded_at",
    ),
    "orders": COMMON + (
        "order_id", "customer_id", "paid_at", "paid_recorded_at", "delivered_at",
        "delivery_recorded_at", "sku", "quantity", "list_subtotal_krw",
        "other_discount_krw", "crm_coupon_discount_krw",
        "item_revenue_after_discount_krw", "customer_shipping_charge_krw",
        "coupon_assignment_id",
    ),
    "order_events": COMMON + (
        "order_event_id", "order_id", "event_type", "occurred_at", "recorded_at",
    ),
    "order_ledger": COMMON + (
        "entry_id", "order_id", "entry_type", "amount_krw", "occurred_at", "recorded_at",
    ),
    "customer_events": COMMON + (
        "event_id", "customer_id", "event_type", "occurred_at", "recorded_at", "order_id",
    ),
    "assignments": COMMON + (
        "assignment_id", "customer_id", "first_order_id", "first_delivered_at",
        "assigned_at", "arm", "p_control", "p_info", "p_coupon", "eligibility_version",
    ),
    "contacts": COMMON + (
        "contact_id", "assignment_id", "attempted_at", "delivered_at", "opened_at",
        "clicked_at", "send_cost_krw", "coupon_issued_at", "coupon_expires_at",
    ),
    "eligibility_audit": COMMON + (
        "customer_id", "evaluated_at", "eligible", "reason_codes", "latest_available_record_at",
    ),
}

PRIMARY_KEYS = {
    "customers": "customer_id", "orders": "order_id", "order_events": "order_event_id",
    "order_ledger": "entry_id", "customer_events": "event_id",
    "assignments": "assignment_id", "contacts": "contact_id",
    "eligibility_audit": "customer_id",
}

OPERATIONAL_CUSTOMER_EVENTS = {
    "consent_granted", "consent_revoked", "email_enabled", "email_disabled",
}
ANALYTICS_CUSTOMER_EVENTS = {"session", "tip_view", "cart"}


def observed_row(table, simulation_id, **values):
    """Build a row without silently accepting hidden or unexpected columns."""
    row = {"simulation_id": simulation_id, "schema_version": SCHEMA_VERSION, **values}
    expected = set(TABLE_COLUMNS[table])
    if set(row) != expected:
        raise ValueError(f"{table}: missing={expected - set(row)}, extra={set(row) - expected}")
    return {key: row[key] for key in TABLE_COLUMNS[table]}
