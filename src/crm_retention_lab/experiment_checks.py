"""Training ITT diagnostics and independent signed-ledger reconciliation.

Source tables are indexed/scanned once. Customer IDs are never emitted in the
public result, including mismatch details. No generator/oracle data is read.
"""

from collections import Counter
from datetime import timedelta
import math

from .config import parse_ts
from .marts import FEATURE_COLUMNS
from .schema import TABLE_COLUMNS


ARMS = ("control", "info", "coupon")
PAIRS = (("info", "control"), ("coupon", "control"), ("coupon", "info"))
CATEGORICAL = {"first_pack_grams", "acquisition_channel", "first_delivery_month"}
COMPONENTS = (
    "net_item_revenue", "customer_shipping_charge", "refund", "cogs", "cogs_recovery",
    "outbound_shipping", "fulfillment", "payment_fee", "return_handling", "send_cost",
)
SUPPORTING = ("list_subtotal_krw", "other_discount_krw", "crm_coupon_discount_krw")
STAGES = ("assigned", "attempted", "reached", "opened", "clicked", "coupon_issued", "redeemed")


def _indexed(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate {key} in experiment input")
    return result


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Financial entries must be integer KRW")
    return value


def _moments(values):
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError("Balance variables must contain finite numeric observations")
    n = len(values)
    mean = math.fsum(values) / n if n else None
    variance = math.fsum((value - mean) ** 2 for value in values) / (n - 1) if n > 1 else None
    return {"n": n, "mean": mean, "variance": variance,
            "sd": math.sqrt(variance) if variance is not None else None}


def _binary_moments(count, total):
    mean = count / total if total else None
    variance = count * (total - count) / (total * (total - 1)) if total > 1 else None
    return {"n": total, "mean": mean, "variance": variance,
            "sd": math.sqrt(variance) if variance is not None else None}


def _smd(treatment, reference):
    if treatment["n"] < 2 or reference["n"] < 2:
        return None, "insufficient_n"
    difference = treatment["mean"] - reference["mean"]
    pooled_sd = math.sqrt((treatment["variance"] + reference["variance"]) / 2)
    if pooled_sd == 0:
        return (0.0, "defined") if difference == 0 else (None, "undefined_constant_difference")
    return difference / pooled_sd, "defined"


def _balance(features):
    grouped = {arm: [row for row in features if row["arm"] == arm] for arm in ARMS}
    rows = []
    for feature in (*FEATURE_COLUMNS, "days_since_last_session__missing"):
        missing_indicator = feature.endswith("__missing")
        kind = "missing_indicator" if missing_indicator else ("categorical" if feature in CATEGORICAL else "numeric")
        summaries, moments, counts = {}, {}, {}
        for arm, group in grouped.items():
            values = [int(row["days_since_last_session"] is None) if missing_indicator else row[feature]
                      for row in group]
            missing = sum(value is None for value in values)
            if kind == "categorical":
                counts[arm] = Counter("(missing)" if value is None else str(value) for value in values)
                summaries[arm] = {"n": len(values), "n_missing": missing,
                                  "counts": dict(sorted(counts[arm].items()))}
            else:
                moments[arm] = _moments([value for value in values if value is not None])
                summaries[arm] = {**moments[arm], "n_missing": missing}
        levels = sorted(set().union(*(set(counts[arm]) for arm in ARMS))) if kind == "categorical" else []
        comparisons = []
        for treatment, reference in PAIRS:
            level = None
            if kind == "categorical":
                candidates = []
                for category in levels:
                    value, status = _smd(
                        _binary_moments(counts[treatment][category], len(grouped[treatment])),
                        _binary_moments(counts[reference][category], len(grouped[reference])),
                    )
                    candidates.append((category, value, status))
                undefined = [candidate for candidate in candidates if candidate[1] is None]
                if undefined:
                    level, value, status = undefined[0]
                elif candidates:
                    level, value, status = max(candidates, key=lambda candidate: abs(candidate[1]))
                else:
                    value, status = None, "insufficient_n"
            else:
                value, status = _smd(moments[treatment], moments[reference])
            comparisons.append({"contrast": f"{treatment}_vs_{reference}", "smd": value,
                                "max_abs_smd": abs(value) if value is not None else None,
                                "level": level, "status": status})
        undefined = [row["contrast"] for row in comparisons if row["smd"] is None]
        rows.append({"feature": feature, "kind": kind, "arm_summaries": summaries,
                     "comparisons": comparisons, "undefined_comparisons": undefined,
                     "max_abs_smd": None if undefined else max(row["max_abs_smd"] for row in comparisons)})
    return {"reference_threshold": 0.1, "features": rows,
            "any_above_reference": any(row["max_abs_smd"] is not None and row["max_abs_smd"] > 0.1 for row in rows),
            "has_undefined_smd": any(row["undefined_comparisons"] for row in rows)}


def _validate_inputs(observed, marts, config):
    if set(observed) != set(TABLE_COLUMNS):
        raise ValueError("Experiment checks accept only the eight observed tables")
    if marts["metadata"].get("analysis_scope") != "train":
        raise ValueError("Experiment checks are restricted to train")
    snapshot = parse_ts(marts["metadata"]["as_of"])
    source_end = parse_ts(config["population"]["observation_end_exclusive"])
    readout = parse_ts(config["splits"]["train_labels_available_by"])
    if snapshot > min(source_end, readout):
        raise ValueError("Analysis snapshot exceeds source coverage or train readout")
    start = parse_ts(config["splits"]["train"]["start_inclusive"])
    end = parse_ts(config["splits"]["train"]["end_exclusive"])
    selected = [row for row in observed["assignments"]
                if start <= parse_ts(row["assigned_at"]) < min(end, snapshot)]
    assignments = _indexed(selected, "assignment_id")
    features = _indexed(marts["features"], "assignment_id")
    outcomes = _indexed(marts["outcomes"], "assignment_id")
    if not assignments or assignments.keys() != features.keys() or assignments.keys() != outcomes.keys():
        raise ValueError("All train assignments must occur exactly once in both marts")
    if len({row["customer_id"] for row in selected}) != len(selected):
        raise ValueError("A customer may have only one train assignment")
    probability = {row["id"]: row["probability"] for row in config["experiment"]["arms"]}
    if set(probability) != set(ARMS) or any(not math.isfinite(p) or p <= 0 or p >= 1 for p in probability.values()):
        raise ValueError("Three strictly positive assignment probabilities are required")
    if not math.isclose(sum(probability.values()), 1, abs_tol=1e-12):
        raise ValueError("Assignment probabilities must sum to one")
    horizon = timedelta(days=config["experiment"]["outcome_horizon_days"])
    settlement_lag = timedelta(days=config["experiment"]["settlement_lag_days"])
    windows = {}
    for aid, assignment in assignments.items():
        if assignment["arm"] not in ARMS:
            raise ValueError("Unknown assignment arm")
        for arm in ARMS:
            p = assignment[f"p_{arm}"]
            if not math.isfinite(p) or not 0 < p < 1 or not math.isclose(p, probability[arm], abs_tol=1e-12):
                raise ValueError("Recorded assignment probabilities must match the configured design")
        for key in ("customer_id", "assigned_at", "arm"):
            if features[aid][key] != assignment[key] or outcomes[aid][key] != assignment[key]:
                raise ValueError("Source assignment and marts disagree")
        assigned = parse_ts(assignment["assigned_at"])
        window_end = assigned + horizon
        freeze = window_end + settlement_lag
        outcome = outcomes[aid]
        if (not outcome["is_outcome_mature"] or not outcome["is_profit_settled"]
                or outcome["label_freeze_at"] is None or parse_ts(outcome["label_freeze_at"]) != freeze
                or snapshot < freeze or outcome["contribution_profit_60d_krw"] is None):
            raise ValueError("Full ITT cohort must pass settlement; partial mature comparisons are forbidden")
        if parse_ts(features[aid]["feature_cutoff_at"]) != assigned:
            raise ValueError("Feature snapshot must be the pre-assignment cutoff")
        windows[aid] = (assigned, window_end, freeze)
    return assignments, features, outcomes, probability, windows


def summarize_experiment_checks(observed, marts, config):
    """Return SRM, pre-assignment balance, non-nested delivery counts and accounts.

    Mismatch totals are returned for the reporting pipeline to refuse publishing.
    Missing/immature ITT members are rejected before any partial comparison.
    """
    from scipy.stats import chi2

    assignments, features, outcomes, probability, windows = _validate_inputs(observed, marts, config)
    arm_counts = Counter(row["arm"] for row in assignments.values())
    total = len(assignments)
    chi_square = math.fsum((arm_counts[arm] - total * probability[arm]) ** 2 / (total * probability[arm]) for arm in ARMS)
    p_value = float(chi2.sf(chi_square, len(ARMS) - 1))
    randomization = {
        "n_assigned": total, "chi_square": chi_square, "degrees_of_freedom": 2,
        "p_value": p_value, "alpha": 0.001, "srm_flag": p_value < 0.001,
        "arms": [{"arm": arm, "n": arm_counts[arm], "expected_probability": probability[arm],
                  "expected_n": total * probability[arm], "observed_fraction": arm_counts[arm] / total} for arm in ARMS],
        "minimum_expected_n": min(total * probability[arm] for arm in ARMS),
        "chi_square_approximation_caution": min(total * probability[arm] for arm in ARMS) < 5,
    }

    by_customer = {row["customer_id"]: aid for aid, row in assignments.items()}
    components = {aid: {name: 0 for name in COMPONENTS} for aid in assignments}
    supporting = {aid: {name: 0 for name in SUPPORTING} for aid in assignments}
    flags = {aid: {name: name == "assigned" for name in STAGES} for aid in assignments}
    included_orders, order_counts = {}, Counter()
    mismatch_ids, mismatch_counts = set(), Counter()

    def mismatch(aid, name):
        mismatch_ids.add(aid)
        mismatch_counts[name] += 1

    order_item, order_shipping = Counter(), Counter()
    for order in observed["orders"]:
        aid = by_customer.get(order["customer_id"])
        if aid is None or order["order_id"] == assignments[aid]["first_order_id"]:
            continue
        start, end, freeze = windows[aid]
        paid, recorded = parse_ts(order["paid_at"]), parse_ts(order["paid_recorded_at"])
        if not (start <= paid < end and recorded < freeze):
            continue
        if order["order_id"] in included_orders:
            raise ValueError("Duplicate included order")
        included_orders[order["order_id"]] = aid
        order_counts[aid] += 1
        for name in SUPPORTING:
            supporting[aid][name] += _integer(order[name])
        net_item = _integer(order["item_revenue_after_discount_krw"])
        order_item[aid] += net_item
        order_shipping[aid] += _integer(order["customer_shipping_charge_krw"])
        if order["list_subtotal_krw"] - order["other_discount_krw"] - order["crm_coupon_discount_krw"] != net_item:
            mismatch(aid, "order_price_identity")
        if order["crm_coupon_discount_krw"] > 0:
            if order["coupon_assignment_id"] != aid:
                mismatch(aid, "coupon_assignment_link")
            flags[aid]["redeemed"] = True

    seen_entries, refunded = set(), set()
    for entry in observed["order_ledger"]:
        aid = included_orders.get(entry["order_id"])
        if aid is None:
            continue
        freeze = windows[aid][2]
        if not (parse_ts(entry["occurred_at"]) < freeze and parse_ts(entry["recorded_at"]) < freeze):
            continue
        if entry["entry_id"] in seen_entries:
            raise ValueError("Duplicate included ledger entry")
        seen_entries.add(entry["entry_id"])
        kind = entry["entry_type"]
        if kind not in COMPONENTS or kind == "send_cost":
            raise ValueError("Unknown signed order-ledger component")
        components[aid][kind] += _integer(entry["amount_krw"])
        if kind == "refund":
            refunded.add(aid)

    contact_fields = {"reached": "delivered_at", "opened": "opened_at", "clicked": "clicked_at", "coupon_issued": "coupon_issued_at"}
    seen_contacts = set()
    for contact in observed["contacts"]:
        aid = contact["assignment_id"]
        if aid not in assignments:
            continue
        start, end, freeze = windows[aid]
        attempted = parse_ts(contact["attempted_at"])
        if not start <= attempted < freeze:
            continue
        if contact["contact_id"] in seen_contacts:
            raise ValueError("Duplicate included contact")
        seen_contacts.add(contact["contact_id"])
        components[aid]["send_cost"] -= _integer(contact["send_cost_krw"])
        if attempted < end:
            flags[aid]["attempted"] = True
        for stage, field in contact_fields.items():
            if contact[field] is not None and start <= parse_ts(contact[field]) < end:
                flags[aid][stage] = True

    for aid, outcome in outcomes.items():
        component = components[aid]
        checks = {
            "contribution_profit_60d_krw": sum(component.values()),
            "order_count_60d": order_counts[aid],
            "repeat_paid_within_60d": int(order_counts[aid] > 0),
            "refund_amount_krw": -component["refund"],
            "refund_customer_flag": int(aid in refunded),
            "actual_campaign_spend_krw": -component["send_cost"] + supporting[aid]["crm_coupon_discount_krw"],
        }
        for name, actual in checks.items():
            if outcome[name] != actual:
                mismatch(aid, name)
        if component["net_item_revenue"] != order_item[aid]:
            mismatch(aid, "ledger_item_revenue_vs_order")
        if component["customer_shipping_charge"] != order_shipping[aid]:
            mismatch(aid, "ledger_shipping_charge_vs_order")

    finances, support_rows, funnel = [], [], []
    for arm in ARMS:
        aids = [aid for aid, assignment in assignments.items() if assignment["arm"] == arm]
        n = len(aids)
        totals = {name: sum(components[aid][name] for aid in aids) for name in COMPONENTS}
        supporting_totals = {name: sum(supporting[aid][name] for aid in aids) for name in SUPPORTING}
        mean = {name: value / n if n else None for name, value in totals.items()}
        finances.append({"arm": arm, "n": n, "components_total_krw": totals, "components_mean_krw": mean,
                         "total_profit_krw": sum(totals.values()), "mean_profit_krw": sum(totals.values()) / n if n else None,
                         "mart_total_profit_krw": sum(_integer(outcomes[aid]["contribution_profit_60d_krw"]) for aid in aids)})
        support_rows.append({"arm": arm, "n": n, "totals_krw": supporting_totals,
                             "means_krw": {name: value / n if n else None for name, value in supporting_totals.items()}})
        counts = {stage: sum(flags[aid][stage] for aid in aids) for stage in STAGES}
        applicable = {stage: stage == "assigned" or (arm != "control" and (stage not in {"coupon_issued", "redeemed"} or arm == "coupon")) for stage in STAGES}
        funnel.append({"arm": arm, "n_assigned": n, "counts": counts, "applicable": applicable,
                       "rates_per_assigned": {stage: count / n if n and applicable[stage] else None for stage, count in counts.items()}})
    finance_by_arm = {row["arm"]: row for row in finances}
    comparisons = []
    for treatment, reference in PAIRS:
        treated, control = finance_by_arm[treatment], finance_by_arm[reference]
        valid = treated["n"] > 0 and control["n"] > 0
        comparisons.append({"contrast": f"{treatment}_vs_{reference}",
                            "components_mean_difference_krw": {name: treated["components_mean_krw"][name] - control["components_mean_krw"][name] if valid else None for name in COMPONENTS},
                            "profit_mean_difference_krw": treated["mean_profit_krw"] - control["mean_profit_krw"] if valid else None})
    return {
        "randomization": randomization,
        "balance": _balance(list(features.values())),
        "delivery_funnel": {"arms": funnel, "stages": list(STAGES), "denominator": "all_originally_assigned_customers", "strictly_nested": False},
        "finance_reconciliation": {
            "status": "mismatch" if mismatch_ids else "passed", "n_customers_checked": total,
            "mismatch_customers": len(mismatch_ids), "mismatch_counts": dict(sorted(mismatch_counts.items())),
            "components_order": list(COMPONENTS), "arms": finances, "comparisons": comparisons,
            "supporting_accounting": {"arms": support_rows, "included_in_waterfall": False},
        },
        "methods": {
            "data_origin": "fully_synthetic", "analysis_scope": "train", "oracle_used": False,
            "population": "Every original train assignment; all must have 90-day settled labels.",
            "srm": "Pearson chi-square against configured probabilities; alpha=0.001 is a diagnostic flag, never a sample-removal rule.",
            "smd": "(mean_t - mean_r) / sqrt((sample_variance_t + sample_variance_r) / 2); no p-values.",
            "categorical_smd": "One-hot sample-variance SMD for each level; report signed value at maximum absolute difference.",
            "missingness": "Numeric last-session SMD uses observed values; its missingness indicator is reported separately.",
            "smd_reference": "Absolute 0.1 is a descriptive reference, not a randomization test or causal guarantee.",
            "funnel": "Distinct customer counts within the 60-day window; every rate uses original arm assignments. Coupon redemption need not follow a recorded open or click.",
            "source_cutoff": "Payment [assignment, assignment+60d); payment and ledger records strictly before settlement; snapshot no later than source/train readout.",
            "finance": "Signed integer ledger components plus negative send costs; initial order excluded. Net item revenue already contains coupon discounts.",
            "supporting_accounting": "Gross list subtotal and discounts are supplementary identities, not additional waterfall costs.",
            "mismatch_policy": "Public mismatch counts have no customer identifiers; a mismatch must stop report publication.",
        },
    }
