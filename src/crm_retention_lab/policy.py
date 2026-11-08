"""Deterministic daily allocation using predictions and pretreatment fields only.

Reservation is the full coupon face value plus attempt cost, regardless of
redemption. Risk screening spends only positive predicted risk differences;
predicted benefits cannot offset predicted harms to other customers. This is
a planning screen, not the empirical IPW safety assessment or a global optimum.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from fractions import Fraction
import hashlib
import math

import numpy as np

from .config import parse_ts


POLICY_VERSION = "0.1.0"
ARM_NAMES = ("control", "info", "coupon")
KINDS = {"control", "random_info", "random_coupon", "rule", "risk_coupon", "uplift"}


@dataclass
class PreparedPolicyInputs:
    """Reusable allocation arrays; construct once per prediction family.

    Bootstrap indices address these original rows. Every sampled occurrence
    receives its own action even when the same source customer appears twice.
    """

    customer_ids: np.ndarray
    customer_codes: np.ndarray
    batch_labels: np.ndarray
    batch_codes: np.ndarray
    pack: np.ndarray
    tips: np.ndarray
    gains: np.ndarray
    unsubscribe_delta: np.ndarray
    refund_delta: np.ndarray
    risk: np.ndarray
    costs: tuple
    contact_numerator: int
    contact_denominator: int
    budget_numerator: int
    budget_denominator: int
    unsubscribe_limit: float
    refund_limit: float
    default_seed: int
    random_priorities: dict = field(default_factory=dict, repr=False)


def default_policy_specs(config):
    """Return the prespecified five baselines and eight uplift candidates."""
    seed = int(config["reproducibility"]["base_seed"])
    common = {"policy_version": POLICY_VERSION, "penalty_lambda": 0.0, "risk_filter": True, "seed": seed}
    specs = [{"id": kind, "kind": kind, "model": "hgb", **common}
             for kind in ("control", "random_info", "random_coupon", "rule", "risk_coupon")]
    specs[3]["rule"] = {"info_pack_grams": 200, "info_max_tip_views": 0, "coupon_pack_grams": [500, 1000]}
    for model in ("ridge", "hgb"):
        for penalty in (0.0, 0.5, 1.0, 2.0):
            slug = str(penalty).replace(".", "p")
            specs.append({"id": f"uplift_{model}_lambda_{slug}", "kind": "uplift", "model": model,
                          **common, "penalty_lambda": penalty})
    return specs


def _array(values, shape, name, probability=False):
    array = np.array(values, dtype=float, copy=True)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite with shape {shape}")
    if probability and ((array < 0).any() or (array > 1).any()):
        raise ValueError(f"{name} must contain probabilities in [0, 1]; no implicit clipping")
    return array


def prepare_policy_inputs(features, predictions, config):
    """Read exactly four permitted feature fields; ignore observed arms/outcomes.

    ``predictions`` is a flat family dictionary. Its risk vector is the
    *non-repurchase* risk, supplied as one minus control repurchase probability.
    Additional keys, including the evaluation-only DR nuisance, are ignored.
    """
    n = len(features)
    customer_ids = np.array([row["customer_id"] for row in features], dtype=str)
    if any(not isinstance(row["customer_id"], str) or not row["customer_id"] for row in features):
        raise ValueError("customer_id must be a nonempty string")
    raw_batches = [row["assigned_at"] for row in features]
    normalized = {}
    for value in set(raw_batches):
        timestamp = parse_ts(value)
        if timestamp.strftime("%H:%M:%S") != "09:00:00" or timestamp.microsecond or timestamp.utcoffset() != timedelta(hours=9):
            raise ValueError("Allocation batches must use the prespecified 09:00 assignment slot")
        normalized[value] = timestamp.isoformat(timespec="seconds")
    batch_labels, batch_codes = np.unique([normalized[value] for value in raw_batches], return_inverse=True)
    _, customer_codes = np.unique(customer_ids, return_inverse=True)
    pack = _array([row["first_pack_grams"] for row in features], (n,), "first_pack_grams")
    tips = _array([row["tip_views_d0_d13"] for row in features], (n,), "tip_views_d0_d13")
    if (tips < 0).any() or not np.equal(tips, np.floor(tips)).all():
        raise ValueError("Pretreatment tip counts must be nonnegative integers")
    profit = _array(predictions["profit"], (n, 3), "profit")
    unsubscribe = _array(predictions["unsubscribe"], (n, 3), "unsubscribe", probability=True)
    refund = _array(predictions["refund"], (n, 3), "refund", probability=True)
    risk = _array(predictions["risk"], (n,), "risk", probability=True)
    constraints, offer = config["policy_constraints"], config["offer"]
    contact = Fraction(str(constraints["max_contact_fraction"]))
    budget = Fraction(int(constraints["budget_reservation_cap_krw_per_10000"]), 10000)
    send, coupon = offer["send_cost_krw_per_attempt"], offer["coupon_discount_krw"]
    if not 0 <= contact <= 1 or budget < 0 or type(send) is not int or type(coupon) is not int or send <= 0 or coupon < 0:
        raise ValueError("Invalid contact, reservation budget, or offer cost")
    unsub_limit = config["inference"]["guardrail_max_increase_unsubscribe_pp"] / 100
    refund_limit = config["inference"]["guardrail_max_increase_refund_customer_pp"] / 100
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in (unsub_limit, refund_limit)):
        raise ValueError("Risk screening limits must be probability increases in [0, 1]")
    prepared = PreparedPolicyInputs(
        customer_ids, customer_codes, batch_labels, batch_codes.astype(np.int32), pack, tips,
        profit[:, 1:] - profit[:, [0]], unsubscribe[:, 1:] - unsubscribe[:, [0]],
        refund[:, 1:] - refund[:, [0]], risk, (0, send, send + coupon),
        contact.numerator, contact.denominator, budget.numerator, budget.denominator,
        unsub_limit, refund_limit, int(config["reproducibility"]["base_seed"]),
    )
    # Copies above prevent accidental mutation of caller-owned prediction arrays.
    for value in vars(prepared).values():
        if isinstance(value, np.ndarray):
            value.flags.writeable = False
    return prepared


def _spec(spec, default_seed):
    kind = spec["kind"]
    if kind not in KINDS:
        raise ValueError(f"Unknown policy kind: {kind}")
    model = spec.get("model", "hgb")
    if model not in {"ridge", "hgb"} or (kind != "uplift" and model != "hgb"):
        raise ValueError("Operating baselines must use the fixed HGB prediction gate")
    penalty = spec.get("penalty_lambda", 0.0)
    if isinstance(penalty, bool) or not isinstance(penalty, (int, float)) or not math.isfinite(penalty) or penalty < 0:
        raise ValueError("penalty_lambda must be finite and nonnegative")
    risk_filter = spec.get("risk_filter", True)
    seed = spec.get("seed", default_seed)
    if type(risk_filter) is not bool or type(seed) is not int:
        raise ValueError("risk_filter must be boolean and seed must be an integer")
    return kind, float(penalty), risk_filter, seed


def _random_priority(prepared, seed):
    if seed not in prepared.random_priorities:
        values = np.fromiter((int.from_bytes(hashlib.sha256(
            f"{seed}|{prepared.batch_labels[batch]}|{customer}".encode("utf-8")).digest()[:8], "big")
                              for customer, batch in zip(prepared.customer_ids, prepared.batch_codes)),
                             dtype=np.uint64, count=len(prepared.customer_ids))
        values.flags.writeable = False
        prepared.random_priorities[seed] = values
    return prepared.random_priorities[seed]


def allocate_policy(features, predictions, spec, config, *, indices=None, return_audit=True, prepared=None):
    """Allocate 0/control, 1/info, 2/coupon independently inside daily batches.

    For repeated bootstrap calls, supply a cached ``prepared`` object and only
    change ``indices``. Rows are returned in sampled order. Equal-score ties are
    customer ID, arm, then sampled occurrence; duplicated source indices are
    separate customers for that bootstrap replicate's capacity calculation.
    ``return_audit=False`` returns only actions/caps_ok to avoid report overhead.
    """
    if prepared is None:
        prepared = prepare_policy_inputs(features, predictions, config)
    if not isinstance(prepared, PreparedPolicyInputs):
        raise ValueError("prepared must be created by prepare_policy_inputs")
    kind, penalty, risk_filter, seed = _spec(spec, prepared.default_seed)
    size = len(prepared.customer_ids)
    if indices is None:
        take = np.arange(size, dtype=np.intp)
    else:
        take = np.asarray(indices)
        if take.size == 0:
            take = take.astype(np.intp)
        if take.ndim != 1 or not np.issubdtype(take.dtype, np.integer) or (take < 0).any() or (take >= size).any():
            raise ValueError("indices must be a one-dimensional array of valid source row indices")
    n, batch_count = len(take), len(prepared.batch_labels)
    batches = prepared.batch_codes[take]
    populations = np.bincount(batches, minlength=batch_count).astype(np.int64)
    contact_caps = populations * prepared.contact_numerator // prepared.contact_denominator
    budget_caps = populations * prepared.budget_numerator // prepared.budget_denominator
    contacts, reserved = np.zeros(batch_count, dtype=np.int64), np.zeros(batch_count, dtype=np.int64)
    unsub_spent, refund_spent = np.zeros(batch_count), np.zeros(batch_count)
    unsub_caps, refund_caps = populations * prepared.unsubscribe_limit, populations * prepared.refund_limit
    actions = np.zeros(n, dtype=np.int8)
    gains = prepared.gains[take]
    unsub = np.maximum(prepared.unsubscribe_delta[take], 0)
    refunds = np.maximum(prepared.refund_delta[take], 0)
    if kind != "control" and n:
        eligible = gains > 0
        if kind == "uplift":
            scores = gains - penalty * np.asarray(prepared.costs[1:])
            eligible &= scores > 0
            priorities = -scores
        else:
            if kind == "random_info":
                eligible[:, 1] = False
            elif kind in {"random_coupon", "risk_coupon"}:
                eligible[:, 0] = False
            elif kind == "rule":
                rule = spec.get("rule", {})
                eligible[:, 0] &= ((prepared.pack[take] == rule.get("info_pack_grams", 200))
                                   & (prepared.tips[take] <= rule.get("info_max_tip_views", 0)))
                eligible[:, 1] &= np.isin(prepared.pack[take], rule.get("coupon_pack_grams", [500, 1000]))
            priority = -prepared.risk[take] if kind == "risk_coupon" else _random_priority(prepared, seed)[take]
            priorities = np.broadcast_to(priority[:, None], (n, 2))
        rows, arms_zero = np.nonzero(eligible)
        candidate_batches = batches[rows]
        # Lexsort's last key is primary: daily batch, score, customer, arm,
        # occurrence. A sampled row's position orders otherwise identical copies.
        order = np.lexsort((rows, arms_zero, prepared.customer_codes[take[rows]],
                            priorities[rows, arms_zero], candidate_batches))
        rows, arms_zero = rows[order], arms_zero[order]
        candidate_batches = candidate_batches[order]
        rows_list, arms_list = rows.tolist(), (arms_zero + 1).tolist()
        unsub_list, refund_list = unsub[rows, arms_zero].tolist(), refunds[rows, arms_zero].tolist()
        starts = np.searchsorted(candidate_batches, np.arange(batch_count + 1))
        epsilon = 1e-12
        minimum_cost = prepared.costs[2] if kind in {"random_coupon", "risk_coupon"} else prepared.costs[1]
        for batch in np.flatnonzero(populations):
            contact_cap, budget_cap = int(contact_caps[batch]), int(budget_caps[batch])
            spent, used, risk_u, risk_r = 0, 0, 0.0, 0.0
            limit_u, limit_r = unsub_caps[batch], refund_caps[batch]
            for position in range(int(starts[batch]), int(starts[batch + 1])):
                if used >= contact_cap or budget_cap - spent < minimum_cost:
                    break
                row, arm = rows_list[position], arms_list[position]
                if actions[row] or prepared.costs[arm] > budget_cap - spent:
                    continue
                add_u, add_r = unsub_list[position], refund_list[position]
                if risk_filter and (risk_u + add_u > limit_u + epsilon or risk_r + add_r > limit_r + epsilon):
                    continue
                actions[row] = arm
                spent += prepared.costs[arm]
                used += 1
                risk_u += add_u
                risk_r += add_r
            contacts[batch], reserved[batch] = used, spent
            unsub_spent[batch], refund_spent[batch] = risk_u, risk_r
    cap_results = (contacts <= contact_caps) & (reserved <= budget_caps)
    if risk_filter:
        cap_results &= (unsub_spent <= unsub_caps + 1e-12) & (refund_spent <= refund_caps + 1e-12)
    result = {"actions": actions, "caps_ok": bool(cap_results.all())}
    if not return_audit:
        return result
    active = np.flatnonzero(actions)
    active_arms = actions[active] - 1
    action_counts = np.bincount(actions, minlength=3)
    summary = {
        "policy_id": spec.get("id", kind), "kind": kind, "model": spec.get("model", "hgb"),
        "n_eligible": n, "n_batches": int(np.count_nonzero(populations)),
        "action_counts": {arm: int(action_counts[index]) for index, arm in enumerate(ARM_NAMES)},
        "contacts": int(contacts.sum()), "reserved_cost_krw": int(reserved.sum()),
        "contact_fraction": float(contacts.sum() / n) if n else 0.0,
        "predicted_incremental_profit_krw": float(gains[active, active_arms].sum()),
        "predicted_unsubscribe_positive_mass": float(unsub_spent.sum()),
        "predicted_refund_positive_mass": float(refund_spent.sum()),
        "predicted_incremental_unsubscribe_mass": float(prepared.unsubscribe_delta[take[active], active_arms].sum()),
        "predicted_incremental_refund_mass": float(prepared.refund_delta[take[active], active_arms].sum()),
        "risk_filter": risk_filter, "risk_screen_is_empirical_guardrail": False,
        "reservation_basis": "full_coupon_face_value_plus_attempt_cost",
    }
    audit = [{"assigned_at": str(prepared.batch_labels[batch]), "n_eligible": int(populations[batch]),
              "contact_cap": int(contact_caps[batch]), "contacts": int(contacts[batch]),
              "reservation_cap_krw": int(budget_caps[batch]), "reserved_cost_krw": int(reserved[batch]),
              "unsubscribe_positive_mass": float(unsub_spent[batch]), "unsubscribe_mass_cap": float(unsub_caps[batch]),
              "refund_positive_mass": float(refund_spent[batch]), "refund_mass_cap": float(refund_caps[batch]),
              "caps_ok": bool(cap_results[batch])} for batch in np.flatnonzero(populations)]
    result.update(summary=summary, batch_audit=audit)
    return result
