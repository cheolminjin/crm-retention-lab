# Stage 3: arm-average experiment specification

Written: 2026-11-08, before computing these three-arm results. This specifies estimators from the [existing analysis plan](ANALYSIS_PLAN.md). The earlier no-contact repurchase diagnosis had already been inspected. This is not an externally preregistered confirmatory trial. Generation assumptions, source data, population scope, and the three comparisons remain unchanged.

## Population and outcomes

Use every assigned training customer in `train-diagnostic-v0.1`, after the complete 60-day outcome and 30-day settlement windows. If any customer is unsettled, withhold results rather than estimate an ITT effect only among mature customers. Failed sends, unopened messages, and unused coupons remain in the original arms.

The primary outcome is the mean difference in `contribution_profit_60d_krw` per assigned customer. It excludes the first order and includes revenue after discounts, refunds, product cost/recovery, outbound/return handling, payment, and sending costs. Coupon discounts already enter revenue and are not deducted twice.

## Fixed comparisons and methods

| Item | Implementation |
|---|---|
| Primary contrasts | Information − no contact; information + coupon − no contact; information + coupon − information |
| Mean difference | Arithmetic difference of customer means; Welch standard error, degrees of freedom, and t interval |
| Primary intervals | Individual two-sided 95% intervals; not simultaneous multiple-comparison intervals |
| Primary tests | Two-sided Welch p-values; Holm correction only for the 3 prespecified profit comparisons |
| Repurchase, unsubscribe, refund-customer rates | Arm-level Wilson intervals; individual 95% Newcombe score intervals for independent proportion differences |
| Order counts | Welch mean differences; secondary analysis |
| Secondary metrics | Exploratory estimates/intervals without the primary family's multiplicity claim |
| SRM | Pearson chi-square against assignment probability 1/3; investigate p<0.001 |
| Baseline balance | SMD for numeric values and categorical indicators; absolute 0.1 is a reference |
| Side-effect comparisons | 2 active arms × unsubscribe/refund: 4 differences versus no contact |
| Side-effect bounds | One-sided family alpha 0.05 / 4 → 98.75% one-sided Newcombe score upper bounds |

Tolerances are +0.5 percentage points for unsubscribe and +1.0 for refund-customer rate. Mark **Within tolerance** only when the adjusted upper bound is within tolerance. Otherwise mark **Not established**, which does not establish deterioration. This four-comparison family differs from the 97.5% one-sided bounds planned for the two side effects of one final locked policy.

Undefined inference for small samples, empty arms, or zero variance is reported as unavailable, not significant. There is no outlier removal, purchaser-only/send-success-only restriction, or result-dependent seed/sample-size change.

## Accounting and interpretation

Independently reconcile each customer's source ledger and sending cost against mart profit; require total discrepancy 0. Arm totals check accounting; effect estimates compare totals divided by each arm's assigned count.

The waterfall sums **per-assigned-customer component mean differences** for coupon versus information. Components are not independent causal mediators. Delivery/open/redemption tables diagnose operations without reducing the ITT denominator. Redemption is not assumed to be a subset of recorded opens.

This is a training-population average experiment within a fixed synthetic world, not final evaluation of a later customer policy or approval for real-market expansion. Validation/final customers remain unopened. Independent pilot power simulation remains separate future work. Observed effects are not used to calculate post-hoc power or choose additional sample size.

## Method references

- [SciPy Welch t-test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html): independent means without equal-variance assumptions.
- [SciPy Pearson chisquare](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chisquare.html): assignment counts against known category probabilities.
- [statsmodels independent proportion intervals](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html): Newcombe implementation and references. The project implements and checks the formulas without adding that package.
