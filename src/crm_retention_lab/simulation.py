"""Seeded observed-world generator; stage 1 writes latent oracle state only.

Each process/customer has its own SHA-256 RNG stream. Scenarios share underlying
draws, including purchase shocks, so differences arise from declared mechanisms.
No individual potential-outcome table or causal estimator is implemented here.
"""

import hashlib
import math
import random
from datetime import timedelta

from .config import iso, parse_ts, simulation_id, validate_config
from .schema import TABLE_COLUMNS, observed_row
from .finance import price_order, build_ledger
from .eligibility import evaluate_eligibility


def _rng(seed, customer_id, stream):
    digest = hashlib.sha256(f"{seed}|{customer_id}|{stream}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _choose_arm(rng, arms):
    value, cumulative = rng.random(), 0.0
    for arm in arms:
        cumulative += arm["probability"]
        if value < cumulative:
            return arm["id"]
    return arms[-1]["id"]


def generate_dataset(config):
    """Return (eight observed table lists, latent-only customer oracle rows)."""
    validate_config(config)
    cfg = config
    g = cfg["generator"]
    pop, exp, offer = cfg["population"], cfg["experiment"], cfg["offer"]
    seed = cfg["reproducibility"]["base_seed"]
    sid = simulation_id(cfg)
    scenario = cfg["runtime"]["scenario"]
    if g["refund"]["days_after_payment_max"] > pop["max_order_adjustment_recording_days_after_payment"]:
        raise ValueError("Refund generation exceeds the financial settlement contract")
    aa = scenario == "a_a_zero_cost"
    treatment_effects = scenario == "base"
    start = parse_ts(pop["first_delivery_start_inclusive"])
    end = parse_ts(pop["first_delivery_end_exclusive"])
    cutoff = parse_ts(pop["observation_end_exclusive"])
    slot_hour, slot_minute, slot_second = map(int, pop["first_delivery_daily_slot_local"].split(":"))
    slot = start.replace(hour=slot_hour, minute=slot_minute, second=slot_second, microsecond=0)
    if slot < start:
        slot += timedelta(days=1)
    days = []
    while slot < end:
        days.append(slot)
        slot += timedelta(days=1)
    if not days:
        raise ValueError("Delivery interval must contain a 09:00 slot")
    tables = {name: [] for name in TABLE_COLUMNS}
    oracle = []

    def row(table, **values):
        result = observed_row(table, sid, **values)
        tables[table].append(result)
        return result

    for index in range(pop["first_delivery_customers"]):
        cid = f"C{index + 1:07d}"
        cr = _rng(seed, cid, "customer")
        latent = g["customer"]
        consumption = cr.uniform(latent["consumption_grams_daily_min"], latent["consumption_grams_daily_max"])
        preference = cr.betavariate(latent["preference_beta_alpha"], latent["preference_beta_beta"])
        sensitivity = cr.betavariate(latent["price_sensitivity_beta_alpha"], latent["price_sensitivity_beta_beta"])
        first_delivery = cr.choice(days)
        lead = cr.randint(g["delivery"]["lead_days_min"], g["delivery"]["lead_days_max"])
        first_paid = first_delivery - timedelta(days=lead) + timedelta(hours=1)
        created = first_paid - timedelta(hours=cr.randint(1, 48))
        channel = cr.choices(latent["channels"], weights=latent["channel_weights"], k=1)[0]
        row("customers", customer_id=cid, created_at=iso(created), acquisition_channel=channel,
            acquisition_recorded_at=iso(created))
        oracle.append({"simulation_id": sid, "customer_id": cid,
                       "consumption_grams_daily": consumption, "product_preference": preference,
                       "price_sensitivity": sensitivity,
                       "oracle_scope": "latent_state_only_no_counterfactual_outcomes"})
        local_orders, local_order_events, local_customer_events = [], [], []
        counters = {"order": 0, "customer_event": 0, "order_event": 0}

        def customer_event(kind, when, lag=0, order_id=None):
            recorded = when + timedelta(days=lag)
            if when >= cutoff or recorded >= cutoff:
                return
            counters["customer_event"] += 1
            event = row("customer_events", event_id=f"{cid}-E{counters['customer_event']:04d}",
                        customer_id=cid, event_type=kind, occurred_at=iso(when),
                        recorded_at=iso(recorded), order_id=order_id)
            local_customer_events.append(event)

        def order_event(oid, kind, when):
            if when >= cutoff:
                return
            counters["order_event"] += 1
            event = row("order_events", order_event_id=f"{cid}-OE{counters['order_event']:04d}",
                        order_id=oid, event_type=kind, occurred_at=iso(when), recorded_at=iso(when))
            local_order_events.append(event)

        def add_order(paid, product, quantity=1, other_discount=0, coupon_discount=0,
                      assignment_id=None, delivery=None, is_first=False, refund_increment=0):
            if paid >= cutoff:
                return None
            counters["order"] += 1
            number = counters["order"]
            oid = f"{cid}-O{number:03d}"
            delivery_rng = _rng(seed, cid, f"delivery:{number}")
            if delivery is None:
                delivery = (paid + timedelta(days=delivery_rng.randint(
                    g["delivery"]["lead_days_min"], g["delivery"]["lead_days_max"]))).replace(
                        hour=9, minute=0, second=0, microsecond=0)
            prices = price_order(product, quantity, other_discount, coupon_discount, cfg["unit_economics"])
            order = row("orders", order_id=oid, customer_id=cid, paid_at=iso(paid),
                        paid_recorded_at=iso(paid), delivered_at=iso(delivery) if delivery < cutoff else None,
                        delivery_recorded_at=iso(delivery) if delivery < cutoff else None,
                        sku=product["sku"], quantity=quantity,
                        coupon_assignment_id=assignment_id if coupon_discount else None, **prices)
            local_orders.append(order)
            order_event(oid, "paid", paid)
            order_event(oid, "delivered", delivery)
            rr = _rng(seed, cid, f"refund:{number}")
            refund_probability = g["refund"]["first_order_probability" if is_first else "repeat_order_probability"]
            refund_draw = rr.random()
            refund_days = rr.randint(g["refund"]["days_after_payment_min"], g["refund"]["days_after_payment_max"])
            refund_at = paid + timedelta(days=refund_days) if refund_draw < refund_probability + refund_increment else None
            if refund_at is not None:
                order_event(oid, "fully_refunded", refund_at)
            full_order = dict(order, delivered_at=iso(delivery), delivery_recorded_at=iso(delivery))
            entries = build_ledger(full_order, product, cfg, refund_at=refund_at,
                                   recovery_fraction=g["refund"]["recovery_fraction"])
            for entry in entries:
                if parse_ts(entry["occurred_at"]) < cutoff and parse_ts(entry["recorded_at"]) < cutoff:
                    row("order_ledger", **{key: value for key, value in entry.items()
                                           if key not in ("simulation_id", "schema_version")})
            return order

        consent = cr.random() < latent["initial_consent_probability"]
        enabled = cr.random() < latent["initial_email_enabled_probability"]
        customer_event("consent_granted" if consent else "consent_revoked", created)
        customer_event("email_enabled" if enabled else "email_disabled", created)
        if cr.random() < latent["pre_assignment_revoke_probability"]:
            customer_event("consent_revoked", first_delivery + timedelta(days=7, hours=1))
        # Product choice is correlated with consumption, but not a direct copy.
        weights = [max(0.1, 30 - consumption), 15.0, max(0.1, consumption - 4)]
        product = cr.choices(cfg["catalog"], weights=weights, k=1)[0]
        quantity = 2 if cr.random() < latent["first_quantity_two_probability"] else 1
        discount_prob = latent["first_discount_probability_intercept"] + sensitivity * latent["first_discount_probability_sensitivity_weight"]
        first_discount = round(product["list_price_krw"] * quantity * latent["first_discount_fraction"]) if cr.random() < discount_prob else 0
        first = add_order(first_paid, product, quantity, first_discount, delivery=first_delivery, is_first=True)
        first_grams = product["grams"] * quantity
        br = _rng(seed, cid, "pre_purchase")
        if br.random() < g["behavior"]["pre_delivery_repeat_probability"]:
            add_order(first_paid + timedelta(days=1), product)
        early = br.random() < g["behavior"]["early_repeat_probability"]
        if early:
            add_order(first_delivery + timedelta(days=br.randint(1, 12), hours=3), product)
        assigned_at = first_delivery + timedelta(days=exp["assignment_offset_days"])
        for day in range(exp["assignment_offset_days"]):
            er = _rng(seed, cid, f"behavior:{day}")
            happened = first_delivery + timedelta(days=day, hours=er.randint(1, 10))
            lag = er.randint(0, pop["max_analytics_reporting_lag_days"])
            if er.random() < g["behavior"]["session_daily_intercept"] + preference * g["behavior"]["session_preference_weight"]:
                customer_event("session", happened, lag)
                if er.random() < g["behavior"]["tip_view_given_session_probability"]:
                    customer_event("tip_view", happened + timedelta(minutes=2), lag)
                if er.random() < g["behavior"]["cart_given_session_probability"]:
                    customer_event("cart", happened + timedelta(minutes=4), lag)
        if assigned_at >= cutoff:
            continue  # Pending customers have no eligibility verdict or assignment.
        audit = evaluate_eligibility(cid, first, local_orders, local_order_events,
                                     local_customer_events, assigned_at)
        row("eligibility_audit", **audit)
        arm, aid, contact_delivery, expiry = "control", None, None, None
        if audit["eligible"]:
            arm = _choose_arm(_rng(seed, cid, "assignment"), exp["arms"])
            aid = f"{cid}-A001"
            probs = {item["id"]: item["probability"] for item in exp["arms"]}
            row("assignments", assignment_id=aid, customer_id=cid, first_order_id=first["order_id"],
                first_delivered_at=iso(first_delivery), assigned_at=iso(assigned_at), arm=arm,
                p_control=probs["control"], p_info=probs["info"], p_coupon=probs["coupon"], eligibility_version="0.1.0")
            if arm != "control":
                nr = _rng(seed, cid, "contact")
                attempted = assigned_at + timedelta(minutes=5)
                delivered = attempted + timedelta(minutes=1) if nr.random() < g["contact"]["delivery_success_probability"] else None
                opened = delivered + timedelta(hours=nr.randint(1, 48)) if delivered and nr.random() < g["contact"]["open_probability_intercept"] + preference * g["contact"]["open_preference_weight"] else None
                clicked = opened + timedelta(minutes=3) if opened and nr.random() < g["contact"]["click_given_open_probability"] else None
                issued = delivered if arm == "coupon" else None
                expiry = issued + timedelta(days=offer["coupon_valid_days"]) if issued else None
                if attempted < cutoff:
                    contact_delivery = delivered if delivered and delivered < cutoff else None
                    row("contacts", contact_id=f"{cid}-K001", assignment_id=aid,
                        attempted_at=iso(attempted), delivered_at=iso(contact_delivery) if contact_delivery else None,
                        opened_at=iso(opened) if opened and opened < cutoff else None,
                        clicked_at=iso(clicked) if clicked and clicked < cutoff else None,
                        send_cost_krw=0 if aa else offer["send_cost_krw_per_attempt"],
                        coupon_issued_at=iso(issued) if issued and issued < cutoff else None,
                        coupon_expires_at=iso(expiry) if issued and issued < cutoff else None)
        # Account-setting opt-outs exist in every arm, independent of purchasing.
        ur = _rng(seed, cid, "unsubscribe")
        unsubscribe_draw = ur.random()
        unsubscribe_day = ur.randint(1, exp["outcome_horizon_days"] - 1)
        unsubscribe_probability = g["behavior"]["natural_unsubscribe_probability_60d"]
        if treatment_effects and contact_delivery:
            unsubscribe_probability += g["effects"][f"{arm}_unsubscribe_probability_increment"]
        if unsubscribe_draw < unsubscribe_probability:
            customer_event("consent_revoked", assigned_at + timedelta(days=unsubscribe_day, hours=2))
        last_purchase = max(parse_ts(order["paid_at"]) for order in local_orders)
        inventory_grams = first_grams
        coupon_used = False
        for day in range(exp["outcome_horizon_days"]):
            pr = _rng(seed, cid, f"purchase:{day}")
            paid = assigned_at + timedelta(days=day, hours=pr.randint(1, 12), minutes=pr.randint(0, 59))
            if paid >= cutoff:
                continue
            age = max(0.0, (paid - max(last_purchase, first_delivery)).total_seconds() / 86400)
            replenishment = inventory_grams / consumption
            odds = g["behavior"]["daily_base_odds"] + g["behavior"]["depletion_peak_odds"] * math.exp(-0.5 * ((age - replenishment) / g["behavior"]["depletion_width_days"]) ** 2)
            odds *= g["behavior"]["preference_odds_floor"] + preference * g["behavior"]["preference_odds_weight"]
            odds *= 1 + g["behavior"]["seasonal_odds_amplitude"] * math.cos(2 * math.pi * paid.month / 12)
            active = contact_delivery and contact_delivery <= paid < contact_delivery + timedelta(days=g["effects"]["active_days_after_contact"])
            if treatment_effects and active:
                log_effect = g["effects"]["info_log_odds_intercept"] + preference * g["effects"]["info_log_odds_preference_weight"]
                if arm == "coupon" and not coupon_used and expiry is not None and paid < expiry:
                    log_effect += g["effects"]["coupon_extra_log_odds_intercept"] + sensitivity * g["effects"]["coupon_extra_log_odds_sensitivity_weight"]
                odds *= math.exp(log_effect)
            buy_draw, product_draw, quantity_draw, redemption_draw = (pr.random() for _ in range(4))
            if buy_draw >= odds / (1 + odds):
                continue
            # These draws are shared across scenarios even when no purchase occurs.
            repeat_product = cfg["catalog"][min(int(product_draw * len(cfg["catalog"])), len(cfg["catalog"]) - 1)]
            repeat_quantity = 2 if quantity_draw < g["behavior"]["repeat_quantity_two_probability"] else 1
            discount = 0
            if (not aa and arm == "coupon" and contact_delivery and not coupon_used
                    and paid < expiry and repeat_product["list_price_krw"] * repeat_quantity >= offer["coupon_min_list_subtotal_krw"]
                    and redemption_draw < g["contact"]["coupon_redeem_probability_intercept"] + sensitivity * g["contact"]["coupon_redeem_sensitivity_weight"]):
                discount = offer["coupon_discount_krw"]
                coupon_used = True
            refund_increment = g["effects"]["coupon_return_probability_increment"] if treatment_effects and discount else 0
            add_order(paid, repeat_product, repeat_quantity, coupon_discount=discount,
                      assignment_id=aid, refund_increment=refund_increment)
            last_purchase = paid
            inventory_grams = repeat_product["grams"] * repeat_quantity
    for table, records in tables.items():
        # Stable insertion order is intentional: no machine-local hash ordering.
        if any(set(record) != set(TABLE_COLUMNS[table]) for record in records):
            raise AssertionError(f"Schema mismatch in {table}")
    return tables, oracle
