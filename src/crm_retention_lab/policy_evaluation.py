"""Paired DR/IPW policy evaluation with within-day allocation bootstrap.

Only caller-supplied observed outcomes and frozen predictions are used. This
module never reads a dataset, fits a model, chooses lambda, or opens an oracle.
"""

from functools import lru_cache
from fractions import Fraction
import hashlib
import math
from statistics import NormalDist

from .config import parse_ts


ARMS = ("control", "info", "coupon")
GUARDRAILS = ("unsubscribe_60d", "refund_customer_flag")
REFERENCES = (
    "https://icml.cc/2011/papers/554_icmlpaper.pdf",
    "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html",
)


@lru_cache(maxsize=1)
def _numpy():
    try:
        import numpy
    except ImportError as error:
        raise ImportError("Policy evaluation requires the optional NumPy analysis dependency") from error
    return numpy


def _codes(values, n, name):
    np = _numpy()
    array = np.asarray(values)
    if array.shape != (n,):
        raise ValueError(f"{name} must have shape (n,)")
    if array.dtype.kind in "USO":
        try:
            array = np.asarray([ARMS.index(value) for value in values], dtype=np.int8)
        except ValueError as error:
            raise ValueError(f"Unknown {name}") from error
    elif array.dtype.kind not in "iu":
        raise ValueError(f"{name} must use arm names or integer action codes")
    if np.any((array < 0) | (array >= 3)):
        raise ValueError(f"Unknown {name}")
    return array.astype(np.int8, copy=False)


def _score_tables(y, arms, mu, propensity):
    np = _numpy()
    y = np.asarray(y, dtype=float)
    if y.ndim != 1 or not len(y) or not np.all(np.isfinite(y)):
        raise ValueError("Outcomes must be a nonempty finite vector")
    n = len(y)
    arms = _codes(arms, n, "observed arms")
    mu = np.asarray(mu, dtype=float)
    if mu.shape != (n, 3) or not np.all(np.isfinite(mu)):
        raise ValueError("Frozen nuisance predictions must have finite shape (n, 3)")
    probabilities = np.asarray(propensity, dtype=float)
    if probabilities.shape == (3,):
        probabilities = np.broadcast_to(probabilities, (n, 3))
    if probabilities.shape != (n, 3) or not np.all(np.isfinite(probabilities)):
        raise ValueError("Propensity must have shape (3,) or (n, 3)")
    if np.any(probabilities <= 0) or np.any(probabilities > 1) or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-12):
        raise ValueError("Every action must have positive probability and each row must sum to one")
    positions = np.arange(n)
    observed_p = probabilities[positions, arms]
    inverse_p = 1 / observed_p
    ipw = np.zeros((n, 3), dtype=float)
    ipw[positions, arms] = y * inverse_p
    dr = mu.copy()
    dr[positions, arms] += (y - mu[positions, arms]) * inverse_p
    return {"y": y, "arms": arms, "mu": mu, "inverse_p": inverse_p, "dr": dr, "ipw": ipw}


def policy_scores(y, arms, actions, mu, propensity):
    """Return per-customer policy/control scores, without matching-only filtering.

    Actions/arms are 0,1,2 or control/info/coupon. Propensity is the three arm
    probabilities, or an n-by-3 matrix; all means use the full n denominator.
    """
    np = _numpy()
    tables = _score_tables(y, arms, mu, propensity)
    n = len(tables["y"])
    actions = _codes(actions, n, "policy actions")
    positions = np.arange(n)
    matched = tables["arms"] == actions
    weights = matched * tables["inverse_p"]
    control_weights = (tables["arms"] == 0) * tables["inverse_p"]
    dr, ipw = tables["dr"][positions, actions], tables["ipw"][positions, actions]
    dr_control, ipw_control = tables["dr"][:, 0], tables["ipw"][:, 0]
    return {"dr": dr, "ipw": ipw, "dr_control": dr_control, "ipw_control": ipw_control,
            "dr_difference": dr - dr_control, "ipw_difference": ipw - ipw_control,
            "matched": matched, "weights": weights, "control_weights": control_weights}


def _batch_structure(features):
    np = _numpy()
    if not features:
        raise ValueError("At least one eligible customer is required")
    ids = [row["customer_id"] for row in features]
    if len(set(ids)) != len(ids):
        raise ValueError("Original evaluation customers must be unique; bootstrap occurrences may repeat")
    # Exact daily assignment slots are the budget batches, not calendar-month groups.
    slots = [parse_ts(row["assigned_at"]).isoformat() for row in features]
    names, codes = np.unique(np.asarray(slots), return_inverse=True)
    codes = codes.astype(np.int32)
    groups = [np.flatnonzero(codes == index) for index in range(len(names))]
    return codes, groups


def make_bootstrap_indices(features, repetitions, seed):
    """Reusable int32 pool; each row resamples customers within each original slot.

    Output positions retain their original batch. Repeated source indices are
    separate eligible occurrences; they must not be deduplicated by allocators.
    """
    np = _numpy()
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 0:
        raise ValueError("Bootstrap repetitions must be a nonnegative integer")
    _, groups = _batch_structure(features)
    if len(features) > np.iinfo(np.int32).max:
        raise ValueError("Evaluation population is too large for the resampling pool")
    pool = np.empty((repetitions, len(features)), dtype=np.int32)
    rng = np.random.default_rng(seed)
    for group in groups:
        pool[:, group] = group[rng.integers(len(group), size=(repetitions, len(group)))]
    return pool


def _prepare(features, outcomes, predictions, config):
    np = _numpy()
    n = len(features)
    if len(outcomes) != n:
        raise ValueError("Feature and outcome rows must be aligned")
    codes, groups = _batch_structure(features)
    for feature, outcome in zip(features, outcomes):
        for key in ("customer_id", "assigned_at"):
            if key in outcome and outcome[key] != feature[key]:
                raise ValueError("Feature/outcome rows are not aligned")
        for field in ("is_outcome_mature", "is_profit_settled"):
            if field in outcome and outcome[field] is not True:
                raise ValueError("Policy evaluation cannot drop or score immature assignments")
    if isinstance(predictions, dict):
        nuisance = predictions.get("evaluation_profit", predictions["profit"])
    else:
        nuisance = predictions
    probability = {arm["id"]: arm["probability"] for arm in config["experiment"]["arms"]}
    if set(probability) != set(ARMS):
        raise ValueError("Exactly three configured assignment arms are required")
    tables = _score_tables(
        [row["contribution_profit_60d_krw"] for row in outcomes], [row["arm"] for row in outcomes],
        nuisance, [probability[arm] for arm in ARMS],
    )
    tables["dr_difference"] = tables["dr"] - tables["dr"][:, [0]]
    tables["ipw_difference"] = tables["ipw"] - tables["ipw"][:, [0]]
    tables["guardrail_difference"] = {}
    for metric in GUARDRAILS:
        values = np.asarray([row[metric] for row in outcomes], dtype=float)
        if not np.all(np.isfinite(values)) or not np.all((values == 0) | (values == 1)):
            raise ValueError("Guardrail outcomes must be observed binary labels")
        score = np.zeros((n, 3), dtype=float)
        score[np.arange(n), tables["arms"]] = values * tables["inverse_p"]
        tables["guardrail_difference"][metric] = score - score[:, [0]]
    constraints = config["policy_constraints"]
    rollout_n = constraints["rollout_eligible_customers"]
    if isinstance(rollout_n, bool) or not isinstance(rollout_n, int) or rollout_n <= 0:
        raise ValueError("Rollout population must be a positive integer")
    batch_sizes = np.asarray([len(group) for group in groups], dtype=np.int64)
    contact_fraction = Fraction(str(constraints["max_contact_fraction"]))
    if not 0 <= contact_fraction <= 1:
        raise ValueError("Contact capacity must be a fraction in [0, 1]")
    tables.update(
        n=n, batch_codes=codes, batch_sizes=batch_sizes,
        costs=np.asarray([0, config["offer"]["send_cost_krw_per_attempt"],
                          config["offer"]["send_cost_krw_per_attempt"] + config["offer"]["coupon_discount_krw"]], dtype=np.int64),
        budget_caps=(batch_sizes * constraints["budget_reservation_cap_krw_per_10000"]) // 10000,
        contact_caps=(batch_sizes * contact_fraction.numerator) // contact_fraction.denominator,
        rollout_n=rollout_n, setup_cost=constraints["fixed_setup_cost_krw_per_rollout"],
    )
    return tables


def _allocation_context(features, predictions, config, options):
    allocator = options.get("allocator", options.get("allocate"))
    if allocator is None:
        from .policy import allocate_policy
        allocator = allocate_policy
    if "prepared" in options:
        prepared = options["prepared"]
    elif "allocator" not in options and "allocate" not in options:
        from .policy import prepare_policy_inputs
        prepared = prepare_policy_inputs(features, predictions, config)
    else:
        prepared = None
    return allocator, prepared


def _allocate(allocator, prepared, spec, features, predictions, config, indices=None):
    result = allocator(features, predictions, spec, config, indices=indices, return_audit=False, prepared=prepared)
    values = result["actions"] if isinstance(result, dict) else result
    actions = _codes(values, len(features), "allocated actions")
    declared_caps_ok = bool(result.get("caps_ok", True)) if isinstance(result, dict) else True
    return actions, declared_caps_ok


def _cap_counts(actions, data):
    np = _numpy()
    contacts = np.bincount(data["batch_codes"], weights=actions != 0, minlength=len(data["batch_sizes"]))
    reservations = np.bincount(data["batch_codes"], weights=data["costs"][actions], minlength=len(data["batch_sizes"]))
    violations = (contacts > data["contact_caps"]) | (reservations > data["budget_caps"])
    return contacts, reservations, violations


def _exposure(actions, data, declared_caps_ok=True):
    np = _numpy()
    contacts, reservations, violations = _cap_counts(actions, data)
    counts = np.bincount(actions, minlength=3)
    return {"counts": {arm: int(counts[index]) for index, arm in enumerate(ARMS)},
            "contact_n": int(contacts.sum()), "contact_fraction": float(contacts.sum() / data["n"]),
            "reservation_total_krw": int(reservations.sum()),
            "reservation_per_customer_krw": float(reservations.sum() / data["n"]),
            "budget_cap_total_krw": int(data["budget_caps"].sum()),
            "contact_cap_total": int(data["contact_caps"].sum()),
            "batch_count": len(data["batch_sizes"]), "violating_batches": int(violations.sum()),
            "caps_ok": bool(not violations.any() and declared_caps_ok)}


def _point_summary(values, confidence):
    np = _numpy()
    n = len(values)
    estimate = float(np.mean(values))
    se = float(np.std(values, ddof=1) / math.sqrt(n)) if n > 1 else None
    margin = NormalDist().inv_cdf((1 + confidence) / 2) * se if se is not None else None
    return {"estimate": estimate, "standard_error": se, "score_standard_error": se,
            "ci_lower": estimate - margin if margin is not None else None,
            "ci_upper": estimate + margin if margin is not None else None,
            "confidence_level": confidence, "interval_method": "normal_fixed_action_score_approximation"}


def _overlap(actions, data):
    np = _numpy()

    def summary(assigned_actions):
        match = data["arms"] == assigned_actions
        weights = match * data["inverse_p"]
        total, squares = float(weights.sum()), float(np.square(weights).sum())
        nonzero = weights[match]
        return {"matched_n": int(match.sum()), "matched_fraction": float(match.mean()),
                "matched_by_arm": {arm: int(np.count_nonzero(match & (data["arms"] == code))) for code, arm in enumerate(ARMS)},
                "effective_sample_size": total * total / squares if squares else 0.0,
                "weights": {"sum": total, "sum_squares": squares, "mean_all_customers": float(weights.mean()),
                            "minimum_nonzero": float(nonzero.min()) if len(nonzero) else None,
                            "maximum": float(weights.max())}}

    return {"policy": summary(actions), "control": summary(np.zeros(data["n"], dtype=np.int8)),
            "denominator": data["n"], "normalization": "Horvitz-Thompson full-n, not matching-only or self-normalized"}


def _resampling_pool(features, data, repetitions, seed, options):
    np = _numpy()
    supplied = options.get("indices")
    pool = make_bootstrap_indices(features, repetitions, seed) if supplied is None else np.asarray(supplied)
    if pool.shape != (repetitions, data["n"]) or pool.dtype.kind not in "iu":
        raise ValueError("Shared bootstrap indices must have shape (repetitions, n)")
    if repetitions and (pool.min() < 0 or pool.max() >= data["n"]):
        raise ValueError("Bootstrap index outside the evaluation population")
    # Preserve each daily budget population, including with user-supplied pools.
    for start in range(0, repetitions, 64):
        if not np.all(data["batch_codes"][pool[start:start + 64]] == data["batch_codes"]):
            raise ValueError("Bootstrap occurrences must remain within their original assignment slot")
    return pool


def _bootstrap(spec, features, predictions, config, options, data, allocator, prepared):
    np = _numpy()
    repetitions = options.get("repetitions", config["inference"]["bootstrap_repetitions"])
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 0:
        raise ValueError("Bootstrap repetitions must be a nonnegative integer")
    if repetitions == 1:
        raise ValueError("Use at least two bootstrap repetitions, or zero for screening")
    seed = options.get("seed", config["reproducibility"]["base_seed"])
    pool = _resampling_pool(features, data, repetitions, seed, options)
    draws = {name: np.empty(repetitions, dtype=float) for name in ("dr_difference", "ipw_difference", "rollout_net_profit", *GUARDRAILS)}
    cap_violations = 0
    for index, sample in enumerate(pool):
        actions, declared_caps_ok = _allocate(allocator, prepared, spec, features, predictions, config, sample)
        draws["dr_difference"][index] = np.mean(data["dr_difference"][sample, actions])
        draws["ipw_difference"][index] = np.mean(data["ipw_difference"][sample, actions])
        for metric in GUARDRAILS:
            draws[metric][index] = np.mean(data["guardrail_difference"][metric][sample, actions])
        setup = data["setup_cost"] if np.any(actions != 0) else 0
        draws["rollout_net_profit"][index] = data["rollout_n"] * draws["dr_difference"][index] - setup
        _, _, violating = _cap_counts(actions, data)
        cap_violations += int(violating.any() or not declared_caps_ok)
    return {"draws": draws, "repetitions": repetitions, "seed": seed,
            "resampling_sha256": hashlib.sha256(pool.astype("<i4", copy=False).tobytes()).hexdigest(),
            "cap_violating_resamples": cap_violations}


def bootstrap_policy(policy_spec, features, outcomes, predictions, config, bootstrap_spec=None):
    """Low-level paired draws; rerun the fixed allocation for every resample.

    Predictions/models and policy_spec are held fixed. Returned arrays contain
    only aggregate statistics, never customer IDs or resampled row identities.
    """
    options = dict(bootstrap_spec or {})
    data = _prepare(features, outcomes, predictions, config)
    allocator, prepared = _allocation_context(features, predictions, config, options)
    return _bootstrap(policy_spec, features, predictions, config, options, data, allocator, prepared)


def evaluate_policy(policy_spec, features, outcomes, predictions, config, bootstrap_spec=None):
    """JSON-ready evaluation; B=0 is cheap selection-only normal score inference.

    Allocators receive ``profit`` for their fixed ranking, while DR uses the
    common ``evaluation_profit`` nuisance predictions when that key is supplied.
    """
    np = _numpy()
    options = dict(bootstrap_spec or {})
    data = _prepare(features, outcomes, predictions, config)
    allocator, prepared = _allocation_context(features, predictions, config, options)
    actions, declared_caps_ok = _allocate(allocator, prepared, policy_spec, features, predictions, config)
    exposure = _exposure(actions, data, declared_caps_ok)
    n, positions = data["n"], np.arange(data["n"])
    confidence = config["inference"]["confidence_level"]
    guardrail_confidence = options.get("guardrail_confidence", config["inference"]["guardrail_bonferroni_individual_one_sided_confidence"])
    if not 0.5 < confidence < 1 or not 0.5 < guardrail_confidence < 1:
        raise ValueError("Invalid evaluation confidence")
    primary = _point_summary(data["dr_difference"][positions, actions], confidence)
    ipw = _point_summary(data["ipw_difference"][positions, actions], confidence)
    for item, key in ((primary, "dr"), (ipw, "ipw")):
        item.update(estimator=key, policy_value=float(np.mean(data[key][positions, actions])),
                    control_value=float(np.mean(data[key][:, 0])))
    guardrails = []
    tolerances = {"unsubscribe_60d": config["inference"]["guardrail_max_increase_unsubscribe_pp"] / 100,
                  "refund_customer_flag": config["inference"]["guardrail_max_increase_refund_customer_pp"] / 100}
    for metric in GUARDRAILS:
        summary = _point_summary(data["guardrail_difference"][metric][positions, actions], confidence)
        upper = summary["estimate"] + NormalDist().inv_cdf(guardrail_confidence) * summary["standard_error"] if summary["standard_error"] is not None else None
        guardrails.append({"metric": metric, "estimator": "ipw_difference_vs_control", "estimate": summary["estimate"],
                           "standard_error": summary["standard_error"], "score_standard_error": summary["score_standard_error"],
                           "ci_upper": upper, "one_sided_confidence": guardrail_confidence,
                           "tolerance": tolerances[metric], "interval_method": "normal_fixed_action_score_approximation"})
    bootstrap = _bootstrap(policy_spec, features, predictions, config, options, data, allocator, prepared)
    b = bootstrap["repetitions"]
    setup = data["setup_cost"] if exposure["contact_n"] else 0
    rollout_estimate = data["rollout_n"] * primary["estimate"] - setup
    rollout_lower = data["rollout_n"] * primary["ci_lower"] - setup if primary["ci_lower"] is not None else None
    rollout_upper = data["rollout_n"] * primary["ci_upper"] - setup if primary["ci_upper"] is not None else None
    if b:
        alpha = 1 - confidence
        for item, name in ((primary, "dr_difference"), (ipw, "ipw_difference")):
            item.update(ci_lower=float(np.quantile(bootstrap["draws"][name], alpha / 2)),
                        ci_upper=float(np.quantile(bootstrap["draws"][name], 1 - alpha / 2)),
                        standard_error=float(np.std(bootstrap["draws"][name], ddof=1)),
                        interval_method="within_batch_allocation_bootstrap_percentile")
        for item in guardrails:
            values = bootstrap["draws"][item["metric"]]
            item.update(ci_upper=float(np.quantile(values, guardrail_confidence)),
                        standard_error=float(np.std(values, ddof=1)),
                        interval_method="within_batch_allocation_bootstrap_percentile")
        rollout_lower, rollout_upper = [float(value) for value in np.quantile(bootstrap["draws"]["rollout_net_profit"], [alpha / 2, 1 - alpha / 2])]
    for item in guardrails:
        item["assessment"] = "within_tolerance" if item["ci_upper"] is not None and item["ci_upper"] <= item["tolerance"] else "not_established"
    caps_ok = exposure["caps_ok"] and bootstrap["cap_violating_resamples"] == 0
    if not b:
        decision = "screening_only"
    elif not caps_ok or (rollout_upper is not None and rollout_upper < 0):
        decision = "hold"
    elif rollout_lower is not None and rollout_lower > 0 and all(row["assessment"] == "within_tolerance" for row in guardrails):
        decision = "candidate"
    else:
        decision = "modify_or_collect_more_evidence"
    result = {
        "policy_id": policy_spec.get("id"), "policy_spec": dict(policy_spec), "n": n,
        "evaluation_role": options.get("evaluation_role", "unspecified"),
        "primary": primary, "ipw_check": ipw, "guardrails": guardrails,
        "exposure": exposure, "overlap": _overlap(actions, data),
        "rollout": {"eligible_customers": data["rollout_n"], "setup_cost_krw": setup,
                    "setup_per_eligible_krw": setup / data["rollout_n"],
                    "incremental_profit_krw": rollout_estimate, "ci_lower": rollout_lower, "ci_upper": rollout_upper,
                    "caps_ok": caps_ok, "decision": decision},
        "bootstrap": {key: value for key, value in bootstrap.items() if key != "draws"},
        "methods": {
            "primary": "DR policy value minus all-control value; paired scores over every eligible customer.",
            "check": "IPW with known assignment probabilities, full-n Horvitz-Thompson normalization.",
            "nuisance": "evaluation_profit is the common frozen nuisance; profit remains the allocator ranking input.",
            "bootstrap": "Sample within each exact assigned_at batch with replacement; preserve batch sizes, keep duplicate occurrences, rerun fixed allocation and caps.",
            "quantile_method": "NumPy linear percentile; two-sided profit and one-sided guardrail bounds.",
            "guardrails": "IPW differences for unsubscribe and refund; default 97.5% upper bounds for the selected policy's two-metric family.",
            "score_se": "Fixed-action sample score SD/sqrt(n); screening approximation ignores allocation coupling and selection optimism.",
            "models_refit": False, "policy_reselected": False, "oracle_used": False,
            "uncertainty": "Conditional on frozen fitted models/policy and the empirical daily batch pattern in the synthetic world; not full training or real-market uncertainty.",
            "selection_notice": "Validation intervals used for candidate selection are selection-dependent, not final-test confirmation.",
            "setup": "Fixed rollout setup is separate from reservation caps; charged only if any contact, including in each bootstrap resample. Actual campaign costs already reside in Y.",
            "decision_scope": "A candidate label concerns only the evaluated fixed policy; multiple baseline intervals do not provide simultaneous superiority or safety claims.",
            "references": list(REFERENCES),
        },
    }
    if options.get("include_draws", False):
        result["bootstrap"]["draws"] = {key: value.tolist() for key, value in bootstrap["draws"].items()}
    return result
