"""English aggregate-only narrative for frozen policy selection and evaluation."""

from html import escape


ARM_NAMES = {"control": 'No contact', "info": 'Information', "coupon": 'Information + coupon'}
BASELINE_NAMES = {"control": 'Keep no contact', "random_info": 'Random information priority',
                  "random_coupon": 'Random coupon priority', "rule": 'Package/tips rule',
                  "risk_coupon": 'Non-repurchase risk priority'}
METRIC_NAMES = {"unsubscribe_60d": 'Unsubscribe', "refund_customer_flag": 'Refund-customer rate'}


def _text(value):
    return escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def _number(value, digits=0, signed=False):
    return "NA" if value is None else format(value, f"{'+,' if signed else ','}.{digits}f")


def _percent(value, digits=1):
    return "NA" if value is None else f"{100 * value:.{digits}f}%"


def _pp(value):
    return "NA" if value is None else f'{100 * value:+.2f} pp'


def _interval(item):
    return f"{_number(item['ci_lower'], signed=True)}~{_number(item['ci_upper'], signed=True)}"


def _table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def _policy_name(spec):
    if spec["kind"] != "uplift":
        return BASELINE_NAMES.get(spec["kind"], _text(spec.get("id", spec["kind"])))
    model = {"ridge": "Ridge", "hgb": "HGB"}.get(spec["model"], _text(spec["model"]))
    return f"{model} · λ={spec['penalty_lambda']:g}"


def _split_row(name, metadata):
    prefix = "train" if name == "train" else "split"
    readout = metadata["train_labels_available_by" if name == "train" else "split_readout_at"]
    labels = {"train": 'Training', "validation": 'Validation / selection', "final_test": 'Locked-policy final evaluation'}
    return [labels[name], f"{metadata[prefix + '_start_inclusive'][:10]} inclusive–{metadata[prefix + '_end_exclusive'][:10]} exclusive",
            f"{metadata['selected_assignments']:,}", readout[:10]]


def build_policy_section(analysis, figure_html=None):
    """Render sections 9–12 from public aggregates; never fit or select a policy.

    ``analysis`` must include the locked choice's evaluated final result. The
    function intentionally emits no customer IDs, fitted values or batch rows.
    """
    if analysis["metadata"].get("synthetic") is not True:
        raise ValueError("This narrative is restricted to the declared synthetic study")
    splits = analysis["metadata"]["splits"]
    chosen = analysis["selection"]["chosen_policy"]
    matching = [row for row in analysis["final"] if row["policy_id"] == chosen["id"]]
    if len(matching) != 1:
        raise ValueError("Exactly one final evaluation of the locked policy is required")
    selected = matching[0]
    if selected["policy_spec"] != chosen:
        raise ValueError("Final evaluated policy differs from the locked choice")
    if selected["n"] != splits["final_test"]["selected_assignments"]:
        raise ValueError("Final policy denominator differs from the full evaluation mart")
    if selected["bootstrap"]["repetitions"] < 2:
        raise ValueError("Validation screening cannot be presented as final bootstrap inference")
    selection = analysis["selection"]
    manifest = analysis["model_manifest"]
    constraints = analysis["constraints"]
    validation = [row for row in analysis["validation"] if row["policy_spec"]["kind"] == "uplift"]
    final = [selected] + [row for row in analysis["final"] if row["policy_id"] != chosen["id"]]
    selected_name = _policy_name(chosen)
    exposure, rollout = selected["exposure"], selected["rollout"]
    overlap = selected["overlap"]["policy"]
    confidence = selected["primary"]["confidence_level"]
    ci_label = _percent(confidence, 0)
    split_table = _table(['Purpose', 'Assignment dates', 'All assigned customers', 'Prespecified label cutoff'],
                         [_split_row(name, splits[name]) for name in ("train", "validation", "final_test")])
    validation_table = _table(['Candidate', 'DR incremental profit / customer', 'Validation approximate 95% interval', 'Profit / side effects', 'Selection'], [
        [_policy_name(row["policy_spec"]), f"{_number(row['primary']['estimate'], signed=True)} KRW", _interval(row["primary"]),
         ('Pass' if row["screen"]["profit_pass"] else 'Fail') + " / " + ('Pass' if row["screen"]["harm_pass"] else 'Fail'),
         'Locked' if row["policy_id"] == chosen["id"] else "—"] for row in validation])
    final_table = _table(['Policy', 'DR incremental profit / customer', f'{ci_label} interval · KRW', 'IPW check / customer'], [
        [('**Locked policy: ' + _policy_name(row["policy_spec"]) + "**") if row["policy_id"] == chosen["id"] else _policy_name(row["policy_spec"]),
         f"{_number(row['primary']['estimate'], signed=True)} KRW", _interval(row["primary"]),
         f"{_number(row['ipw_check']['estimate'], signed=True)} KRW"] for row in final])
    allocations = _table(['Final population', 'No contact', 'Information', 'Information + coupon'], [[
        f"{selected['n']:,}", *[f"{exposure['counts'][arm]:,}" for arm in ARM_NAMES]]])
    segment_table = _table(['First package', 'Customers', 'No contact', 'Information', 'Information + coupon'], [
        [f"{_number(row['first_pack_grams'])}g", f"{row['n']:,}", *[f'{row[arm]:,}' for arm in ARM_NAMES]]
        for row in selected.get("segments", [])])
    safety_table = _table(['Locked policy − no contact', 'IPW increase', 'One-sided upper bound', 'Tolerance', 'Assessment'], [
        [METRIC_NAMES[row["metric"]], _pp(row["estimate"]), _pp(row["ci_upper"]), _pp(row["tolerance"]),
         'Within tolerance' if row["assessment"] == "within_tolerance" else 'Not established']
        for row in selected["guardrails"]])
    feasible_n, one_se_n = len(selection["feasible_ids"]), len(selection["one_se_ids"])
    if chosen["kind"] == "control":
        selection_text = 'Validation selected **keep no contact**. The prespecified no-contact fallback was locked rather than arbitrarily proceeding with an active campaign.'
        decision_text = '**Keep no contact.** This policy is identical to the reference, so incremental profit and side-effect differences are 0. It does not demonstrate the effectiveness of an active campaign.'
    else:
        selection_text = f'Validation yielded {feasible_n} feasible candidates, including {one_se_n} within 1 standard error. **{selected_name}** was selected and locked.'
        decision_text = {
            "candidate": '**A rollout candidate within this synthetic environment.** The lower interval bound after setup cost exceeds 0, and both side-effect upper bounds and resource constraints are met.',
            "hold": '**Hold the current policy.** Resource constraints are not met, or the incremental-profit upper bound after setup cost is below 0. Review the detailed values and violations together.',
            "modify_or_collect_more_evidence": '**Modify operating conditions or collect more evidence.** Evidence is not yet sufficient to jointly establish the profit lower-bound, both side-effect, and resource criteria.',
        }.get(rollout["decision"], '**Final decision remains unresolved.** Evaluation status and prespecified decision conditions require review.')
    guard_confidences = sorted({row["one_sided_confidence"] for row in selected["guardrails"]})
    guard_confidence_text = ", ".join(_percent(value, 2) for value in guard_confidences)
    screening_confidences = sorted({row["one_sided_confidence"] for result in validation for row in result["guardrails"]})
    screen_confidence_text = ", ".join(_percent(value, 4) for value in screening_confidences) or 'Prespecified'
    caps_text = 'All assignment-day constraints met' if rollout["caps_ok"] else 'Constraint violations present'
    model_spec = manifest["model_spec"]
    chosen_validation = [row for row in validation if row["policy_id"] == chosen["id"]]
    validation_to_final = ""
    if chosen_validation:
        change = ('decreased' if selected["primary"]["estimate"] < chosen_validation[0]["primary"]["estimate"] else 'changed')
        validation_to_final = (
            f"For the same locked policy, DR incremental profit moved from {_number(chosen_validation[0]['primary']['estimate'], digits=2, signed=True)} KRW/customer on validation to {_number(selected['primary']['estimate'], digits=2, signed=True)} KRW/customer on final data; the estimate {change}. Sampling variation, validation selection optimism, and customer-composition differences are possible explanations, but this comparison cannot separate or establish the cause."
        )

    def chart(name):
        fragment = figure_html[name] if figure_html is not None else '{{< include assets/figures/' + name + '.html >}}'
        return '\n```{=html}\n<div class="figure-card policy-figure">\n' + fragment + '\n</div>\n```\n'

    return f'''
## 9. Customer-level models and policy lock

Building on the three-arm average comparisons, 11 pre-assignment features predict **conditional contribution profit and side-effect probabilities** for no contact, information, and information plus coupon. Only the assigned treatment's outcome is observed for each customer. Model differences therefore estimate **conditional average effects**, not observed individual true effects.

{split_table}

Each split retains the full originally randomized population with completed 90-day settlement. Preprocessing and models are fitted on training data only; validation selects candidates, and the final split evaluates the locked policy only. Models, λ, and policies are not reselected after seeing final results.

### Two models and eight policy candidates

The training set contains **{manifest['n_train']:,} customers**. Candidates are Ridge(α={model_spec['ridge']['alpha']:g}) and histogram gradient boosting (HGB). A T-learner fits separate contribution-profit models for each arm; unsubscribe and refund outcomes are modeled as classification probabilities. Negative and 0 profit values are retained. Numeric imputation, scaling, and categorical encoding are fitted on training data only. Months/channels first appearing later are handled as unseen categories.

Applying reservation-cost penalties λ=0, 0.5, 1, 2 to each model gives {len(validation)} candidates for validation. Sending candidates are ranked by **predicted incremental profit − λ×reserved cost**. The λ penalty allocates scarce resources; it is not deducted as an accounting cost from evaluated contribution profit. All policies share prespecified HGB outcome predictions for DR evaluation, separating policy ranking models from the evaluation nuisance model.

On narrow screens, scroll charts horizontally.

{chart('policy_validation')}

{validation_table}

The profit criterion requires the lower bound of the validation DR approximate 95% interval to exceed fixed setup cost per customer. Side-effect screening covers {len(validation)} candidates × 2 metrics and uses Bonferroni-corrected **{screen_confidence_text} one-sided upper bounds**. Validation intervals are normal approximations for fixed action scores; they are not final inference accounting for all allocation dependence and selection optimism.

Among feasible candidates, prefer the simpler Ridge model if it lies within 1 standard error of the highest DR estimate. Within a model, rank by decreasing DR, increasing λ, then fixed identifier. Select no contact if no candidate is feasible. {selection_text}

## 10. Independent incremental profit of the locked policy

The final denominator is **all {selected['n']:,} assigned customers**; the analysis does not retain only customers whose assigned arm matches the policy action. Actual randomization probabilities compare policy value with the value of no contact for everyone. DR combines outcome predictions with assignment probabilities as the primary analysis; IPW provides a probability-weighted check.

{chart('policy_profit')}

{final_table}

The locked policy's primary estimate is **{_number(selected['primary']['estimate'], signed=True)} KRW/eligible customer**, with a {ci_label} interval of **{_interval(selected['primary'])} KRW**. The IPW check is {_number(selected['ipw_check']['estimate'], signed=True)} KRW, with an interval of {_interval(selected['ipw_check'])} KRW. Other rows are prespecified **exploratory baselines**. They are not used to choose a new final winner, nor to claim simultaneous superiority over multiple baselines.

{validation_to_final}

Customers are resampled with replacement within assignment days for **{selected['bootstrap']['repetitions']:,} bootstrap repetitions**. Repeated customers occupy separate slots; allocation and constraints are recalculated for the same policy in each repetition, without model refitting or policy reselection. The intervals therefore condition on the locked models/policy and observed daily composition, excluding full training uncertainty and uncertainty about generalization to real markets.

### Scaling to rollout size and accounting for costs

For **{rollout['eligible_customers']:,} eligible customers**, scaled incremental profit after setup cost is **{_number(rollout['incremental_profit_krw'], signed=True)} KRW**, with an interval of **{_interval(rollout)} KRW**. The calculation is `DR incremental profit per customer × rollout population − fixed setup cost`; setup cost here is {_number(rollout['setup_cost_krw'])} KRW. Setup cost is charged only when at least one customer is contacted; the bootstrap reapplies this condition.

Discounts, refunds, product costs, shipping, payment, and sending costs already enter customer-level contribution profit. Reservation budgets and λ penalties are not deducted again. Scaling is a planning calculation conditional on unchanged customer composition and operating conditions, not a forecast of actual sales.

## 11. Constrained allocation and selection rationale

The contact cap is **{_percent(constraints['max_contact_fraction'], 0)}** of eligible customers; the variable-cost reservation budget is **{_number(constraints['budget_reservation_cap_krw_per_10000'])} KRW per 10,000 customers**. Each assignment day's caps are proportional to its eligible population and rounded down to integers. Coupons reserve **full face value plus sending cost**, without discounting by expected redemption. Fixed setup cost of {_number(constraints['fixed_setup_cost_krw_per_rollout'])} KRW is accounted for separately, outside the variable-cost reservation cap.

{chart('policy_allocation')}

{allocations}

The evaluation population receives {exposure['contact_n']:,} contacts ({_percent(exposure['contact_fraction'])}), against a total contact cap of {exposure['contact_cap_total']:,}. Reserved cost is **{_number(exposure['reservation_total_krw'])} KRW**, against summed daily caps of {_number(exposure['budget_cap_total_krw'])} KRW. The original allocation has {exposure['violating_batches']:,} violating days and the bootstrap has {selected['bootstrap']['cap_violating_resamples']:,} violating repetitions: **{caps_text}**.

Actions with positive predicted incremental profit are allocated by score, with at most one action per customer. Only positive predicted increases in unsubscribe/refund risk are accumulated, so one customer's predicted risk reduction cannot offset another's predicted increase. This allocation filter does not replace the observed-outcome side-effect evaluation in the next section. The greedy implementation respects constraints but **does not guarantee a global optimum**.

{chart('policy_segments')}

{segment_table}

The first-package table explains whom the locked policy selects. It does not establish true individual or segment-level causal effects. The non-repurchase risk baseline ranks the chance of not repurchasing, not the incremental response to a message. Random, rule, and risk baselines use the same contact, reservation-budget, predicted-risk filters, and positive incremental-profit requirement.

## 12. Side-effect upper bounds and final decision

The locked policy's unsubscribe and refund-customer rates are compared with no contact for everyone. Differences below are IPW estimates from observed labels, distinct from model-predicted risk scores.

{chart('policy_guardrails')}

{safety_table}

A one-sided family α=0.05 across two metrics yields **{guard_confidence_text} one-sided upper bounds**. Their scope differs from the 4 comparisons in the arm-average analysis and from validation candidate screening. Intervals for multiple exploratory baselines do not provide simultaneous safety guarantees.

The number of IPW customers whose assigned arm matches the policy action is {overlap['matched_n']:,}, with an effective sample size of {_number(overlap['effective_sample_size'], digits=1)}. Matched counts and effective sample size diagnose weighted information; the analysis denominator remains {selected['n']:,} customers. Dependence on matched counts and the DR/IPW difference are assessed together.

::: {{.decision-box}}
{decision_text}
:::

The policy is not reoptimized on the same final split after observing its result. Revisions require a new experiment with separate customers and periods.

### Methods, records, and remaining validation

Public aggregates are in `report/data/policy.json`; prespecified rules are in `docs/STAGE_4_POLICY_SPEC.md`. The actual UTC execution time of policy locking differs from the synthetic business dates in the tables. File creation order is also checked to confirm that the lock precedes final-source generation. Independent pilot power simulations and repeated inference/false-expansion checks in A/A null-effect worlds remain incomplete.

Models refer to [scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) and [HistGradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html); DR policy evaluation refers to [Dudík·Langford·Li, Doubly Robust Policy Evaluation and Learning](https://arxiv.org/abs/1103.4601).
'''
