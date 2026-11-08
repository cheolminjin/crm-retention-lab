"""Configuration loading, timestamps, and stable simulation identities."""

import copy
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

SUPPORTED_SCENARIOS = ("base", "no_behavior_effect", "a_a_zero_cost")


def parse_ts(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"Timezone required: {value}")
    return timestamp


def iso(value):
    if value.tzinfo is None:
        raise ValueError("Timezone required")
    return value.isoformat(timespec="seconds")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def config_hash(config):
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def simulation_id(config):
    return "sim-" + config_hash(config)[:16]


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def load_config(path, *, customers=None, seed=None, scenario=None):
    path = Path(path).resolve()
    profile = json.loads(path.read_text(encoding="utf-8"))
    design = json.loads((path.parent / profile["design_file"]).read_text(encoding="utf-8"))
    generator = json.loads((path.parent / profile["generator_file"]).read_text(encoding="utf-8"))
    _merge(design, profile.get("overrides", {}))
    design["generator"] = generator
    design["runtime"] = {
        "profile_version": profile["profile_version"],
        "purpose": profile["purpose"],
        "scenario": scenario or profile.get("scenario", "base"),
    }
    if customers is not None:
        design["population"]["first_delivery_customers"] = customers
    if seed is not None:
        design["reproducibility"]["base_seed"] = seed
    validate_config(design)
    return design


def validate_config(config):
    population, experiment = config["population"], config["experiment"]
    count = population["first_delivery_customers"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("first_delivery_customers must be a positive integer")
    start = parse_ts(population["first_delivery_start_inclusive"])
    end = parse_ts(population["first_delivery_end_exclusive"])
    cutoff = parse_ts(population["observation_end_exclusive"])
    if not start < end <= cutoff:
        raise ValueError("Require delivery start < delivery end <= observation cutoff")
    if config["timezone"] != "Asia/Seoul" or any(
        stamp.utcoffset() != timedelta(hours=9) for stamp in (start, end, cutoff)
    ):
        raise ValueError("Stage 1 requires Asia/Seoul timestamps with +09:00 offsets")
    if population["first_delivery_daily_slot_local"] != "09:00:00":
        raise ValueError("Stage 1 uses the prespecified 09:00 delivery/assignment slot")
    if config["runtime"]["scenario"] not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Supported stage-1 scenarios: {SUPPORTED_SCENARIOS}")
    arms = experiment["arms"]
    if {arm["id"] for arm in arms} != {"control", "info", "coupon"} or len(arms) != 3:
        raise ValueError("Exactly three unique arms required")
    probabilities = [arm["probability"] for arm in arms]
    if any(not math.isfinite(p) or p <= 0 or p >= 1 for p in probabilities):
        raise ValueError("Arm probabilities must be finite and in (0, 1)")
    if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-12):
        raise ValueError("Arm probabilities must sum to one")
    if population["operational_reporting_lag_days"] != 0:
        raise ValueError("Eligibility operational records must be immediate")
    if population["max_order_adjustment_recording_days_after_payment"] > experiment["settlement_lag_days"]:
        raise ValueError("Settlement wait must cover all financial adjustments")
    for key in ("assignment_offset_days", "outcome_horizon_days", "settlement_lag_days"):
        if experiment[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if config["offer"]["coupon_valid_days"] > experiment["outcome_horizon_days"]:
        raise ValueError("Coupon validity must fit in the outcome horizon")
    offer = config["offer"]
    if offer["allow_stacking"] or offer["coupon_max_redemptions"] != 1 or offer["attempts_per_customer"] != 1:
        raise ValueError("Stage 1 supports one attempt and one nonstacking coupon")
    if not 0 < offer["coupon_discount_krw"] <= offer["coupon_min_list_subtotal_krw"]:
        raise ValueError("Coupon must be positive and no larger than its minimum purchase")
    catalog = config["catalog"]
    if len(catalog) != 3 or [p["grams"] for p in catalog] != [200, 500, 1000]:
        raise ValueError("Stage 1 catalog must contain 200g, 500g, 1000g in that order")
    if len({p["sku"] for p in catalog}) != len(catalog):
        raise ValueError("Catalog SKU identifiers must be unique")
    for product in catalog:
        for key in ("list_price_krw", "unit_cogs_krw"):
            if isinstance(product[key], bool) or not isinstance(product[key], int) or product[key] < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
    generator = config["generator"]
    refund, delivery = generator["refund"], generator["delivery"]
    if not 1 <= delivery["lead_days_min"] <= delivery["lead_days_max"]:
        raise ValueError("Invalid delivery lead bounds")
    if not delivery["lead_days_max"] <= refund["days_after_payment_min"] <= refund["days_after_payment_max"] <= population["max_order_adjustment_recording_days_after_payment"]:
        raise ValueError("Refund timing must follow delivery and fit the settlement bound")
    if not 0 <= refund["recovery_fraction"] <= 1:
        raise ValueError("Inventory recovery fraction must lie in [0, 1]")
    for group in generator.values():
        if not isinstance(group, dict):
            continue
        for key, value in group.items():
            if key.endswith("_probability") and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{key} must lie in [0, 1]")
    customer = generator["customer"]
    if not 0 < customer["consumption_grams_daily_min"] <= customer["consumption_grams_daily_max"]:
        raise ValueError("Consumption bounds must be positive and ordered")
    if not 0 <= customer["first_discount_fraction"] <= 1:
        raise ValueError("First discount fraction must lie in [0, 1]")
    if any(customer[key] <= 0 for key in (
        "preference_beta_alpha", "preference_beta_beta", "price_sensitivity_beta_alpha", "price_sensitivity_beta_beta"
    )):
        raise ValueError("Beta distribution parameters must be positive")
    behavior = generator["behavior"]
    if behavior["daily_base_odds"] < 0 or behavior["depletion_peak_odds"] < 0 or behavior["depletion_width_days"] <= 0:
        raise ValueError("Purchase odds must be nonnegative and the depletion width positive")
    if not 0 <= behavior["seasonal_odds_amplitude"] < 1:
        raise ValueError("Seasonal odds amplitude must lie in [0, 1)")
