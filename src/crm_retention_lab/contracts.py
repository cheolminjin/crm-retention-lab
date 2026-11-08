"""Validate observed data only, without consulting simulator oracle state.

Contract failures are returned as readable diagnostics rather than incidental
KeyError/TypeError exceptions. ``checks`` counts evaluated assertions by rule.
"""

import math
from collections import Counter, defaultdict
from datetime import timedelta

from .config import parse_ts, simulation_id
from .schema import (
    ANALYTICS_CUSTOMER_EVENTS, OPERATIONAL_CUSTOMER_EVENTS,
    PRIMARY_KEYS, SCHEMA_VERSION, TABLE_COLUMNS,
)

_NULLABLE = {
    "orders": {"delivered_at", "delivery_recorded_at", "coupon_assignment_id"},
    "customer_events": {"order_id"},
    "contacts": {"delivered_at", "opened_at", "clicked_at", "coupon_issued_at", "coupon_expires_at"},
    "eligibility_audit": {"latest_available_record_at"},
}
_LEDGER_POSITIVE = {"net_item_revenue", "customer_shipping_charge", "cogs_recovery"}
_LEDGER_NEGATIVE = {"refund", "cogs", "outbound_shipping", "fulfillment", "payment_fee", "return_handling"}
_INITIAL_ENTRIES = {"net_item_revenue", "customer_shipping_charge", "cogs", "outbound_shipping", "fulfillment", "payment_fee"}


def validate_dataset(observed, config):
    """Return valid/errors/check counts/row counts for the observed tables.

    ``reason_codes`` is the sole list-valued field (a list of strings). All
    other cells must be finite JSON scalars, with timezone-aware timestamps.
    No minimum arm sample size or stochastic significance check is imposed.
    """
    errors, checks, row_counts = [], Counter(), {}

    def check(condition, rule, message):
        checks[rule] += 1
        if not condition:
            errors.append(f"{rule}: {message}")
        return condition

    def result():
        return {"valid": not errors, "errors": errors, "checks": dict(checks), "row_counts": row_counts}

    if not check(isinstance(observed, dict), "tables", "observed must be a dictionary of tables"):
        return result()
    try:
        cutoff = parse_ts(config["population"]["observation_end_exclusive"])
        offset = timedelta(days=config["experiment"]["assignment_offset_days"])
        settle = timedelta(days=config["population"]["max_order_adjustment_recording_days_after_payment"])
        analytics_lag = timedelta(days=config["population"]["max_analytics_reporting_lag_days"])
        expected_customers = config["population"]["first_delivery_customers"]
        probabilities = {arm["id"]: arm["probability"] for arm in config["experiment"]["arms"]}
        catalog = {p["sku"]: p for p in config["catalog"]}
        offer, economics = config["offer"], config["unit_economics"]
        aa = config["runtime"]["scenario"] == "a_a_zero_cost"
        expected_simulation = simulation_id(config)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        check(False, "config", f"invalid validation configuration: {exc}")
        return result()

    check(set(observed) == set(TABLE_COLUMNS), "tables",
          f"missing={sorted(set(TABLE_COLUMNS) - set(observed))}, unexpected={sorted(set(observed) - set(TABLE_COLUMNS), key=str)}")
    tables, times, indexes = {}, {}, {}
    for table, columns in TABLE_COLUMNS.items():
        rows = observed.get(table, [])
        if not check(isinstance(rows, list), "table_type", f"{table} must contain a list of rows"):
            rows = []
        row_counts[table] = len(rows)
        tables[table], indexes[table] = [], {}
        for number, row in enumerate(rows):
            location = f"{table}[{number}]"
            if not check(isinstance(row, dict), "row_type", f"{location} must be an object"):
                continue
            expected, actual = set(columns), set(row)
            shape_ok = check(actual == expected, "columns",
                             f"{location} missing={sorted(expected - actual)}, unexpected={sorted(actual - expected, key=str)}")
            good = shape_ok
            for key in expected & actual:
                value = row[key]
                if key == "reason_codes":
                    scalar = isinstance(value, list) and all(isinstance(v, str) for v in value)
                else:
                    scalar = value is None or isinstance(value, (str, int, float, bool))
                if isinstance(value, float):
                    scalar = scalar and math.isfinite(value)
                good = check(scalar, "cell_type", f"{location}.{key} must be a finite JSON scalar (reason_codes: string list)") and good
                if value is None:
                    good = check(key in _NULLABLE.get(table, set()), "nullability", f"{location}.{key} cannot be null") and good
                    continue
                if key.endswith("_at"):
                    try:
                        timestamp = parse_ts(value)
                        times[id(row), key] = timestamp
                        if key != "coupon_expires_at":
                            good = check(timestamp < cutoff, "observation_cutoff", f"{location}.{key} is at/after observation cutoff") and good
                    except (TypeError, ValueError, OverflowError):
                        good = check(False, "timestamp", f"{location}.{key} must be a timezone-aware ISO timestamp") and good
                if key.endswith("_krw") or key == "quantity":
                    good = check(type(value) is int, "integer_amount", f"{location}.{key} must be an integer") and good
                    if key != "amount_krw" and type(value) is int:
                        good = check(value >= 0, "nonnegative_amount", f"{location}.{key} cannot be negative") and good
                elif key == "eligible":
                    good = check(type(value) is bool, "boolean_type", f"{location}.{key} must be a boolean") and good
                elif key not in {"p_control", "p_info", "p_coupon", "reason_codes"} and not key.endswith("_at"):
                    good = check(isinstance(value, str) and bool(value), "string_type", f"{location}.{key} must be a nonempty string") and good
            key = row.get(PRIMARY_KEYS[table])
            good = check(isinstance(key, str) and bool(key), "primary_key", f"{location} requires a nonempty string {PRIMARY_KEYS[table]}") and good
            if isinstance(key, str):
                check(key not in indexes[table], "primary_key_unique", f"{table}: duplicate {PRIMARY_KEYS[table]}={key}")
            check(row.get("schema_version") == SCHEMA_VERSION, "schema_version", f"{location} schema_version mismatch")
            check(row.get("simulation_id") == expected_simulation, "simulation_id", f"{location} simulation_id mismatch")
            if good:
                tables[table].append(row)
                indexes[table].setdefault(key, row)

    check(row_counts["customers"] == expected_customers, "population_count", "customer count differs from configured first-delivery population")

    def ts(row, key):
        return times.get((id(row), key))

    def before(left, right, rule, message, strict=False):
        if left is not None and right is not None:
            check(left < right if strict else left <= right, rule, message)

    def fk(row, key, target, nullable=False):
        value = row.get(key)
        if nullable and value is None:
            return None
        if check(isinstance(value, str) and value in indexes[target], "foreign_key", f"{key}={value!r} does not reference {target}"):
            return indexes[target][value]
        return None

    customer_orders, customer_events, order_events = defaultdict(list), defaultdict(list), defaultdict(list)
    assignment_by_customer, contacts_by_assignment, ledger_by_order = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in tables["customers"]:
        before(ts(row, "created_at"), ts(row, "acquisition_recorded_at"), "recording_order", f"customer {row['customer_id']} acquisition recorded before creation")
        if ts(row, "created_at") and ts(row, "acquisition_recorded_at"):
            check(ts(row, "acquisition_recorded_at") - ts(row, "created_at") <= analytics_lag, "analytics_lag", f"customer {row['customer_id']} acquisition lag exceeds limit")

    for row in tables["orders"]:
        customer = fk(row, "customer_id", "customers")
        fk(row, "coupon_assignment_id", "assignments", nullable=True)
        if customer:
            customer_orders[row["customer_id"]].append(row)
            before(ts(customer, "created_at"), ts(row, "paid_at"), "order_sequence", f"order {row['order_id']} precedes customer creation")
        check(ts(row, "paid_at") == ts(row, "paid_recorded_at"), "operational_lag", f"order {row['order_id']} payment must record immediately")
        check((row["delivered_at"] is None) == (row["delivery_recorded_at"] is None), "delivery_nullability", f"order {row['order_id']} delivery timestamps must both be null or present")
        check(ts(row, "delivered_at") == ts(row, "delivery_recorded_at"), "operational_lag", f"order {row['order_id']} delivery must record immediately")
        before(ts(row, "paid_at"), ts(row, "delivered_at"), "order_sequence", f"order {row['order_id']} delivered before payment")
        check(row["quantity"] > 0, "quantity", f"order {row['order_id']} quantity must be positive")
        product = catalog.get(row["sku"]) if isinstance(row["sku"], str) else None
        if check(product is not None, "catalog", f"order {row['order_id']} unknown SKU {row['sku']!r}"):
            try:
                from .finance import price_order
                expected = price_order(product, row["quantity"], row["other_discount_krw"], row["crm_coupon_discount_krw"], economics)
                for key, value in expected.items():
                    check(row.get(key) == value, "order_pricing", f"order {row['order_id']} {key}: expected {value}, got {row.get(key)!r}")
            except (ValueError, TypeError, ArithmeticError) as exc:
                check(False, "order_pricing", f"order {row['order_id']} invalid price: {exc}")

    for row in tables["order_events"]:
        order = fk(row, "order_id", "orders")
        check(row["event_type"] in {"paid", "delivered", "cancelled", "fully_refunded"}, "order_event_type", f"unknown order event {row['event_type']!r}")
        check(ts(row, "occurred_at") == ts(row, "recorded_at"), "operational_lag", f"order event {row['order_event_id']} must record immediately")
        if order:
            order_events[row["order_id"]].append(row)
            before(ts(order, "paid_at"), ts(row, "occurred_at"), "order_sequence", f"event {row['order_event_id']} precedes payment")
            if row["event_type"] == "paid":
                check(ts(row, "occurred_at") == ts(order, "paid_at"), "order_event_consistency", f"paid event differs from order {row['order_id']}")
            if row["event_type"] == "delivered":
                check(ts(row, "occurred_at") == ts(order, "delivered_at"), "order_event_consistency", f"delivery event differs from order {row['order_id']}")

    for row in tables["customer_events"]:
        customer = fk(row, "customer_id", "customers")
        order = fk(row, "order_id", "orders", nullable=True)
        event_type = row["event_type"]
        check(event_type in OPERATIONAL_CUSTOMER_EVENTS | ANALYTICS_CUSTOMER_EVENTS, "customer_event_type", f"unknown customer event {event_type!r}")
        before(ts(row, "occurred_at"), ts(row, "recorded_at"), "recording_order", f"event {row['event_id']} recorded before occurrence")
        if customer:
            customer_events[row["customer_id"]].append(row)
            before(ts(customer, "created_at"), ts(row, "occurred_at"), "customer_event_sequence", f"event {row['event_id']} precedes customer creation")
        if order:
            check(order["customer_id"] == row["customer_id"], "order_customer", f"event {row['event_id']} belongs to another customer's order")
        if event_type in OPERATIONAL_CUSTOMER_EVENTS:
            check(ts(row, "occurred_at") == ts(row, "recorded_at"), "operational_lag", f"event {row['event_id']} must record immediately for eligibility")
        elif ts(row, "occurred_at") and ts(row, "recorded_at"):
            check(ts(row, "recorded_at") - ts(row, "occurred_at") <= analytics_lag, "analytics_lag", f"event {row['event_id']} reporting lag exceeds limit")

    for row in tables["assignments"]:
        customer = fk(row, "customer_id", "customers")
        first = fk(row, "first_order_id", "orders")
        if customer:
            assignment_by_customer[row["customer_id"]].append(row)
        check(row["arm"] in probabilities, "assignment_arm", f"assignment {row['assignment_id']} unknown arm")
        check(row["eligibility_version"] == SCHEMA_VERSION, "eligibility_version", f"assignment {row['assignment_id']} eligibility version mismatch")
        valid_probs = all(type(row[f"p_{arm}"]) in (int, float) and 0 < row[f"p_{arm}"] < 1 and math.isfinite(row[f"p_{arm}"]) for arm in probabilities)
        if check(valid_probs, "assignment_probability", f"assignment {row['assignment_id']} requires positive finite probabilities"):
            check(math.isclose(sum(row[f"p_{arm}"] for arm in probabilities), 1.0, abs_tol=1e-12), "assignment_probability", f"assignment {row['assignment_id']} probabilities must sum to one")
            for arm, probability in probabilities.items():
                check(math.isclose(row[f"p_{arm}"], probability, abs_tol=1e-12), "assignment_probability", f"assignment {row['assignment_id']} probability differs from configured {arm}")
        if first:
            check(first["customer_id"] == row["customer_id"], "assignment_first_order", f"assignment {row['assignment_id']} refers to another customer's order")
            check(ts(first, "delivered_at") == ts(row, "first_delivered_at"), "assignment_first_order", f"assignment {row['assignment_id']} first delivery differs from order")
            if ts(first, "delivered_at"):
                check(ts(row, "assigned_at") == ts(first, "delivered_at") + offset, "assignment_time", f"assignment {row['assignment_id']} must be first delivery + {offset.days} days")
        if ts(row, "assigned_at"):
            check(ts(row, "assigned_at").strftime("%H:%M:%S") == "09:00:00", "assignment_time", f"assignment {row['assignment_id']} must use the 09:00 slot")
    for customer_id, rows in assignment_by_customer.items():
        check(len(rows) == 1, "assignment_unique_customer", f"customer {customer_id} has {len(rows)} assignments")

    for row in tables["contacts"]:
        assignment = fk(row, "assignment_id", "assignments")
        if not assignment:
            continue
        contacts_by_assignment[row["assignment_id"]].append(row)
        check(assignment["arm"] != "control", "control_contact", f"control assignment {row['assignment_id']} cannot have contacts")
        before(ts(assignment, "assigned_at"), ts(row, "attempted_at"), "contact_time", f"contact {row['contact_id']} attempt precedes assignment")
        check(row["send_cost_krw"] == (0 if aa else offer["send_cost_krw_per_attempt"]), "contact_cost", f"contact {row['contact_id']} incorrect attempt cost")
        before(ts(row, "attempted_at"), ts(row, "delivered_at"), "contact_time", f"contact {row['contact_id']} delivered before attempted")
        for key in ("opened_at", "clicked_at"):
            if row[key] is not None:
                check(row["delivered_at"] is not None, "contact_time", f"contact {row['contact_id']} {key} without delivery")
                before(ts(row, "delivered_at"), ts(row, key), "contact_time", f"contact {row['contact_id']} {key} precedes delivery")
        if row["clicked_at"] is not None:
            check(row["opened_at"] is not None, "contact_time", f"contact {row['contact_id']} clicked without opened_at")
            before(ts(row, "opened_at"), ts(row, "clicked_at"), "contact_time", f"contact {row['contact_id']} clicked before open")
        coupon_present = row["coupon_issued_at"] is not None
        check(coupon_present == (row["coupon_expires_at"] is not None), "coupon_issuance", f"contact {row['contact_id']} issued/expiry must both be present or null")
        check(coupon_present == (assignment["arm"] == "coupon" and row["delivered_at"] is not None), "coupon_issuance", f"contact {row['contact_id']} coupon issuance must match delivered coupon contact")
        if coupon_present:
            check(assignment["arm"] == "coupon", "coupon_issuance", f"contact {row['contact_id']} issued coupon outside coupon arm")
            check(row["delivered_at"] is not None, "coupon_issuance", f"contact {row['contact_id']} issued coupon without delivery")
            before(ts(row, "delivered_at"), ts(row, "coupon_issued_at"), "coupon_issuance", f"contact {row['contact_id']} coupon precedes delivery")
            if ts(row, "coupon_issued_at"):
                check(ts(row, "coupon_expires_at") == ts(row, "coupon_issued_at") + timedelta(days=offer["coupon_valid_days"]), "coupon_issuance", f"contact {row['contact_id']} incorrect validity period")
    for assignment in tables["assignments"]:
        count = len(contacts_by_assignment[assignment["assignment_id"]])
        check(count == (0 if assignment["arm"] == "control" else 1), "contact_count", f"assignment {assignment['assignment_id']} has {count} contacts")

    redeemed = Counter()
    for order in tables["orders"]:
        assignment_id = order["coupon_assignment_id"]
        discount = order["crm_coupon_discount_krw"]
        check((assignment_id is not None) == (discount > 0), "coupon_redemption", f"order {order['order_id']} coupon reference/discount disagree")
        if not assignment_id:
            continue
        redeemed[assignment_id] += 1
        assignment = indexes["assignments"].get(assignment_id)
        if not assignment:
            continue
        check(not aa and assignment["arm"] == "coupon", "coupon_redemption", f"order {order['order_id']} redemption outside coupon arm/scenario")
        check(assignment["customer_id"] == order["customer_id"], "coupon_ownership", f"order {order['order_id']} used another customer's coupon")
        check(discount == offer["coupon_discount_krw"], "coupon_discount", f"order {order['order_id']} incorrect coupon amount")
        check(order["list_subtotal_krw"] >= offer["coupon_min_list_subtotal_krw"], "coupon_minimum", f"order {order['order_id']} below coupon minimum")
        if not offer["allow_stacking"]:
            check(order["other_discount_krw"] == 0, "coupon_stacking", f"order {order['order_id']} stacks discounts")
        contacts = contacts_by_assignment[assignment_id]
        if check(len(contacts) == 1, "coupon_issuance", f"order {order['order_id']} requires one issuing contact"):
            contact = contacts[0]
            check(contact["coupon_issued_at"] is not None, "coupon_issuance", f"order {order['order_id']} redeems an unissued coupon")
            before(ts(contact, "coupon_issued_at"), ts(order, "paid_at"), "coupon_window", f"order {order['order_id']} precedes coupon issuance")
            before(ts(order, "paid_at"), ts(contact, "coupon_expires_at"), "coupon_window", f"order {order['order_id']} coupon expired", strict=True)
    for assignment_id, count in redeemed.items():
        check(count <= offer["coupon_max_redemptions"], "coupon_single_use", f"assignment {assignment_id} redeemed {count} times")

    for row in tables["order_ledger"]:
        order = fk(row, "order_id", "orders")
        entry_type, amount = row["entry_type"], row["amount_krw"]
        check(entry_type in _LEDGER_POSITIVE | _LEDGER_NEGATIVE, "ledger_type", f"entry {row['entry_id']} unsupported type {entry_type!r}; coupon cannot be deducted again")
        if entry_type in _LEDGER_POSITIVE:
            check(amount >= 0, "ledger_sign", f"entry {row['entry_id']} must be nonnegative")
        if entry_type in _LEDGER_NEGATIVE:
            check(amount <= 0, "ledger_sign", f"entry {row['entry_id']} must be nonpositive")
        before(ts(row, "occurred_at"), ts(row, "recorded_at"), "recording_order", f"entry {row['entry_id']} recorded before occurrence")
        if order:
            ledger_by_order[row["order_id"]].append(row)
            before(ts(order, "paid_at"), ts(row, "occurred_at"), "ledger_time", f"entry {row['entry_id']} precedes payment")
            if ts(order, "paid_at"):
                before(ts(row, "recorded_at"), ts(order, "paid_at") + settle, "settlement_limit", f"entry {row['entry_id']} exceeds {settle.days}-day settlement limit")
            if entry_type in _INITIAL_ENTRIES:
                check(ts(row, "occurred_at") == ts(order, "paid_at") and ts(row, "recorded_at") == ts(order, "paid_recorded_at"), "ledger_time", f"initial entry {row['entry_id']} must match payment")

    for order in tables["orders"]:
        entries = ledger_by_order[order["order_id"]]
        by_type = defaultdict(list)
        for entry in entries:
            by_type[entry["entry_type"]].append(entry)
        for entry_type in sorted(_INITIAL_ENTRIES):
            check(len(by_type[entry_type]) == 1, "ledger_completeness", f"order {order['order_id']} requires exactly one {entry_type}")
        for entry_type, rows in by_type.items():
            check(len(rows) <= 1, "ledger_entry_unique", f"order {order['order_id']} duplicate {entry_type} can double count costs")
        product = catalog.get(order["sku"]) if isinstance(order["sku"], str) else None
        if product:
            from .finance import build_ledger
            try:
                expected_entries = build_ledger(order, product, config)
                for expected in expected_entries:
                    for actual in by_type[expected["entry_type"]]:
                        check(actual["amount_krw"] == expected["amount_krw"], "ledger_amount", f"order {order['order_id']} {expected['entry_type']} expected {expected['amount_krw']}, got {actual['amount_krw']}")
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                check(False, "ledger_amount", f"order {order['order_id']} invalid economics: {exc}")
        statuses = order_events[order["order_id"]]
        paid_events = [e for e in statuses if e["event_type"] == "paid"]
        delivered_events = [e for e in statuses if e["event_type"] == "delivered"]
        check(len(paid_events) == 1, "order_event_completeness", f"order {order['order_id']} needs one paid event")
        check(len(delivered_events) == (1 if order["delivered_at"] else 0), "order_event_completeness", f"order {order['order_id']} delivery event disagrees with delivery state")
        refunds = [e for e in statuses if e["event_type"] in {"fully_refunded", "cancelled"}]
        has_refund = bool(by_type["refund"])
        check(has_refund == bool(refunds), "refund_consistency", f"order {order['order_id']} refund state and ledger disagree")
        for entry_type in ("cogs_recovery", "return_handling"):
            check(len(by_type[entry_type]) == (1 if has_refund else 0), "refund_completeness", f"order {order['order_id']} requires one {entry_type} per refund")
        for entry in by_type["refund"]:
            check(entry["amount_krw"] == -(order["item_revenue_after_discount_krw"] + order["customer_shipping_charge_krw"]), "refund_amount", f"order {order['order_id']} refund differs from collected payment")
            check(any(ts(event, "occurred_at") == ts(entry, "occurred_at") for event in refunds), "refund_consistency", f"order {order['order_id']} refund event time differs from ledger")
        for entry in by_type["cogs_recovery"]:
            check(has_refund, "cogs_recovery", f"order {order['order_id']} recovery without refund")
            check(any(ts(refund, "occurred_at") == ts(entry, "occurred_at") for refund in by_type["refund"]), "refund_consistency", f"order {order['order_id']} recovery time differs from refund")
            if product:
                check(0 <= entry["amount_krw"] <= product["unit_cogs_krw"] * order["quantity"], "cogs_recovery", f"order {order['order_id']} recovered more than original cost")
        for entry in by_type["return_handling"]:
            check(has_refund and entry["amount_krw"] == -economics["return_handling_krw_per_return"], "return_handling", f"order {order['order_id']} incorrect return handling")
            check(any(ts(refund, "occurred_at") == ts(entry, "occurred_at") for refund in by_type["refund"]), "refund_consistency", f"order {order['order_id']} return handling time differs from refund")

    # Recompute D+14 audits with customer-local records; this stays linear in
    # customer count and never reads hidden traits or treatment potential outcomes.
    from .eligibility import evaluate_eligibility
    expected_audits = set()
    for customer_id, customer in indexes["customers"].items():
        orders = sorted(customer_orders[customer_id], key=lambda r: ts(r, "paid_at"))
        if not check(bool(orders), "first_order", f"customer {customer_id} has no first order"):
            continue
        first = orders[0]
        delivery = ts(first, "delivered_at")
        if not check(delivery is not None, "first_delivery", f"customer {customer_id} first order must be delivered"):
            continue
        check(delivery.strftime("%H:%M:%S") == "09:00:00", "first_delivery_slot", f"customer {customer_id} first delivery must be at 09:00")
        when = delivery + offset
        assigned = assignment_by_customer[customer_id]
        for assignment in assigned:
            check(assignment["first_order_id"] == first["order_id"], "assignment_first_order", f"assignment {assignment['assignment_id']} does not use earliest paid order")
        if when >= cutoff:
            check(not assigned, "pending_assignment", f"customer {customer_id} D+14 is not observed yet")
            check(customer_id not in indexes["eligibility_audit"], "pending_audit", f"customer {customer_id} should remain pending")
            continue
        expected_audits.add(customer_id)
        audit = indexes["eligibility_audit"].get(customer_id)
        if not check(audit is not None, "audit_completeness", f"customer {customer_id} missing D+14 audit"):
            continue
        check(ts(audit, "evaluated_at") == when, "audit_time", f"customer {customer_id} audit must be D+14")
        local_order_events = [event for order in orders for event in order_events[order["order_id"]]]
        try:
            expected = evaluate_eligibility(customer_id, first, orders, local_order_events, customer_events[customer_id], when)
            for key in ("eligible", "reason_codes", "latest_available_record_at"):
                check(audit[key] == expected[key], "eligibility_recomputed", f"customer {customer_id} audit {key} expected {expected[key]!r}, got {audit[key]!r}")
            check(type(audit["eligible"]) is bool, "audit_eligible_type", f"customer {customer_id} eligible must be boolean")
            check(bool(assigned) == expected["eligible"], "assignment_eligibility", f"customer {customer_id} assignment and recomputed eligibility disagree")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            check(False, "eligibility_recomputed", f"customer {customer_id} cannot recompute eligibility: {exc}")
    check(set(indexes["eligibility_audit"]) == expected_audits, "audit_population", "audit rows must exactly cover customers whose D+14 has arrived")
    for arm in probabilities:
        checks[f"assignments_{arm}"] = sum(row["arm"] == arm for row in tables["assignments"])
    return result()
