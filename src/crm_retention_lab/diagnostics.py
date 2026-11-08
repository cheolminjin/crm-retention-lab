"""Training-only descriptive CRM diagnostics from observed analysis marts.

Probabilities are fractions, not percentages. No treatment comparison, policy
evaluation, model fitting, or generator/oracle state is used by this module.
"""

from collections import defaultdict
import math
from statistics import NormalDist

from .config import parse_ts


DIAGNOSTICS_VERSION = "0.1.0"


def wilson_interval(successes, total, confidence_level=0.95):
    """Return a binomial proportion and Wilson score interval, including n=0."""
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("Require 0 <= successes <= total")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must lie in (0, 1)")
    if total == 0:
        return None, None, None
    z = NormalDist().inv_cdf((1 + confidence_level) / 2)
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return rate, max(0.0, center - half), min(1.0, center + half)


def _survival_interval(survival, greenwood_sum, z):
    if survival in (0.0, 1.0):
        return survival, survival
    log_minus_log = math.log(-math.log(survival))
    standard_error = math.sqrt(greenwood_sum) / abs(math.log(survival))

    def inverse(value):
        # exp(-exp(value)) with its limiting value when exp would overflow.
        return 0.0 if value > 709 else math.exp(-math.exp(value))

    return (inverse(log_minus_log + z * standard_error),
            inverse(log_minus_log - z * standard_error))


def kaplan_meier_curve(durations, event_observed, horizon_days=60, confidence_level=0.95):
    """KM with event-before-censor ties and Greenwood log-log pointwise CIs.

    ``durations`` include censoring durations, not only event durations. Risk
    counts are immediately before the named time, including same-time events
    and censors. Integer days plus all event/censor times form the plot grid.
    Estimates beyond the largest observed duration are null, not extrapolated.
    """
    if len(durations) != len(event_observed):
        raise ValueError("Durations and event indicators must have equal lengths")
    if horizon_days <= 0 or not 0 < confidence_level < 1:
        raise ValueError("Invalid horizon or confidence level")
    removals = defaultdict(lambda: [0, 0])
    for duration, event in zip(durations, event_observed):
        if isinstance(duration, bool) or not isinstance(duration, (float, int)):
            raise ValueError("Durations must be finite numbers")
        if not math.isfinite(duration) or not 0 <= duration <= horizon_days:
            raise ValueError("Durations must lie inside the observation horizon")
        if not isinstance(event, bool):
            raise ValueError("Event indicators must be booleans")
        removals[float(duration)][0 if event else 1] += 1

    count = len(durations)
    support_end = max(durations) if count else None
    timeline = sorted(set(range(math.floor(horizon_days) + 1)) | set(removals) | {float(horizon_days)})
    z = NormalDist().inv_cdf((1 + confidence_level) / 2)
    survival, greenwood_sum, risk = 1.0, 0.0, count
    median = None
    points, censor_marks = [], []
    for day in timeline:
        events, censored = removals.get(day, (0, 0))
        before = risk
        if events:
            survival *= (before - events) / before
            if before > events:
                greenwood_sum += events / (before * (before - events))
            if median is None and survival <= 0.5:
                median = float(day)
        supported = count > 0 and day <= support_end
        lower, upper = _survival_interval(survival, greenwood_sum, z)
        point = {
            "day": float(day), "at_risk": before, "events": events, "censored": censored,
            "survival": survival if supported else None,
            "survival_ci_lower": lower if supported else None,
            "survival_ci_upper": upper if supported else None,
            "cumulative_repurchase": 1 - survival if supported else None,
            "cumulative_repurchase_ci_lower": 1 - upper if supported else None,
            "cumulative_repurchase_ci_upper": 1 - lower if supported else None,
        }
        points.append(point)
        if censored:
            censor_marks.append({"day": float(day), "n": censored,
                                 "cumulative_repurchase": 1 - survival})
        risk -= events + censored

    return {
        "n": count,
        "events": sum(event_observed),
        "censored": count - sum(event_observed),
        "support_end_day": support_end,
        "points": points,
        "censor_marks": censor_marks,
        "at_risk": [{"day": day, "n": sum(duration >= day for duration in durations)}
                    for day in (0, 14, 30, 60) if day <= horizon_days],
        "median_repurchase_days": median,
        "median_repurchase_status": "observed" if median is not None else ("not_reached" if count else "no_customers"),
    }


def _mature(outcome, as_of):
    freeze = outcome["label_freeze_at"]
    mature = (outcome["is_outcome_mature"] and outcome["is_profit_settled"]
              and freeze is not None and parse_ts(freeze) <= as_of)
    label = outcome["repeat_paid_within_60d"]
    if mature and (not isinstance(label, (bool, int)) or label not in (0, 1)):
        raise ValueError("A settled outcome must have a binary 60-day repeat label")
    return mature


def summarize_diagnostics(marts, config):
    """Summarize training controls; keep incomplete labels null and retain KM censors."""
    metadata = marts["metadata"]
    if metadata.get("analysis_scope") != "train":
        raise ValueError("Diagnostics are restricted to the prespecified training split")
    as_of = parse_ts(metadata["as_of"])
    train_start = parse_ts(config["splits"]["train"]["start_inclusive"])
    train_end = parse_ts(config["splits"]["train"]["end_exclusive"])
    horizon = config["experiment"]["outcome_horizon_days"]
    if horizon != 60:
        raise ValueError("Stage-2 diagnostics require the prespecified 60-day horizon")
    confidence = config["inference"]["confidence_level"]
    feature_rows = marts["features"]
    outcome_rows = marts["outcomes"]
    features = {row["assignment_id"]: row for row in feature_rows}
    outcomes = {row["assignment_id"]: row for row in outcome_rows}
    if len(features) != len(feature_rows) or len(outcomes) != len(outcome_rows):
        raise ValueError("Duplicate assignment in analysis mart")
    if features.keys() != outcomes.keys():
        raise ValueError("Feature and outcome assignments must match exactly")

    controls = []
    for assignment_id, feature in features.items():
        outcome = outcomes[assignment_id]
        assigned = parse_ts(feature["assigned_at"])
        if not train_start <= assigned < train_end or assigned >= as_of:
            raise ValueError("Training mart contains an out-of-scope assignment")
        for key in ("customer_id", "arm", "assigned_at"):
            if feature[key] != outcome[key]:
                raise ValueError(f"Feature/outcome {key} mismatch")
        if feature["arm"] == "control":
            duration = outcome["days_to_first_repeat_paid"]
            event = outcome["repeat_event_observed"]
            followup = min(float(horizon), (as_of - assigned).total_seconds() / 86400)
            if duration > followup or (event and duration >= followup):
                raise ValueError("KM duration/event crosses the exclusive observation end")
            if not event and not math.isclose(duration, followup, rel_tol=0, abs_tol=1e-9):
                raise ValueError("Non-event KM duration must end at administrative censoring")
            controls.append((feature, outcome))

    curves = []
    for grams in (None, 200, 500, 1000):
        group = [(feature, outcome) for feature, outcome in controls
                 if grams is None or feature["first_pack_grams"] == grams]
        curve = kaplan_meier_curve(
            [outcome["days_to_first_repeat_paid"] for _, outcome in group],
            [outcome["repeat_event_observed"] for _, outcome in group], horizon, confidence,
        )
        curves.append({"group": "all" if grams is None else f"{grams}g", "first_pack_grams": grams, **curve})

    cohort_groups = defaultdict(list)
    for feature, outcome in controls:
        cohort_groups[parse_ts(feature["assigned_at"]).strftime("%Y-%m")].append(outcome)
    cohorts = []
    for month, group in sorted(cohort_groups.items()):
        mature = all(_mature(outcome, as_of) for outcome in group)
        cells = []
        for day in (7, 14, 30, 60):
            events = sum(outcome["repeat_event_observed"] and outcome["days_to_first_repeat_paid"] < day
                         for outcome in group) if mature else None
            rate, lower, upper = wilson_interval(events, len(group), confidence) if mature else (None, None, None)
            cells.append({"day": day, "n": len(group), "events": events, "rate": rate,
                          "ci_lower": lower, "ci_upper": upper, "is_mature": mature})
        cohorts.append({"assigned_month": month, "n_control": len(group),
                        "is_fully_mature": mature, "cells": cells})

    segments = []
    segment_specs = [("first_pack_grams", grams, f"{grams}g") for grams in (200, 500, 1000)]
    segment_specs += [("tip_viewed", flag, "Tip viewed" if flag else "No tip viewed") for flag in (False, True)]
    for name, value, label in segment_specs:
        group = [(feature, outcome) for feature, outcome in controls
                 if (feature["first_pack_grams"] == value if name == "first_pack_grams"
                     else (feature["tip_views_d0_d13"] > 0) == value)]
        settled = [outcome for _, outcome in group if _mature(outcome, as_of)]
        events = sum(outcome["repeat_paid_within_60d"] for outcome in settled)
        rate, lower, upper = wilson_interval(events, len(settled), confidence)
        segments.append({"feature": name, "value": value, "label": label,
                         "n_eligible_control": len(group), "n_mature": len(settled),
                         "events": events, "rate": rate, "ci_lower": lower, "ci_upper": upper})

    settled = [outcome for _, outcome in controls if _mature(outcome, as_of)]
    events_60 = sum(outcome["repeat_paid_within_60d"] for outcome in settled)
    rate, lower, upper = wilson_interval(events_60, len(settled), confidence)
    allowed_metadata = ("analysis_scope", "as_of", "cutoff", "input_simulation_id",
                        "input_first_delivery_customers_known_as_of", "feature_columns", "feature_version")
    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "metadata": {key: metadata[key] for key in allowed_metadata if key in metadata},
        "eligibility_flow": dict(marts["eligibility_flow"]),
        "summary": {
            "train_assigned_customers": len(features),
            "control_customers": len(controls), "control_mature_customers": len(settled),
            "control_immature_customers": len(controls) - len(settled),
            "control_repurchase_60d_customers": events_60,
            "control_repurchase_60d_rate": rate,
            "control_repurchase_60d_ci_lower": lower, "control_repurchase_60d_ci_upper": upper,
            "median_repurchase_days": curves[0]["median_repurchase_days"],
            "median_repurchase_status": curves[0]["median_repurchase_status"],
        },
        "cohorts": cohorts, "km_curves": curves, "segments": segments,
        "methods": {
            "data_origin": "fully_synthetic",
            "interpretation": "Descriptive diagnostic associations; not causal timing or treatment effects.",
            "population": "Train, D14-eligible, randomized no-contact control customers.",
            "time_origin": "Assignment, 14 days after first delivery.",
            "outcome_interval": "[assignment, assignment + 60 days)",
            "cohort_interval": "[assignment, assignment + named day)",
            "cohort_maturity": "All controls in a displayed cohort must pass their 90-day label freeze; otherwise all cells are null.",
            "segment_denominator": "Control customers with settled 90-day labels; unobserved outcomes are never zero.",
            "km_estimator": "Kaplan-Meier; events before censoring at tied times.",
            "km_censoring": "Administrative min(60 days, as_of - assigned_at); unsubscribe does not censor purchases.",
            "km_interval": "Pointwise Greenwood log-log survival interval, transformed to 1-S(t).",
            "at_risk_convention": "Immediately before each named time, including same-time events and censors.",
            "unsupported_tail": "Values after largest observed duration are null; no extrapolation.",
            "proportion_interval": "Wilson score interval.",
            "confidence_level": confidence,
            "uncertainty_scope": "Sampling uncertainty within the fixed synthetic world, not real-market uncertainty.",
            "probability_unit": "fraction_0_to_1",
            "oracle_used": False,
            "treatment_comparisons_performed": False,
        },
    }
