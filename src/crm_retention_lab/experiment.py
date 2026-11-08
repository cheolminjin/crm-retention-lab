"""Prespecified, training-only three-arm ITT mean effects.

No delivery/open/coupon-use filter is allowed here. Inference starts only after
the complete training roster and every assigned customer's label have matured.
SciPy is imported lazily for Student-t quantiles and tail probabilities.
"""

from datetime import timedelta
from functools import lru_cache
import math
from statistics import variance

from .config import parse_ts
from .diagnostics import wilson_interval


PRIMARY = "contribution_profit_60d_krw"
BINARY_METRICS = ("repeat_paid_within_60d", "unsubscribe_60d", "refund_customer_flag")
COUNT_METRIC = "order_count_60d"
ARMS = ("control", "info", "coupon")
COMPARISONS = ("info_vs_control", "coupon_vs_control", "coupon_vs_info")


@lru_cache(maxsize=1)
def _student_t():
    try:
        from scipy.stats import t
    except ImportError as error:
        raise ImportError("Stage-3 Welch inference requires the optional SciPy analysis dependency") from error
    return t


def holm_adjust(p_values):
    """Holm adjusted p-values in input order; unavailable tests keep family size.

    An unavailable p-value is treated as one for ordering/adjustment, but its
    returned value stays None. Dropping it would shrink the prespecified family.
    """
    for value in p_values:
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("p-values must be finite and in [0, 1]")
    ordered = sorted(range(len(p_values)), key=lambda i: 1.0 if p_values[i] is None else p_values[i])
    adjusted, running = [None] * len(p_values), 0.0
    for rank, index in enumerate(ordered):
        value = 1.0 if p_values[index] is None else p_values[index]
        running = max(running, min(1.0, (len(p_values) - rank) * value))
        if p_values[index] is not None:
            adjusted[index] = running
    return adjusted


def newcombe_interval(successes_treatment, n_treatment, successes_reference, n_reference,
                      confidence_level=0.95, *, one_sided=False):
    """Independent risk difference using Newcombe method 10 (no continuity correction).

    For a one-sided upper bound, use z=Phi^-1(confidence_level). The return is
    (difference, None, upper); the lower tail is not another guardrail test.
    Reference: statsmodels confint_proportions_2indep(method='newcomb').
    """
    for events, count in ((successes_treatment, n_treatment), (successes_reference, n_reference)):
        if type(events) is not int or type(count) is not int or not 0 <= events <= count:
            raise ValueError("Binomial counts must be nonnegative integers with events <= n")
    if not 0.5 < confidence_level < 1:
        raise ValueError("Confidence level must be in (0.5, 1)")
    if not n_treatment or not n_reference:
        return None, None, None
    # A two-sided Wilson interval with coverage 2*c-1 uses the one-sided z_c.
    wilson_confidence = 2 * confidence_level - 1 if one_sided else confidence_level
    p_t, lower_t, upper_t = wilson_interval(successes_treatment, n_treatment, wilson_confidence)
    p_r, lower_r, upper_r = wilson_interval(successes_reference, n_reference, wilson_confidence)
    difference = p_t - p_r
    lower = max(-1.0, difference - math.hypot(p_t - lower_t, upper_r - p_r))
    upper = min(1.0, difference + math.hypot(upper_t - p_t, p_r - lower_r))
    return difference, None if one_sided else lower, upper


def _numeric_summary(values, metric, confidence):
    count = len(values)
    total = sum(values)  # Preserve exact integer KRW totals; do not cast to float.
    mean = total / count if count else None
    result = {"metric": metric, "n": count, "sum": total, "mean": mean,
              "sd": None, "sem": None, "ci_lower": None, "ci_upper": None,
              "confidence_level": confidence, "interval_method": "student_t_mean",
              "status": "empty_arm" if not count else "insufficient_sample"}
    if count < 2:
        return result
    sd = math.sqrt(variance(values))
    sem = sd / math.sqrt(count)
    result.update(sd=sd, sem=sem)
    if not sem:
        result["status"] = "zero_variance"
        return result
    margin = float(_student_t().ppf((1 + confidence) / 2, count - 1)) * sem
    result.update(ci_lower=mean - margin, ci_upper=mean + margin, status="ok")
    return result


def welch_comparison(treatment, reference, confidence_level=0.95):
    """Independent mean difference; degenerate inference is explicit JSON null."""
    if not 0.5 < confidence_level < 1:
        raise ValueError("Confidence level must be in (0.5, 1)")
    for value in (*treatment, *reference):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Welch outcomes must be finite numbers")
    nt, nr = len(treatment), len(reference)
    result = {
        "n_treatment": nt, "n_reference": nr,
        "estimate": sum(treatment) / nt - sum(reference) / nr if nt and nr else None,
        "standard_error": None, "degrees_of_freedom": None, "t_statistic": None,
        "ci_lower": None, "ci_upper": None, "p_value": None,
        "confidence_level": confidence_level, "interval_method": "welch_t",
        "status": "empty_arm" if not nt or not nr else "insufficient_sample",
    }
    if nt < 2 or nr < 2:
        return result
    vt, vr = variance(treatment) / nt, variance(reference) / nr
    se = math.sqrt(vt + vr)
    result["standard_error"] = se
    if not se:
        result["status"] = "undefined_zero_standard_error"
        return result
    df = (vt + vr) ** 2 / (vt ** 2 / (nt - 1) + vr ** 2 / (nr - 1))
    statistic = result["estimate"] / se
    distribution = _student_t()
    margin = float(distribution.ppf((1 + confidence_level) / 2, df)) * se
    result.update(
        degrees_of_freedom=df, t_statistic=statistic,
        ci_lower=result["estimate"] - margin, ci_upper=result["estimate"] + margin,
        p_value=float(2 * distribution.sf(abs(statistic), df)), status="ok",
    )
    return result


def _binary_summary(values, metric, confidence):
    events, count = sum(values), len(values)
    rate, lower, upper = wilson_interval(events, count, confidence)
    return {"metric": metric, "n": count, "events": events, "sum": events,
            "mean": rate, "rate": rate, "ci_lower": lower, "ci_upper": upper,
            "confidence_level": confidence, "interval_method": "wilson_score",
            "status": "ok" if count else "empty_arm"}


def _binary_comparison(treatment, reference, confidence):
    estimate, lower, upper = newcombe_interval(sum(treatment), len(treatment), sum(reference), len(reference), confidence)
    return {"n_treatment": len(treatment), "n_reference": len(reference),
            "events_treatment": sum(treatment), "events_reference": sum(reference),
            "estimate": estimate, "ci_lower": lower, "ci_upper": upper,
            "confidence_level": confidence, "interval_method": "newcombe_independent_score",
            "status": "ok" if treatment and reference else "empty_arm",
            "p_value": None, "p_value_holm": None, "exploratory": True}


def summarize_experiment(marts, config):
    """Return aggregate ITT comparisons or readiness counts, never partial-arm estimates."""
    metadata = marts["metadata"]
    if metadata.get("analysis_scope") != "train":
        raise ValueError("Stage-3 experiment estimates are restricted to train")
    as_of = parse_ts(metadata["as_of"])
    if as_of > min(parse_ts(config["population"]["observation_end_exclusive"]),
                   parse_ts(config["splits"]["train_labels_available_by"]), parse_ts(metadata["cutoff"])):
        raise ValueError("Analysis time exceeds source coverage or the training readout")
    train_start = parse_ts(config["splits"]["train"]["start_inclusive"])
    train_end = parse_ts(config["splits"]["train"]["end_exclusive"])
    horizon = timedelta(days=config["experiment"]["outcome_horizon_days"])
    lag = timedelta(days=config["experiment"]["settlement_lag_days"])
    if config["experiment"]["primary_outcome"] != PRIMARY:
        raise ValueError("Unexpected primary outcome")
    inference = config["inference"]
    confidence = inference["confidence_level"]
    family_alpha = inference["guardrail_familywise_one_sided_alpha"]
    comparisons = inference["prespecified_arm_comparisons"]
    if len(comparisons) != 3 or set(comparisons) != set(COMPARISONS):
        raise ValueError("The primary family must contain all three prespecified arm comparisons")
    if not 0.5 < confidence < 1 or not 0 < family_alpha < 0.5:
        raise ValueError("Invalid inference confidence or familywise alpha")
    if inference["arm_comparison_adjustment"] != "holm_for_all_three_pairwise_arm_comparisons":
        raise ValueError("The primary comparison family requires Holm adjustment")
    arm_config = config["experiment"]["arms"]
    if len(arm_config) != 3 or {row["id"] for row in arm_config} != set(ARMS):
        raise ValueError("Exactly control, info and coupon arms are required")
    features = {row["assignment_id"]: row for row in marts["features"]}
    outcomes = {row["assignment_id"]: row for row in marts["outcomes"]}
    if len(features) != len(marts["features"]) or len(outcomes) != len(marts["outcomes"]):
        raise ValueError("Duplicate assignment IDs are not allowed")
    if features.keys() != outcomes.keys():
        raise ValueError("Feature/outcome assignments must match exactly")
    if len({row["customer_id"] for row in features.values()}) != len(features):
        raise ValueError("Each randomized customer must appear once")
    if marts["eligibility_flow"]["assigned_total"] != len(features):
        raise ValueError("ITT rows do not match the assignment denominator")
    if metadata.get("selected_assignments", len(features)) != len(features):
        raise ValueError("ITT rows do not match mart metadata")
    by_arm = {arm: {"n_assigned": 0, "n_mature": 0, "n_immature": 0} for arm in ARMS}
    grouped = {arm: [] for arm in ARMS}
    for aid, feature in features.items():
        outcome = outcomes[aid]
        for field in ("customer_id", "arm", "assigned_at"):
            if feature[field] != outcome[field]:
                raise ValueError(f"Feature/outcome {field} mismatch")
        arm = feature["arm"]
        if arm not in grouped:
            raise ValueError("Unknown randomized arm")
        assigned = parse_ts(feature["assigned_at"])
        if not train_start <= assigned < train_end or assigned >= as_of:
            raise ValueError("Out-of-scope training assignment")
        settlement = assigned + horizon + lag
        freeze = outcome["label_freeze_at"]
        if freeze is not None and parse_ts(freeze) != settlement:
            raise ValueError("The final label freeze must equal assignment + horizon + settlement lag")
        if any(type(outcome[field]) is not bool for field in ("is_outcome_mature", "is_profit_settled")):
            raise ValueError("Maturity indicators must be booleans")
        mature = (outcome["is_outcome_mature"] and outcome["is_profit_settled"]
                  and freeze is not None and settlement <= as_of)
        by_arm[arm]["n_assigned"] += 1
        by_arm[arm]["n_mature" if mature else "n_immature"] += 1
        grouped[arm].append(outcome)
    original_arm_counts = marts["eligibility_flow"].get("assigned_by_arm")
    if original_arm_counts is not None and original_arm_counts != {
        arm: by_arm[arm]["n_assigned"] for arm in ARMS
    }:
        raise ValueError("ITT arm denominators do not match the original assignment flow")
    total_mature = sum(group["n_mature"] for group in by_arm.values())
    # Prevent an early snapshot from looking complete merely because later
    # training assignments have not yet appeared in its feature mart.
    roster_end = min(train_end, parse_ts(config["population"]["first_delivery_end_exclusive"])
                     + timedelta(days=config["experiment"]["assignment_offset_days"]))
    reasons = []
    if as_of < roster_end:
        reasons.append("training_roster_not_complete")
    if total_mature != len(features):
        reasons.append("not_all_assignments_settled")
    if any(not counts["n_assigned"] for counts in by_arm.values()):
        reasons.append("empty_randomized_arm")
    population = {"total_assigned": len(features), "total_mature": total_mature,
                  "total_immature": len(features) - total_mature, "by_arm": by_arm,
                  "training_roster_complete": as_of >= roster_end}
    methods = {
        "analysis_principle": "intention_to_treat",
        "population": "D14-eligible randomized training customers in the fixed synthetic world",
        "maturity_policy": "All training assignments must settle; no dropping immature customers or failed/unopened contacts",
        "primary_metric": PRIMARY, "primary_comparisons": list(comparisons),
        "mean_interval": "Student-t mean interval; sample SD uses n-1",
        "difference_interval": "Welch-Satterthwaite two-sided t interval, individual coverage only",
        "primary_p_adjustment": "Holm, fixed family of three two-sided primary p-values",
        "binary_arm_interval": "Wilson score, no continuity correction",
        "binary_difference_interval": "Newcombe independent method 10, Wilson components, no continuity correction",
        "secondary_inference": "Exploratory individual intervals; no multiple-comparison superiority claims",
        "guardrail_family": "Two active arms versus control, times unsubscribe and refund: four upper bounds",
        "guardrail_family_size": 4, "guardrail_familywise_alpha": family_alpha,
        "guardrail_individual_one_sided_confidence": 1 - family_alpha / 4,
        "guardrail_interval": "One-sided Newcombe score upper bound, z = Phi^-1(1-alpha/4)",
        "score_coverage": "Score intervals and Bonferroni family coverage are nominal approximations, not exact binomial guarantees",
        "final_policy_guardrail_distinction": "The configured two-metric final-policy 97.5% rule is not used for this four-comparison arm-RCT family",
        "zero_variance_policy": "Point estimates retained; undefined t inference is null, never infinity or a manufactured p-value",
        "probability_unit": "fraction_0_to_1; risk differences are fractions, not percentage points",
        "uncertainty_scope": "Sampling uncertainty in the specified synthetic world, not real-market uncertainty",
        "policy_approval": False, "oracle_used": False, "final_test_used": False,
        "references": [
            "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html",
            "https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html",
        ],
    }
    result = {
        "experiment_version": "0.1.0", "status": "not_ready" if reasons else "ready",
        "readiness_reasons": reasons,
        "metadata": {key: metadata[key] for key in ("analysis_scope", "as_of", "cutoff", "input_simulation_id")},
        "population": population, "arm_summaries": [], "primary_comparisons": [],
        "secondary_comparisons": [], "guardrails": [], "methods": methods,
    }
    result["metadata"]["confidence_level"] = confidence
    if reasons:
        return result

    metrics = (PRIMARY, *BINARY_METRICS, COUNT_METRIC)
    values = {arm: {metric: [] for metric in metrics} for arm in ARMS}
    for arm, rows in grouped.items():
        for row in rows:
            for metric in metrics:
                value = row[metric]
                if metric in BINARY_METRICS:
                    if type(value) not in (int, bool) or value not in (0, 1):
                        raise ValueError(f"Settled {metric} must be a binary label")
                    value = int(value)
                elif type(value) is not int or (metric == COUNT_METRIC and value < 0):
                    raise ValueError(f"Settled {metric} must be an integer")
                values[arm][metric].append(value)
        secondary = {metric: _binary_summary(values[arm][metric], metric, confidence) for metric in BINARY_METRICS}
        secondary[COUNT_METRIC] = _numeric_summary(values[arm][COUNT_METRIC], COUNT_METRIC, confidence)
        result["arm_summaries"].append({
            "arm": arm, "n": len(rows), "primary": _numeric_summary(values[arm][PRIMARY], PRIMARY, confidence),
            "secondary": secondary,
        })
    for comparison in comparisons:
        treatment, reference = comparison.split("_vs_")
        common = {"comparison": comparison, "treatment_arm": treatment, "reference_arm": reference}
        primary = welch_comparison(values[treatment][PRIMARY], values[reference][PRIMARY], confidence)
        result["primary_comparisons"].append({**common, "metric": PRIMARY, **primary})
        for metric in (*BINARY_METRICS, COUNT_METRIC):
            comparison_result = (_binary_comparison(values[treatment][metric], values[reference][metric], confidence)
                                 if metric in BINARY_METRICS else welch_comparison(values[treatment][metric], values[reference][metric], confidence))
            result["secondary_comparisons"].append({**common, "metric": metric, **comparison_result, "exploratory": True})
    adjusted = holm_adjust([row["p_value"] for row in result["primary_comparisons"]])
    for row, p_value in zip(result["primary_comparisons"], adjusted):
        row["p_value_holm"] = p_value
        row["reject_after_holm"] = p_value < 1 - confidence if p_value is not None else None
    guardrail_confidence = 1 - family_alpha / 4
    limits = {"unsubscribe_60d": inference["guardrail_max_increase_unsubscribe_pp"] / 100,
              "refund_customer_flag": inference["guardrail_max_increase_refund_customer_pp"] / 100}
    for treatment in ("info", "coupon"):
        for metric, tolerance in limits.items():
            if not math.isfinite(tolerance) or not 0 <= tolerance <= 1:
                raise ValueError("Guardrail tolerances must be between 0 and 100 percentage points")
            tv, rv = values[treatment][metric], values["control"][metric]
            estimate, _, upper = newcombe_interval(sum(tv), len(tv), sum(rv), len(rv), guardrail_confidence, one_sided=True)
            result["guardrails"].append({
                "comparison": f"{treatment}_vs_control", "metric": metric,
                "treatment_arm": treatment, "reference_arm": "control",
                "n_treatment": len(tv), "n_reference": len(rv),
                "events_treatment": sum(tv), "events_reference": sum(rv),
                "estimate": estimate, "ci_upper": upper,
                "one_sided_confidence": guardrail_confidence, "familywise_alpha": family_alpha,
                "family_size": 4, "tolerance": tolerance,
                "assessment": "within_tolerance" if upper <= tolerance else "not_established",
                "status": "ok", "interval_method": "newcombe_one_sided_score",
            })
    return result
