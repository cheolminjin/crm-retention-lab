# Customer-level CRM policy results

Written 2026-11-08. These are self-generated synthetic data, not company results. See the [prespecified method](STAGE_4_POLICY_SPEC.md), [public aggregates](../report/data/policy.json), and [interactive report, sections 9–12](../reports/CRM_DIAGNOSTIC.html).

## Decision: modify operating conditions or collect more evidence

The **HGB T-learner with reservation-cost penalty λ=0.5**, locked on validation data, estimated **KRW +281.94 per eligible customer** on independent final customers. Its 95% interval was **KRW −153.63 to +640.13**. Budget, contact, and both side-effect criteria passed, but the profit lower bound did not exceed zero. The policy therefore failed to meet every scale-up condition. Neither the model nor policy was reselected on final data.

For 10,000 customers, after KRW 100,000 fixed setup cost, planned incremental profit was **KRW +2,719,396**, with a 95% interval of **KRW −1,636,266 to +6,301,281**. This planning calculation assumes the same customer mix and operating conditions; it is not an actual revenue forecast.

## Customers and models

| Purpose | First-delivery customers | Eligible, assigned, and settled through 90 days | Seed |
| --- | --- | --- | --- |
| Training | 20,000 | 15,284 | 20261108 |
| Validation | 20,000 | 15,167 | 20261109 |
| Independent final evaluation | 20,000 | 15,363 | 20261110 |

Customers were generated with independent seeds and identified by `simulation_id:local_id`; repeated local numbers were not linked across runs. Assignment windows were 2025-01-15–07-01 for training, 2025-10-01–12-01 for validation, and 2026-03-01–05-01 for final evaluation, all end exclusive. Preprocessing and fitting used training customers only. Final source generation occurred after the policy lock in the actual execution order.

Ridge and HGB profit models and unsubscribe/refund classifiers were fitted separately by arm. Eight candidates combined two models with λ=0/0.5/1/2. All candidates enforced positive predicted profit, reserved budget, contact, and predicted-risk limits. Prediction differences are not observed individual treatment effects.

## Why validation locked HGB λ=0.5

All four Ridge candidates failed validation side-effect upper-bound screening. All four HGB candidates passed; λ=0.5 had the highest DR estimate, KRW +1,010.73. No eligible Ridge candidate lay within one standard error of the best estimate, so HGB λ=0.5 was selected. Validation screening intervals approximate uncertainty for fixed action scores and differ from final confirmatory intervals.

The same policy's final estimate fell to KRW +281.94. The difference alone does not identify a cause. Sampling variation, optimism from selecting a strong validation candidate, and customer-mix changes across periods warrant investigation. Seeds, sample sizes, λ, and risk thresholds were not changed to suit this result.

## Customer allocation and resources

| Action | Final customers | Share |
| --- | --- | --- |
| No contact | 11,045 | 71.89% |
| Information | 2,834 | 18.45% |
| Information + coupon | 1,484 | 9.66% |

The policy contacted 4,318 customers, **28.11%** of the cohort. Same-day 09:00 assignments were batched with a daily `floor(0.30×n)` contact cap. All 61 final batches met contact, budget, and predicted-risk limits. Allocation was recalculated in each of 2,000 bootstrap replicates; every policy had zero constraint violations.

Reserved variable cost was **KRW 4,538,360 against a KRW 4,608,900 cap**. This is approximately KRW 2,954,084 per 10,000 eligible customers, below the KRW 3,000,000 cap. Information reserves KRW 20; coupons reserve KRW 3,020, including full face value and send cost. Reservation differs from actual redemption spending and is not subtracted again from contribution profit. Fixed setup cost is separate from the variable-cost cap.

| First package | All customers | No contact | Information | Information + coupon |
| --- | --- | --- | --- | --- |
| 200g | 4,496 | 3,332 | 775 | 389 |
| 500g | 5,641 | 3,763 | 984 | 894 |
| 1kg | 5,226 | 3,950 | 1,075 | 201 |

This table describes allocation, not causal evidence that 500g customers respond more strongly to coupons. Actions depend on 11 pretreatment features, predicted incremental profit, and within-batch ranks and constraints. The greedy allocation has no global-optimality guarantee.

## Final policy comparison

All differences are **KRW per eligible customer versus no contact for everyone**. Primary DR estimates use known randomization probabilities of 1/3 and a common training-fitted HGB outcome model. IPW is a diagnostic estimate. Evaluation does not average only customers whose assigned and recommended actions match.

| Policy | DR incremental profit | 95% bootstrap interval | IPW diagnostic |
| --- | --- | --- | --- |
| **Locked HGB λ=0.5** | **+281.94** | **−153.63 to +640.13** | **+290.12** |
| No contact for everyone | 0.00 | 0.00 to 0.00 | 0.00 |
| Random information among eligible candidates | +221.73 | −173.10 to +595.73 | +163.39 |
| Random coupons among eligible candidates | +127.49 | −78.02 to +363.25 | −174.36 |
| Package/tips rule | +238.49 | −66.23 to +530.57 | −47.25 |
| Non-repurchase-risk-first coupons | +242.58 | +66.24 to +457.37 | +332.35 |

Baselines share hard limits and HGB-based positive-profit/predicted-risk screening. “Random” means a fixed hash priority among candidates passing those conditions. Baseline intervals are exploratory, not simultaneous evidence of superiority. The positive risk-first coupon interval does not justify switching policies after final evaluation. DR/IPW differences for some baselines also warrant uncertainty checks.

## Side effects and decision

| Outcome | IPW increase | 97.5% one-sided upper bound | Tolerance | Status |
| --- | --- | --- | --- | --- |
| Unsubscribe | +0.156 pp | +0.371 pp | +0.500 pp | Within tolerance |
| Refunded-customer rate | +0.332 pp | +0.742 pp | +1.000 pp | Within tolerance |

Family one-sided α=0.05 was split across the locked policy's two side effects. Model-predicted screening risk was kept separate from IPW bounds based on observed labels. Both side-effect criteria passed, but profit uncertainty leaves the final decision at **modify or collect more evidence**.

## Proposed next experiment

1. Record profit uncertainty and the validation-to-final decline as decision evidence; do not present this as a successful rollout.
2. Design an experiment on separate customers and dates comparing the locked policy with the simpler risk-first coupon baseline. Do not reuse this final cohort for selection.
3. Before that experiment, determine power and the minimum detectable effect from an independent pilot and check false scale-up rates in repeated null worlds. These tasks are not complete.

The 2,000 bootstrap replicates sample customers with replacement within dates, keeping date-specific sample sizes fixed and reallocating each time. Intervals condition on the fitted models, selected policy, date composition, and synthetic world. They exclude full fitting/selection uncertainty and real-market changes. This portfolio demonstrates planning, analysis, and a cautious execution decision in a simulated setting.
