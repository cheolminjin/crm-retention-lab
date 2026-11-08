"""Training-only, as-of feature and outcome marts from observed tables.

Each source table is indexed once. Customer-local scans keep construction linear
in input rows; oracle state and later evaluation splits are never model inputs.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .config import iso, parse_ts
from .finance import settled_profit
from .schema import TABLE_COLUMNS


FEATURE_VERSION = "0.1.0"
FEATURE_COLUMNS = (
    "first_pack_grams", "first_quantity", "first_paid_amount_krw",
    "first_discount_rate", "delivery_lead_days", "acquisition_channel",
    "sessions_d0_d13", "tip_views_d0_d13", "cart_events_d0_d13",
    "days_since_last_session", "first_delivery_month",
)


def _timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value
    return parse_ts(value)


def _group(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return groups


def build_marts(observed, config, *, as_of=None, split="train"):
    """Keep the stage-2/3 public entry point restricted to training data."""
    if split != "train":
        raise ValueError("Stage 2 supports only the train split")
    return _build_scope_marts(observed, config, as_of=as_of, split=split)


def build_policy_marts(observed, config, *, split, as_of=None):
    """Build a separated policy split with simulation-qualified identities."""
    if split not in {"train", "validation", "final_test"}:
        raise ValueError("Policy marts require train, validation, or final_test")
    result = _build_scope_marts(observed, config, as_of=as_of, split=split)
    namespace = result["metadata"]["input_simulation_id"]
    if not namespace:
        raise ValueError("Policy split requires a simulation identity")
    for name in ("features", "outcomes"):
        for row in result[name]:
            for key in ("customer_id", "assignment_id"):
                row[key] = f"{namespace}:{row[key]}"
    result["metadata"].update(identity_namespace=namespace, identity_rule="simulation_id:local_id",
                              source_seed=config["reproducibility"]["base_seed"])
    return result


def _build_scope_marts(observed, config, *, as_of=None, split="train"):
    """Build training features, frozen labels, provisional KM data and flow.

    ``as_of`` is an exclusive knowledge cutoff, capped by both source coverage
    and the prespecified training readout. All finalized labels remain null
    until the 90-day settlement closes. Survival duration/event remain usable
    during follow-up; a non-event duration is the administrative censor time.
    """
    unknown_tables = set(observed) - set(TABLE_COLUMNS)
    if unknown_tables:
        raise ValueError(f"Only observed tables may enter marts: {sorted(unknown_tables)}")
    missing_tables = set(TABLE_COLUMNS) - set(observed)
    if missing_tables:
        raise ValueError(f"Missing observed tables: {sorted(missing_tables)}")
    cutoff = _timestamp(config["population"]["observation_end_exclusive"])
    readout_key = {"train": "train_labels_available_by", "validation": "policy_lock_at", "final_test": "final_readout_at"}[split]
    readout = _timestamp(config["splits"][readout_key])
    requested = _timestamp(as_of) if as_of is not None else None
    snapshot = min(cutoff, readout, requested) if requested is not None else min(cutoff, readout)
    train = config["splits"][split]
    train_start, train_end = _timestamp(train["start_inclusive"]), _timestamp(train["end_exclusive"])
    offset = timedelta(days=config["experiment"]["assignment_offset_days"])
    horizon = timedelta(days=config["experiment"]["outcome_horizon_days"])
    settlement_lag = timedelta(days=config["experiment"]["settlement_lag_days"])
    catalog = {product["sku"]: product for product in config["catalog"]}
    customers = {row["customer_id"]: row for row in observed["customers"]}
    orders_by_id = {row["order_id"]: row for row in observed["orders"]}
    orders_by_customer = _group(observed["orders"], "customer_id")
    ledger_by_order = _group(observed["order_ledger"], "order_id")
    events_by_customer = _group(observed["customer_events"], "customer_id")
    contacts_by_assignment = _group(observed["contacts"], "assignment_id")
    audits_by_customer = {row["customer_id"]: row for row in observed["eligibility_audit"]}
    simulation_ids = {row["simulation_id"] for table in observed.values() for row in table}
    if len(simulation_ids) > 1:
        raise ValueError("Cannot combine multiple simulation IDs in one mart")

    selected = [
        assignment for assignment in observed["assignments"]
        if train_start <= _timestamp(assignment["assigned_at"]) < train_end
        and _timestamp(assignment["assigned_at"]) < snapshot
    ]
    if len({row["customer_id"] for row in selected}) != len(selected):
        raise ValueError("A customer may have only one training assignment")
    features, outcomes = [], []
    for assignment in selected:
        cid, aid = assignment["customer_id"], assignment["assignment_id"]
        start = _timestamp(assignment["assigned_at"])
        end, settlement = start + horizon, start + horizon + settlement_lag
        first = orders_by_id[assignment["first_order_id"]]
        customer = customers[cid]
        if first["customer_id"] != cid:
            raise ValueError("First order does not belong to the assigned customer")
        if not (first["delivered_at"] and first["delivery_recorded_at"]):
            raise ValueError("First delivery must be known before assignment")
        paid, delivered = _timestamp(first["paid_at"]), _timestamp(first["delivered_at"])
        if not all(timestamp < start for timestamp in (
            paid, delivered, _timestamp(first["paid_recorded_at"]),
            _timestamp(first["delivery_recorded_at"]),
        )):
            raise ValueError("First purchase and delivery must be known before assignment")
        if _timestamp(customer["created_at"]) >= start:
            raise ValueError("Customer must exist before assignment")
        local_events = events_by_customer[cid]
        counts = Counter()
        last_session = None
        for event in local_events:
            kind = event["event_type"]
            if kind not in {"session", "tip_view", "cart"}:
                continue
            occurred = _timestamp(event["occurred_at"])
            if delivered <= occurred < start and _timestamp(event["recorded_at"]) < start:
                counts[kind] += 1
                if kind == "session" and (last_session is None or occurred > last_session):
                    last_session = occurred
        discount = first["other_discount_krw"] + first["crm_coupon_discount_krw"]
        features.append({
            "customer_id": cid, "assignment_id": aid, "arm": assignment["arm"],
            "assigned_at": iso(start), "feature_cutoff_at": iso(start),
            "feature_version": FEATURE_VERSION,
            "first_pack_grams": catalog[first["sku"]]["grams"],
            "first_quantity": first["quantity"],
            "first_paid_amount_krw": first["item_revenue_after_discount_krw"] + first["customer_shipping_charge_krw"],
            "first_discount_rate": discount / first["list_subtotal_krw"] if first["list_subtotal_krw"] else 0.0,
            "delivery_lead_days": (delivered - paid).total_seconds() / 86400,
            "acquisition_channel": customer["acquisition_channel"] if _timestamp(customer["acquisition_recorded_at"]) < start else None,
            "sessions_d0_d13": counts["session"], "tip_views_d0_d13": counts["tip_view"],
            "cart_events_d0_d13": counts["cart"],
            "days_since_last_session": (start - last_session).total_seconds() / 86400 if last_session else None,
            "first_delivery_month": delivered.month,
        })

        # The payment record persists even when the order is later refunded.
        local_orders = orders_by_customer[cid]
        record_cutoff = min(snapshot, settlement)
        censor = min(snapshot, end)
        known_window_orders = [
            order for order in local_orders
            if order["order_id"] != first["order_id"]
            and start <= _timestamp(order["paid_at"]) < censor
            and _timestamp(order["paid_recorded_at"]) < record_cutoff
        ]
        first_repeat = min((_timestamp(order["paid_at"]) for order in known_window_orders), default=None)
        settled = snapshot >= settlement
        outcome = {
            "customer_id": cid, "assignment_id": aid, "arm": assignment["arm"],
            "assigned_at": iso(start), "outcome_start_at": iso(start),
            "outcome_end_at": iso(end), "settlement_end_at": iso(settlement),
            "label_freeze_at": iso(settlement) if settled else None,
            "is_outcome_mature": snapshot >= end, "is_profit_settled": settled,
            "repeat_paid_within_60d": None,
            "days_to_first_repeat_paid": ((first_repeat or censor) - start).total_seconds() / 86400,
            "repeat_event_observed": first_repeat is not None,
            "order_count_60d": None, "contribution_profit_60d_krw": None,
            "refund_amount_krw": None, "refund_customer_flag": None,
            "unsubscribe_60d": None, "actual_campaign_spend_krw": None,
        }
        if settled:
            included_ledger = [
                entry for order in known_window_orders for entry in ledger_by_order[order["order_id"]]
                if _timestamp(entry["occurred_at"]) < settlement
                and _timestamp(entry["recorded_at"]) < settlement
            ]
            local_contacts = contacts_by_assignment[aid]
            refund_amount = -sum(entry["amount_krw"] for entry in included_ledger if entry["entry_type"] == "refund")
            send_cost = sum(
                contact["send_cost_krw"] for contact in local_contacts
                if start <= _timestamp(contact["attempted_at"]) < settlement
            )
            outcome.update({
                "repeat_paid_within_60d": int(first_repeat is not None),
                "order_count_60d": len(known_window_orders),
                "contribution_profit_60d_krw": settled_profit(
                    known_window_orders, included_ledger, local_contacts, assignment, config, iso(snapshot)
                ),
                "refund_amount_krw": refund_amount,
                "refund_customer_flag": int(any(entry["entry_type"] == "refund" for entry in included_ledger)),
                "unsubscribe_60d": int(any(
                    event["event_type"] == "consent_revoked"
                    and start <= _timestamp(event["occurred_at"]) < end
                    and _timestamp(event["recorded_at"]) < settlement
                    for event in local_events
                )),
                "actual_campaign_spend_krw": send_cost + sum(order["crm_coupon_discount_krw"] for order in known_window_orders),
            })
        outcomes.append(outcome)

    # Flow follows scheduled D+14 cohort membership, not the presence of an
    # assignment: ineligible and not-yet-evaluated customers stay in its denominator.
    flow = {
        "scope": f"first_delivery_known_as_of_and_scheduled_d14_in_{split}",
        "first_delivery_customers": 0, "d14_reached": 0, "d14_pending": 0,
        "eligible": 0, "ineligible": 0, "assigned_total": len(selected),
        "assigned_by_arm": {arm["id"]: 0 for arm in config["experiment"]["arms"]},
        "exclusion_reason_counts": {}, "exclusion_reasons_overlap": True,
    }
    for assignment in selected:
        flow["assigned_by_arm"][assignment["arm"]] += 1
    exclusion_reasons = Counter()
    known_deliveries = 0
    for cid, local_orders in orders_by_customer.items():
        known_orders = [
            order for order in local_orders
            if _timestamp(order["paid_at"]) < snapshot and _timestamp(order["paid_recorded_at"]) < snapshot
        ]
        if not known_orders:
            continue
        first = min(known_orders, key=lambda order: (_timestamp(order["paid_at"]), order["order_id"]))
        if (not first["delivered_at"] or not first["delivery_recorded_at"]
                or _timestamp(first["delivered_at"]) >= snapshot
                or _timestamp(first["delivery_recorded_at"]) >= snapshot):
            continue
        known_deliveries += 1
        scheduled = _timestamp(first["delivered_at"]) + offset
        if not train_start <= scheduled < train_end:
            continue
        flow["first_delivery_customers"] += 1
        if scheduled >= snapshot:
            flow["d14_pending"] += 1
            continue
        flow["d14_reached"] += 1
        audit = audits_by_customer.get(cid)
        if audit is None or _timestamp(audit["evaluated_at"]) != scheduled:
            raise ValueError(f"Missing or mistimed eligibility audit for {cid}")
        if audit["eligible"]:
            flow["eligible"] += 1
        else:
            flow["ineligible"] += 1
            exclusion_reasons.update(set(audit["reason_codes"]))
    flow["exclusion_reason_counts"] = dict(sorted(exclusion_reasons.items()))
    if flow["eligible"] != flow["assigned_total"]:
        raise ValueError("Training eligible and assigned populations disagree")
    metadata = {
        "mart_version": FEATURE_VERSION, "analysis_scope": split,
        "as_of": iso(snapshot), "requested_as_of": iso(requested) if requested is not None else None,
        "cutoff": iso(cutoff), "train_labels_available_by": iso(readout),
        "train_start_inclusive": iso(train_start), "train_end_exclusive": iso(train_end),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_metadata_columns": ["customer_id", "assignment_id", "arm", "assigned_at", "feature_cutoff_at", "feature_version"],
        "input_simulation_id": next(iter(simulation_ids), None),
        "input_first_delivery_customers_known_as_of": known_deliveries,
        "selected_assignments": len(selected),
        "finalized_label_count": sum(row["is_profit_settled"] for row in outcomes),
        "labels_require_full_settlement": True,
        "missing_last_session_representation": "null",
        "interval_convention": "start_inclusive_end_exclusive",
    }
    if split != "train":
        metadata["split_readout_at"] = metadata.pop("train_labels_available_by")
        metadata["split_start_inclusive"] = metadata.pop("train_start_inclusive")
        metadata["split_end_exclusive"] = metadata.pop("train_end_exclusive")
    return {"features": features, "outcomes": outcomes, "eligibility_flow": flow, "metadata": metadata}
