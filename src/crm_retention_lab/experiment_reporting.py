"""English decision narrative from aggregate, prespecified arm comparisons."""

ARM_NAMES = {"control": 'No contact', "info": 'Information', "coupon": 'Information + coupon'}
COMPARISON_NAMES = {"info_vs_control": 'Information − no contact', "coupon_vs_control": 'Information + coupon − no contact',
                    "coupon_vs_info": 'Information + coupon − information'}
METRIC_NAMES = {"unsubscribe_60d": 'Unsubscribe', "refund_customer_flag": 'Refund-customer rate'}


def _number(value, *, signed=False, digits=0):
    if value is None:
        return "NA"
    return format(0.0 if value == 0 else value, f"{'+,' if signed else ','}.{digits}f")


def _percent(value):
    return "NA" if value is None else f"{100 * value:.1f}%"


def _pp(value):
    return "NA" if value is None else f'{100 * value:+.2f} pp'


def _p(value):
    return "NA" if value is None else "<0.001" if value < 0.001 else f"{value:.4f}"


def _table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                     + ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def _effect_interpretation(row):
    if row["status"] != "ok":
        return 'Inference unavailable'
    if row["reject_after_holm"]:
        return 'Evidence of an increase' if row["estimate"] > 0 else 'Evidence of a decrease'
    return 'Direction remains uncertain'


def build_experiment_section(experiment, checks, figure_html=None):
    """Render five new charts and auditable numbers; no re-estimation here."""
    if experiment["status"] != "ready":
        return '## 5. Experiment results pending\n\nEffects are not computed until all assigned customers complete settlement.\n'
    if checks["finance_reconciliation"]["status"] != "passed":
        raise ValueError("Cannot narrate an experiment whose accounts do not reconcile")
    arms = {row["arm"]: row for row in experiment["arm_summaries"]}
    comparisons = {row["comparison"]: row for row in experiment["primary_comparisons"]}
    finance = checks["finance_reconciliation"]
    support = {row["arm"]: row for row in finance["supporting_accounting"]["arms"]}
    accounts = {row["arm"]: row for row in finance["arms"]}
    funnels = {row["arm"]: row for row in checks["delivery_funnel"]["arms"]}
    n = experiment["population"]["total_assigned"]
    randomization = checks["randomization"]
    defined_smd = [row["max_abs_smd"] for row in checks["balance"]["features"] if row["max_abs_smd"] is not None]
    max_smd = _number(max(defined_smd), digits=3) if defined_smd else "NA"
    srm_prefix = f"The sample-ratio mismatch (SRM) test p-value is **{randomization['p_value']:.4f}**"
    srm_description = (srm_prefix + '; the investigation threshold is 0.001. An assignment-ratio anomaly requires investigation; conclusions are withheld until its cause is checked.' if randomization["srm_flag"] else
                       srm_prefix + ', above the investigation threshold of 0.001; no departure from the prespecified assignment ratio was detected.')
    balance_prefix = f'The maximum absolute standardized mean difference (|SMD|) across the three pairwise comparisons of displayed baseline features is **{max_smd}**'
    balance_description = (balance_prefix + '. Some features exceed the 0.1 reference or have undefined values and require further investigation.' if
                           checks["balance"]["any_above_reference"] or checks["balance"]["has_undefined_smd"] else
                           balance_prefix + '; all displayed features are below the 0.1 reference.')
    arm_table = _table(['Assigned arm', 'ITT customers', 'Mean contribution profit', '95% interval for mean', 'Repurchase rate'], [
        [ARM_NAMES[arm], f"{row['n']:,}", f"{_number(row['primary']['mean'])} KRW",
         f"{_number(row['primary']['ci_lower'])}~{_number(row['primary']['ci_upper'])} KRW",
         _percent(row["secondary"]["repeat_paid_within_60d"]["rate"])] for arm, row in arms.items()])
    effect_table = _table(['Comparison', 'Incremental profit / assigned customer', 'Individual 95% interval', 'Holm-adjusted p', 'Interpretation within synthetic world'], [
        [COMPARISON_NAMES[name], f"{_number(row['estimate'], signed=True)} KRW",
         f"{_number(row['ci_lower'], signed=True)}~{_number(row['ci_upper'], signed=True)} KRW", _p(row["p_value_holm"]),
         _effect_interpretation(row)] for name, row in comparisons.items()])
    repeat_table = _table(['Comparison', 'Repurchase-rate difference', 'Individual 95% interval · exploratory'], [
        [COMPARISON_NAMES[row["comparison"]], _pp(row["estimate"]), f"{_pp(row['ci_lower'])}~{_pp(row['ci_upper'])}"]
        for row in experiment["secondary_comparisons"] if row["metric"] == "repeat_paid_within_60d"])
    funnel_table = _table(['Assigned arm', 'Assigned', 'Attempted', 'Reached', 'Opened', 'Redeemed'], [
        [ARM_NAMES[arm], *[f"{row['counts'][key]:,}" if row["applicable"][key] else 'Not applicable'
                          for key in ("assigned", "attempted", "reached", "opened", "redeemed")]]
        for arm, row in funnels.items()])
    accounting_table = _table(['Assigned arm', 'List-price merchandise', 'Other discounts', 'CRM coupon discounts', 'Revenue after discounts', 'Sending cost'], [
        [ARM_NAMES[arm], *[f"{_number(support[arm]['means_krw'][key])} KRW" for key in
                          ("list_subtotal_krw", "other_discount_krw", "crm_coupon_discount_krw")],
         f"{_number(accounts[arm]['components_mean_krw']['net_item_revenue'])} KRW",
         f"{_number(-accounts[arm]['components_mean_krw']['send_cost'])} KRW"] for arm in ARM_NAMES])
    safety_table = _table(['Versus no contact', 'Metric', 'Observed increase', 'Adjusted one-sided upper bound', 'Tolerance', 'Assessment'], [
        [ARM_NAMES[row["treatment_arm"]], METRIC_NAMES[row["metric"]], _pp(row["estimate"]), _pp(row["ci_upper"]),
         _pp(row["tolerance"]), 'Within tolerance' if row["assessment"] == "within_tolerance" else 'Not established']
        for row in experiment["guardrails"]])
    guardrail_arms = {arm: [row for row in experiment["guardrails"] if row["treatment_arm"] == arm]
                     for arm in ("info", "coupon")}
    decision_rows = []
    for arm in ("info", "coupon"):
        effect = comparisons[f"{arm}_vs_control"]
        failed_metrics = [METRIC_NAMES[row["metric"]] for row in guardrail_arms[arm] if row["assessment"] != "within_tolerance"]
        safety = 'Both side effects within tolerance' if not failed_metrics else "·".join(failed_metrics) + ': tolerance not established'
        action = ('Consider in the next policy comparison' if not failed_metrics and effect["reject_after_holm"] and effect["estimate"] > 0
                  else 'Modify operations and validate further')
        decision_rows.append([ARM_NAMES[arm], _effect_interpretation(effect), safety, action])
    decision_table = _table(['Option', 'Contribution profit vs no contact', 'Side-effect conditions', 'Planning decision'], decision_rows)
    coupon_info = comparisons["coupon_vs_info"]
    coupon_control = comparisons["coupon_vs_control"]
    coupon_funnel = funnels["coupon"]
    discount = support["coupon"]["means_krw"]["crm_coupon_discount_krw"]

    def chart(name):
        fragment = figure_html[name] if figure_html is not None else '{{< include assets/figures/' + name + '.html >}}'
        return '\n```{=html}\n<div class="figure-card">\n' + fragment + '\n</div>\n```\n'

    return f'''
## 5. Three-arm assignment and baseline features

All **{n:,} assigned training customers** completed the 60-day outcome window and 30-day settlement period. **ITT compares the full original assigned arms**, regardless of failed sends, unopened messages, or unused coupons. First-order profit is excluded.

Each arm was assigned with probability 1/3. {srm_description} Independent reconciliation of the source ledger and marts matched customer-level accounts for all {finance['n_customers_checked']:,} customers.

{chart('balance')}

{balance_description} This diagnoses balance in observed features; it does not prove that randomization is perfect. Missingness in pre-assignment visit records was checked separately.

### Message delivery and usage

{funnel_table}

Each cell counts customers. Unreached customers remain in the profit-comparison denominator. Opens and coupon redemption do not necessarily form a sequential funnel; effects are not calculated only among openers or redeemers.

## 6. Incremental contribution profit per customer

Each arm's 60-day contribution profit accounts for discounts, refunds, product costs, shipping, payment fees, and sending costs. Averages below are in **KRW per assigned customer**, distinct from total revenue or averages among purchasers only.

{chart('arm_profit')}

{arm_table}

### Incremental profit from information and coupons

{chart('profit_effects')}

{effect_table}

::: {{.method-note}}
Lines are Welch **individual 95% confidence intervals**, not simultaneous intervals for the three comparisons. Table p-values use Holm correction across the three prespecified contribution-profit comparisons.
:::

Incremental profit for information + coupon versus no contact is **{_number(coupon_control['estimate'], signed=True)} KRW/customer**, and the difference versus the same information alone is **{_number(coupon_info['estimate'], signed=True)} KRW/customer**. The added value of the coupon must be judged by directly comparing the information + coupon and information-only arms.

### Repurchase with the same ITT denominator

{repeat_table}

Rate-difference intervals use the Newcombe score method and are secondary analyses. A higher repurchase rate alone does not establish profitability; contribution profit above is the primary metric.

## 7. Added coupon value and cost reconciliation

The waterfall sums per-customer accounting differences for **information + coupon − information**. Positive components increase the profit difference and negative components reduce it. The final total matches the experiment estimate of {_number(coupon_info['estimate'], signed=True)} KRW/customer above.

{chart('coupon_info_waterfall')}

::: {{.method-note}}
Coupon discounts already enter the waterfall's merchandise revenue after discounts, so coupon cost is not deducted again. This is an accounting decomposition; components are not interpreted as independent causal mechanisms or mediation effects. The total profit-difference interval is reported above instead of component-level uncertainty.
:::

Among the coupon arm's {coupon_funnel['n_assigned']:,} customers, {coupon_funnel['counts']['redeemed']:,} redeemed a coupon; actual CRM coupon discounts average **{_number(discount)} KRW per assigned customer**. Redeemed discounts differ from the KRW 3,000 budget reserved at issuance.

{accounting_table}

All table amounts are per assigned customer, with discounts and sending costs shown as positive expenditures. **List-price merchandise amount − other discounts − CRM coupon discounts = merchandise revenue after discounts.** Displayed amounts are rounded to whole KRW; calculations use unrounded means.

## 8. Side effects and operating conditions

Alongside profit, we assess increases in unsubscribe and refund-customer rates versus no contact. Tolerances are **+0.5 pp and +1.0 pp**, respectively. Decisions compare the uncertainty-adjusted upper bound with tolerance, rather than relying on the point estimate alone.

{chart('safety_effects')}

{safety_table}

A one-sided family alpha of 0.05 is divided across **4 comparisons** (two active arms × two metrics), giving **98.75% one-sided upper bounds**. Chart lines run from the estimate to the upper bound and differ from two-sided 95% intervals. “Not established” means the upper bound is not within tolerance; it does not establish that deterioration necessarily exceeds tolerance.

### Planning decision at this stage

{decision_table}

::: {{.decision-box}}
The design caps contact at 30% of eligible customers and reserves up to KRW 3,000,000 in variable costs per 10,000 customers. **Profit, side effects, and operating constraints must be checked together.** These three-arm averages are not final customer-policy results, so an arm that sends everyone the same message is not approved as a final campaign satisfying those constraints.
:::

In the next policy stage, these results serve as baselines for selecting customers and benefits using pre-assignment features. Changes to content, frequency, or subscription preferences that could reduce contact burden are separate experimental hypotheses. Proposing real operational expansion requires independent evaluation of a locked policy and confirmation of side-effect conditions. Validation and final-evaluation data were not used in these arm comparisons.

### Experiment calculation and reproduction

Inputs are the same synthetic source as the diagnosis. Results are in `report/data/experiment.json`; assignment, balance, delivery, and accounting checks are in `report/data/experiment_checks.json`. The `compare-arms` command regenerates diagnostic and experiment charts together, and Quarto bundles them into one HTML file.

Mean inference refers to [SciPy Welch t-test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html); independent proportion-difference intervals refer to the [Newcombe implementation](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html). Independent pilot power simulation has not been performed. Sample size and seeds were not changed in response to these results.
'''
