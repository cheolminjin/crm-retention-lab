"""Reproducible, observed-only diagnostic artifacts and a Quarto source report."""

import importlib.metadata
import importlib.util
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from .config import config_hash
from .contracts import validate_dataset
from .diagnostics import summarize_diagnostics
from .marts import build_marts
from .storage import file_hash, load_observed, verify_run_hashes


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _pack_label(value):
    return str(value).replace("1000g", "1,000g")


def _pct(value):
    return "NA" if value is None else f"{value:.1%}"


def _table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def build_report_source(diagnostics, figure_html=None, *, experiment=None, experiment_checks=None, policy_analysis=None):
    """Build narrative from aggregate results; do not insert individual records."""
    summary, flow, meta = (diagnostics[key] for key in ("summary", "eligibility_flow", "metadata"))
    packs = [row for row in diagnostics["segments"] if row["feature"] == "first_pack_grams"]
    rates = [row for row in packs if row["rate"] is not None]
    if rates:
        low, high = min(rates, key=lambda row: row["rate"]), max(rates, key=lambda row: row["rate"])
        finding = (f"60-day repurchase by first package: {_pack_label(high['label'])}: {_pct(high['rate'])}, {_pack_label(low['label'])}: {_pct(low['rate'])}. The observed gap of {100 * (high['rate'] - low['rate']):.1f} pp describes a customer-group difference. It does not mean that changing package size or sending a coupon would produce that improvement.")
    else:
        finding = 'Settled repurchase rates by customer group are not yet available for comparison. Assessment must wait until the observation window is complete.'
    median = summary["median_repurchase_days"]
    median_text = f'{median:.1f} days' if median is not None else 'Not reached'
    median_note = (f'Cumulative repurchase in the full control group reaches 50% at {median:.1f} days after assignment, or approximately {median + 14:.1f} days after first delivery.' if median is not None else
                   'Cumulative repurchase in the full control group did not reach 50% within the observation window.')
    pack_table = _table(['First package', 'Settled customers', 'Repurchasers', '60-day repurchase', '95% interval'], [
        [_pack_label(row["label"]), f"{row['n_mature']:,}", f"{row['events']:,}", _pct(row["rate"]),
         f"{_pct(row['ci_lower'])}–{_pct(row['ci_upper'])}"] for row in packs])
    risk_table = _table(['Group', 'Before assignment', 'Before day 14', 'Before day 30', 'Before day 60'], [
        ['All' if row["group"] == "all" else _pack_label(row["group"])] + [f"{point['n']:,}" for point in row["at_risk"]]
        for row in diagnostics["km_curves"]])
    reason_names = {"additional_paid_order": 'Additional payment before assignment', "consent_not_granted": 'No email consent',
                    "email_not_enabled": 'Email unavailable', "first_order_cancelled": 'First order cancelled',
                    "first_order_fully_refunded": 'First order fully refunded'}
    reasons = _table(['Exclusion reason', 'Customers · overlaps allowed'], [
        [reason_names.get(reason, reason), f'{count:,}'] for reason, count in flow["exclusion_reason_counts"].items()])
    def chart(name):
        fragment = figure_html[name] if figure_html is not None else '{{< include assets/figures/' + name + '.html >}}'
        return '\n```{=html}\n<div class="figure-card">\n' + fragment + '\n</div>\n```\n'
    experiment_section = ""
    experiment_lead = ""
    title = 'When customers return after their first purchase'
    subtitle = 'Repurchase diagnosis for a fictional coffee retailer · Marketing planning portfolio'
    stage = "STAGE 02 / CUSTOMER DIAGNOSIS"
    intro = (f"From a synthetic population of {flow['first_delivery_customers']:,} customers, we selected {summary['train_assigned_customers']:,} eligible CRM customers. We examined natural repurchase among the {summary['control_customers']:,} customers assigned no message and identified groups and questions for the next experiment.")
    transition = ('This stage does not conclude whether coupons or the campaign improve profit. Next, we check balance in the existing randomized assignments and estimate the incremental effects of information and coupons using ITT, including failed sends. Final-evaluation customers are reserved for one evaluation after policy selection.')
    methods_number = 5
    if experiment is not None:
        from .experiment_reporting import build_experiment_section
        experiment_section = build_experiment_section(experiment, experiment_checks, figure_html)
        title = 'Which CRM treatment adds profit after a first purchase?'
        subtitle = 'Repurchase diagnosis and a three-arm experiment · Marketing planning portfolio'
        stage = "STAGE 02 + 03 / DIAGNOSIS & EXPERIMENT"
        intro = (f"From a synthetic population of {flow['first_delivery_customers']:,} customers, {summary['train_assigned_customers']:,} eligible customers were assigned to no contact, information, or information plus coupon. We diagnose natural repurchase and compare incremental contribution profit after discount and refund settlement. Sections 5–8 report effects, costs, and side effects together.")
        transition = ('The following analysis estimates average effects from the prespecified randomized assignment logs. Observed customer-group differences are distinguished from randomized arm differences, and failed sends remain in the original assigned arm. Customer-level policy selection, validation, and final evaluation have not yet been performed at this stage.')
        methods_number = 9
        effects = {row["comparison"]: row["estimate"] for row in experiment["primary_comparisons"]}
        passed = sum(row["assessment"] == "within_tolerance" for row in experiment["guardrails"])
        if all(value is not None for value in effects.values()):
            experiment_lead = (f'''
::: {{.decision-box}}
**Experiment results:** incremental contribution profit per customer is **{effects['info_vs_control']:+,.0f} KRW** for information − no contact, **{effects['coupon_vs_control']:+,.0f} KRW** for information + coupon − no contact, and **{effects['coupon_vs_info']:+,.0f} KRW** for information + coupon − information. Side-effect criteria are within tolerance in **{passed} of 4 comparisons**. Profit intervals, side effects, and operating constraints are considered jointly in the deployment decision.
:::
''')
    policy_section = ""
    stamp_scope = f"Training split only · As of {meta['as_of'][:10]}"
    if policy_analysis is not None:
        from .policy_reporting import build_policy_section
        policy_section = build_policy_section(policy_analysis, figure_html)
        title = 'After a first purchase, who should receive which CRM treatment?'
        subtitle = 'Repurchase diagnosis · Three-arm experiment · Customer policies under budget and side-effect constraints'
        stage = "STAGE 02–04 / DIAGNOSIS, EXPERIMENT & POLICY"
        intro = ('The decision is whether to send information, information plus a coupon, or no message to each customer. Sections 1–4 diagnose natural repurchase; sections 5–8 estimate average training-experiment effects; sections 9–12 independently evaluate a policy fixed on separate validation data. Incremental profit and side effects are assessed alongside reservation-budget and contact constraints.')
        transition = ('Sections 5–8 report average training-experiment effects; sections 9–12 connect these to customer-level allocation. Models use training customers only. The policy was selected and locked on validation data before evaluating separately generated final customers.')
        methods_number = 13
        stamp_scope = 'Sections 1–8: training as of 2025-10-01 · Sections 9–12: validation 2026-03-01 / final 2026-08-01'
        experiment_section = experiment_section.replace('In the next policy stage,', 'In the following policy stage,')
        selected = next(row for row in policy_analysis["final"] if row["policy_id"] == policy_analysis["selection"]["chosen_policy"]["id"])
        estimate = selected["primary"]
        experiment_lead = (f'''
::: {{.decision-box}}
**Independent final evaluation of the selected policy:** incremental contribution profit per eligible customer **{estimate['estimate']:+,.0f} KRW** (95% interval {estimate['ci_lower']:+,.0f}~{estimate['ci_upper']:+,.0f} KRW), contact rate **{selected['exposure']['contact_fraction']:.1%}**. Section 12 reports the final decision, including costs and upper confidence bounds for both side effects.
:::
''')
    return f'''---
title: "{title}"
subtitle: "{subtitle}"
author: "CRM Retention Lab"
date: "2026-11-08"
date-format: "YYYY-MM-DD"
include-in-header:
  - text: |
      <script src="assets/plotly.min.js"></script>
---

::: {{.report-kicker}}
{stage}
:::

::: {{.report-summary}}
**Which repurchase offer should be tested for which customers?**  
{intro}
:::

{experiment_lead}

::: {{.data-stamp}}
Self-generated synthetic data · {stamp_scope}  
Assignment 14 days after first delivery → 60 days of additional payments → 30 further days for settlement  
Snapshot `{meta['input_simulation_id']}`
:::

```{{=html}}
<div class="metric-grid">
<div class="metric-card"><span class="metric-value">{summary['control_customers']:,}</span><span class="metric-label">No-contact control · customers</span></div>
<div class="metric-card"><span class="metric-value">{_pct(summary['control_repurchase_60d_rate'])}</span><span class="metric-label">Repurchase within 60 days</span></div>
<div class="metric-card"><span class="metric-value">{median_text}</span><span class="metric-label">Median repurchase time · after assignment</span></div>
<div class="metric-card"><span class="metric-value">{summary['control_mature_customers']:,}</span><span class="metric-label">90-day settlement complete · customers</span></div>
</div>
```

## 1. CRM eligibility and exclusions

Eligible customers made no additional payment during the 14 days after first delivery and meet first-order status, consent, and email requirements. Customers are randomized to no contact, information, or information plus a coupon. **The repurchase diagnosis in sections 1–4 uses only the no-contact arm.**

{chart('eligibility_flow')}

The {flow['ineligible']:,} excluded customers include both customers who already repurchased and do not need this campaign and customers who do not meet contact requirements. They cannot all be interpreted as churned customers.

{reasons}

::: {{.method-note}}
The denominator consists of customers with confirmed first delivery whose scheduled D+14 assignment falls in the training period. Exclusion reasons can overlap, so their counts may not sum to the number of excluded customers.
:::

## 2. Cumulative repurchase by assignment month

Rows group no-contact customers by **assignment month**; columns show days **since assignment**. Darker cells indicate a higher proportion making an additional payment within that period. Hover for customer counts and 95% intervals.

{chart('cohort_heatmap')}

Monthly differences reflect both customer composition and the synthetic generation rules, so this table cannot establish that a particular month's operations or content were more effective. A row remains NA if the full monthly cohort has not completed 90-day settlement.

## 3. Repurchase timing by customer group

{median_note} The curves show **Kaplan–Meier cumulative repurchase, 1−S(t)**, incorporating time to first repurchase. Customers without a purchase remain in the denominator while observed and are right-censored at observation end.

{chart('pack_km')}

Click a legend entry to toggle a package-size curve and its interval together. Hover over a curve to view the risk set and cumulative repurchase at that time.

{risk_table}

::: {{.method-note}}
The risk set comprises customers still observed who have not repurchased **immediately before** the stated time. Table values count customers. Customers whose follow-up ends at the 60-day boundary are included immediately before that boundary. Intervals are pointwise 95% Greenwood log-log intervals.
:::

::: {{.decision-box}}
**Planning implication:** natural repurchase timing can inform message scenarios. The sending day is fixed at D+14 in this experiment. A time read from these curves therefore cannot be established as the optimal sending day. Timing effects require a separate randomized experiment.
:::

## 4. Customer-group differences and next hypotheses

{finding}

{chart('pack_repeat_60d')}

{pack_table}

Among the full control group of {summary['control_mature_customers']:,} customers, {summary['control_repurchase_60d_customers']:,} repurchased, a rate of {_pct(summary['control_repurchase_60d_rate'])}, with a Wilson 95% interval of {_pct(summary['control_repurchase_60d_ci_lower'])}–{_pct(summary['control_repurchase_60d_ci_upper'])}. First package size is observed before assignment, but may also reflect differences in purchase motivation, consumption, and other factors.

| Diagnostic question | Next comparison | Decision metric |
| --- | --- | --- |
| Does information help groups with low natural repurchase? | D+14 information versus no contact; prespecified exploration by package size | 60-day incremental contribution profit and repurchase-rate difference |
| Are discounts reaching customers who would buy anyway? | Identical information plus coupon versus information alone | Incremental profit after coupon, shipping, and refund costs |
| Can targeting only low repurchase rates lose money? | Send-to-all, coupon-to-all, and customer-level policies | Validation incremental profit within budget; unsubscribe rate |

{transition}

{experiment_section}

{policy_section}

## {methods_number}. Interpretation and scope

- **Synthetic world:** data follow prespecified generation assumptions, not actual consumer research or real-company/brand performance records. Statistical significance concerns mean differences within this fixed synthetic world and does not validate real-brand performance. The 95% intervals describe sampling uncertainty in that world, not the probability of success in a real market. Policy evaluation uses a wholly fictional RCT and does not authorize immediate sending for a real brand.
- **Population:** each analysis split includes eligible customers who have not repurchased by D+14. Results are not generalized to all first-time buyers or customers without consent.
- **Feature timing:** both event time and recorded time must precede assignment. Arm labels are metadata and are excluded from prediction features.
- **Outcome definition:** an additional payment remains a repurchase event even if later refunded. Contribution profit separately accounts for refunds, shipping, payment, and sending costs.
- **Window boundaries:** payments are counted in `[assignment, assignment+60 days)`; final records must precede assignment+90 days. Unsettled outcomes are not replaced with 0.
- **Analysis separation:** hidden generator traits (oracle) were not used. Sections 1–8 use training customers only, excluding validation and final customers.

### Reproduction and method references

The HTML version combines Plotly charts in Quarto as a single file containing scripts and styles; chart display works without an external CDN. Original aggregates are in `report/data/diagnostics.json`, input/code hashes in `report/data/analysis_manifest.json`, and mart-building code in `src/crm_retention_lab/marts.py`.

Statistical methods refer to [lifelines KaplanMeierFitter](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html); output construction refers to [Plotly HTML export](https://plotly.com/python/interactive-html-export/) and [Quarto HTML documents](https://quarto.org/docs/output-formats/html-basics.html). Implemented survival probabilities and intervals are independently cross-checked against lifelines.
'''


def run_diagnosis(run_dir, output, report_dir, *, as_of=None, static_svg=False, include_experiment=False):
    """Validate immutable raw run, save separate marts, then aggregate/report."""
    source, target, report = (Path(value).resolve() for value in (run_dir, output, report_dir))
    for destination in (target, report):
        if destination == source or source in destination.parents or destination in source.parents:
            raise ValueError("Analysis outputs must be separate from the immutable source run")
    if target == report or target in report.parents or report in target.parents:
        raise ValueError("Individual marts and public report must use separate directories")
    if target.exists() and any(target.iterdir()):
        raise ValueError("Analysis output is not empty; choose a new run directory")
    public_files = ["index.qmd", "data/diagnostics.json", "data/analysis_manifest.json", "assets/plotly.min.js"]
    public_files += [f"assets/figures/{name}.{suffix}" for name in
                     ("eligibility_flow", "cohort_heatmap", "pack_km", "pack_repeat_60d")
                     for suffix in ("html", "json", "svg")]
    if include_experiment:
        public_files += ["data/experiment.json", "data/experiment_checks.json"]
        public_files += [f"assets/figures/{name}.{suffix}" for name in
                         ("arm_profit", "profit_effects", "coupon_info_waterfall", "safety_effects", "balance")
                         for suffix in ("html", "json", "svg")]
    for relative in public_files:
        destination = report / relative
        if report not in destination.resolve().parents:
            raise ValueError("A report output resolves outside the public report directory")
        if destination.exists() and destination.stat().st_nlink > 1:
            raise ValueError("Refusing to overwrite a report file with multiple hard links")
    config = verify_run_hashes(source)
    observed = load_observed(source / "observed")
    validation = validate_dataset(observed, config)
    if not validation["valid"]:
        raise ValueError("Input validation failed: " + "; ".join(validation["errors"][:5]))
    marts = build_marts(observed, config, as_of=as_of)
    diagnostics = summarize_diagnostics(marts, config)
    experiment, checks = None, None
    if include_experiment:
        from .experiment import summarize_experiment
        from .experiment_checks import summarize_experiment_checks
        experiment = summarize_experiment(marts, config)
        if experiment["status"] != "ready":
            raise ValueError("All training assignments must have settled outcomes before ITT arm comparison")
        checks = summarize_experiment_checks(observed, marts, config)
        if checks["finance_reconciliation"]["status"] != "passed":
            raise ValueError("Independent financial reconciliation failed; report not updated")
    # Lazy import keeps the generator and data contracts usable without extras.
    from .visuals import create_figures, export_figures
    from plotly.offline import get_plotlyjs

    target.mkdir(parents=True, exist_ok=True)
    for name in ("features", "outcomes"):
        with (target / f"{name}.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
            for row in marts[name]:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    _json(target / "metadata.json", marts["metadata"])
    (report / "data").mkdir(parents=True, exist_ok=True)
    figures = create_figures(diagnostics)
    if include_experiment:
        from .experiment_visuals import create_experiment_figures
        figures.update(create_experiment_figures(experiment, checks))
    exported = export_figures(figures, report / "assets" / "figures", static_svg=static_svg)
    for paths in exported["figures"].values():
        for key, path in paths.items():
            if path:
                paths[key] = Path(path).relative_to(report).as_posix()
    (report / "assets" / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    figure_html = {name: (report / paths["html"]).read_text(encoding="utf-8")
                   for name, paths in exported["figures"].items()}
    (report / "index.qmd").write_text(build_report_source(diagnostics, figure_html,
                                                          experiment=experiment, experiment_checks=checks), encoding="utf-8")
    _json(report / "data" / "diagnostics.json", diagnostics)
    if include_experiment:
        _json(report / "data" / "experiment.json", experiment)
        _json(report / "data" / "experiment_checks.json", checks)
    root = Path(__file__).resolve().parents[2]
    packages = {name: importlib.metadata.version(name) for name in ("plotly", "kaleido", "lifelines", "scipy")
                if importlib.util.find_spec(name) is not None}
    manifest = {
        "stage": 3 if include_experiment else 2, "data_origin": "fully_synthetic", "analysis_scope": "train",
        "as_of": marts["metadata"]["as_of"], "input_simulation_id": marts["metadata"]["input_simulation_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "packages": packages,
        "config_sha256": config_hash(config), "source_run_manifest_sha256": file_hash(source / "manifest.json"),
        "analysis_source_sha256": {path.relative_to(root).as_posix(): file_hash(path)
                                   for path in sorted((root / "src").rglob("*.py"))},
        "mart_sha256": {name: file_hash(target / name) for name in ("features.jsonl", "outcomes.jsonl", "metadata.json")},
        "diagnostics_sha256": file_hash(report / "data" / "diagnostics.json"),
        "report_source_sha256": file_hash(report / "index.qmd"),
        "observed_validation": {"valid": validation["valid"], "row_counts": validation["row_counts"]},
        "oracle_used": False, "final_test_used": False, "figures": exported,
    }
    if include_experiment:
        manifest["experiment_sha256"] = file_hash(report / "data/experiment.json")
        manifest["experiment_checks_sha256"] = file_hash(report / "data/experiment_checks.json")
        manifest["analysis_spec_sha256"] = file_hash(root / "docs/STAGE_3_ANALYSIS_SPEC.md")
    _json(report / "data" / "analysis_manifest.json", manifest)
    return {"summary": diagnostics["summary"], "experiment_status": experiment["status"] if experiment else None,
            "primary_comparisons": experiment["primary_comparisons"] if experiment else [], "analysis_output": str(target),
            "quarto_source": str(report / "index.qmd"), "static_svg": exported["static_svg"]}
