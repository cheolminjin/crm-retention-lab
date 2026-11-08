# Analysis and experiment plan

Status as of 2026-11-08: generation, ledger validation, training marts, KM, **three-arm average ITT comparisons**, and the **Ridge/HGB T-learner, constrained allocation, policy lock, and independent DR/IPW evaluation pipeline** are implemented. The original plan below is retained; comparisons and success criteria are not revised to fit results. See the [stage-3 specification](STAGE_3_ANALYSIS_SPEC.md), [stage-3 results](STAGE_3_RESULTS.md), and [stage-4 prespecified method](STAGE_4_POLICY_SPEC.md) for implementation details fixed before final evaluation. Independent pilot power and repeated A/A inference checks remain unfinished. The [integrated report](../reports/CRM_DIAGNOSTIC.html) and `report/data/policy.json` distinguish completed results from planned work.

## 1. Time, population, and estimands

```text
First delivery             Assignment                   Outcome end       Settlement end
t0                         tA = t0+14 days               tA+60 days        tA+90 days
|-- eligibility/features --|-- purchases/unsubscribes ---|-- settlement ---|
                           No contact / Information / Information + coupon
```

The primary population is **customers eligible for the D+14 experiment**. Do not generalize its effect to early repurchasers, customers without marketing consent, or all first-time buyers.

`Y_i(a)` is customer `i`'s 60-day post-assignment contribution profit under action `a`. Only the assigned action's outcome is observed. ITT compares original assignments regardless of delivery, opens, or coupon redemption.

The three prespecified contrasts are `info-control`, `coupon-control`, and `coupon-info`. The last measures the value of adding a coupon to identical information. Significance in the coupon arm alone does not establish a difference from information.

## 2. Outcomes and costs

```text
Order contribution profit
  = discounted item revenue + customer shipping charge − refunds
    − cost of goods + recovered inventory value
    − outbound shipping − fulfillment − payment fees − return handling

Y_i = settled contribution profit of orders paid within the outcome window
      − CRM send cost
```

- Exclude the first order because it predates assignment.
- Coupon discounts already reduce item revenue; never subtract them again.
- Include discounts on purchases that would have happened anyway.
- Customers without purchases can have negative outcomes because of send costs.
- Do not subtract send costs or discounts again when evaluating policy effects.
- VAT treatment, fixed labor costs, and taxes are outside scope. Amounts use a consistent simulated management-accounting basis and are not net income.

Secondary outcomes are 60-day additional-payment rate, order count, revenue per order, refunded-customer rate, refund amount, and unsubscribe rate. Revenue per order can reflect changing buyer composition and is not a standalone causal performance measure.

The hypothetical side-effect tolerances are increases versus control of at most **0.5 pp for unsubscribe** and **1.0 pp for refunded-customer rate**. Denominators include all assigned customers, not only buyers. Unsubscribes can also occur through account settings available equally across arms.

## 3. Repurchase diagnosis

Use training-period data to:

1. Trace all first buyers through D+14 maturity, no prior repurchase, consent/order eligibility, and assignment.
2. Compare eligibility and early behavior by first package, initial discount, and acquisition channel.
3. Estimate Kaplan–Meier time-to-next-repurchase curves, primarily for eligible controls.
4. Add a discrete-time hazard model using time since assignment, first package, and early behavior to explain conditional timing.

`S(t)` is the share **not yet repurchased**; `1-S(t)` is cumulative repurchase. Label axes accordingly, show risk sets and intervals, and do not extrapolate a median when fewer than 50% have repurchased.

The control curve conditions on no repurchase through D+14 and contact eligibility. Any supplementary all-first-buyer curve must disclose its mixture of assigned treatments. Censor non-repurchasers at `min(assignment+60 days, observation cutoff)`. Payments are real-time operational records under the [data design](DATA_DESIGN.md), unlike delayed analytics logs. Unsubscribing does not stop purchase observation.

These curves diagnose natural timing and customer differences. A high repurchase hazard does not identify the day with the largest causal message effect.

## 4. Average randomized effects

Before estimation, check duplicate assignments, eligibility violations, arm probabilities, SRM, pretreatment balance, and standardized differences. Present assignment → send attempt → delivery → open → redemption as a diagnostic funnel, without restricting ITT to responders. Reconcile transactions, coupons, ledger entries, and send costs at aggregate and order levels. Investigate generation/assignment errors instead of deleting unfavorable observations to improve balance.

Estimate arm means and customer-level mean differences. Raw total-revenue differences are unsuitable when group sizes differ. Apply Holm adjustment to the three prespecified p-values. Report unadjusted **individual 95% intervals** without implying simultaneous coverage equivalent to the adjusted p-values. Emphasize KRW/customer and percentage-point differences rather than unstable relative lifts near a zero baseline.

The initial 60,000-customer scale is not a power calculation. After eligibility and period counts are known, use a pilot world independent of final evaluation to simulate power with profit variance, minimum detectable effects, and multiplicity. Do not add observations because final results are disappointing; retain uncertainty when resources are insufficient.

## 5. Customer-level action selection

| Policy | Purpose |
| --- | --- |
| No contact for everyone | No-intervention reference |
| Random information / random coupons | Value of targeting under shared constraints |
| First-package / early-behavior rule | Explainable marketing baseline |
| Coupons prioritized by non-repurchase risk | Contrast risk prediction with effect prediction |
| Profit-uplift allocation | Choose information, coupon, or no contact by predicted incremental contribution profit |

All-information/all-coupon averages may be unconstrained references. Policies exceeding budget/contact caps cannot be treated as feasible winners on equal operating terms.

The primary model is a **three-arm T-learner**, estimating `E[Y|X,A=a]` and `mu_a(X)-mu_control(X)`. Compare limited candidates of regularized regression and histogram gradient boosting that accommodate zero and negative profit. Implemented candidates are Ridge α=100 and fixed HGB; Logistic/HGB classifiers predict unsubscribe and refund probabilities. Fixed parameters and four λ values are in the [policy configuration](../configs/policy_analysis_v0_1.json). A control-trained repurchase model supplies the risk baseline. Prefer the simpler model when validation supports it. Predicted individual effects are not verified individual causal effects; interpret group averages and policy value.

Use only pre-assignment snapshots. Fit preprocessing on training data and transform validation/test data without refitting. Exclude IDs, treatment arm, post-assignment clicks/purchases, and generator-internal variables from features.

Reserve KRW 0/20/3,020 for no contact/information/coupon. Reserve full coupon face value at issuance regardless of redemption. **Reservation differs from spending**; realized profit includes only redeemed discounts.

All feasible policies share:

- A KRW 3,000,000 variable-cost reservation cap per 10,000 eligible customers.
- A 30% contact cap.
- Positive predicted incremental profit for candidate actions.
- Daily predicted-risk screening that sums only positive unsubscribe/refund increases. This does not replace observed IPW side-effect evaluation.

These are shared **caps**, not equal realized spending. Do not force unused budget to be spent. First delivery and D+14 assignment use daily 09:00 slots; allocate only among customers whose eligibility is known in that slot. Scale caps by batch size and round fractional contact limits down to integers. Future arrivals' features are unavailable.

Rank actions by `predicted_incremental_profit − lambda × reserved_cost`, selecting at most one action per customer within the caps. Select `lambda` on validation and fix ties deterministically. This is a greedy rule, not a globally optimal policy. The assumed KRW 100,000 fixed operating cost is separate from the **variable reservation cap**, occurs once for a 10,000-customer active campaign, and is zero for no contact.

## 6. Time splits and freezing

| Purpose | Assignment dates; end exclusive | Outcome/settlement availability | Use |
| --- | --- | --- | --- |
| Train | 2025-01-15 ~ 2025-07-01 | 2025-10-01 | Diagnosis and fitting |
| Validation | 2025-10-01 ~ 2025-12-01 | 2026-03-01 | Candidate/rule/budget-score selection |
| Final test | 2026-03-01 ~ 2026-05-01 | 2026-08-01 | Locked-policy evaluation |
| Monitoring | 2026-05-01 ~ 2026-08-01 | Customer-specific | Provisional recent-cohort diagnosis only |

Intervening assignment periods are embargoes for outcome maturity and do not support model selection or final claims. Customers never cross splits. Labels use only records available at the corresponding analysis time.

V1 locks the training-fitted model and policy chosen on validation. Refitting on all available data would change the evaluated procedure and is not added automatically. Save model, features, selection rules, and configuration hashes before opening final outcomes. Separate stage inputs/outputs in actual execution as well as simulated time.

`select-policy` reads only training/validation and refuses selection if the final source path exists. `evaluate-policy` checks locked model, configuration, decision-code, and selection hashes before generating or reading final sources. Simulation IDs distinguish repeated local customer numbers. Actual UTC file-generation times differ from synthetic business dates.

## 7. Final policy evaluation

Do not replace observed test outcomes with predictions for recommended actions. Use actual outcomes and known randomization probabilities `e_a=1/3`.

```text
IPW policy value
V(pi) = mean[ I(A_i = pi_i) * Y_i / e_(A_i) ]

DR policy value
V_DR(pi) = mean[ mu_(pi_i)(X_i)
                  + I(A_i = pi_i) / e_(A_i)
                    * (Y_i - mu_(A_i)(X_i)) ]

Primary effect = V_DR(selected policy) - V_DR(no contact for everyone)
```

`pi_i` is the action selected by fixed scores and batch-budget rules; `mu` is fitted outside test data. Prespecify DR as primary and IPW as diagnostic rather than choosing whichever looks favorable. The implementation uses the same training HGB adjustment model for every candidate, including Ridge allocation policies. Validation screens eight candidates with conditional normal approximations; final evaluation applies identical date-stratified resamples to locked and baseline policies. Final baseline results do not trigger reselection.

Do not average only matching assigned/recommended actions. Also report match rates, matches by arm, weights, and standard errors. Use 2,000 customer bootstrap replicates, comparing policies on the same resamples. Resample within daily batches and recalculate limits/allocation using fixed rules. Do not refit models or lambda. Intervals cover **evaluation-sample uncertainty for an already selected policy**, not uncertainty from the entire fitting procedure.

The final confirmatory primary contrast is the single locked **selected policy versus no contact** comparison. Other baseline comparisons are exploratory, unlike the three prespecified average-treatment contrasts.

## 8. Scale, modify, or hold

For a simulated 10,000-customer rollout with the same composition:

```text
Planned incremental profit = 10,000 × per-customer incremental contribution profit
                             − fixed operating cost
```

Fixed cost is KRW 100,000 for active policies and KRW 0 when nobody is contacted. Never subtract costs already included in customer outcomes again. This is a simulated planning calculation, not a real revenue forecast.

- **Scale-up candidate:** planned-profit 95% lower bound > 0, budget/contact compliance, and both side-effect upper bounds within tolerance.
- **Modify / collect more evidence:** profit interval includes 0 or side effects lack sufficient precision.
- **Hold:** profit upper bound < 0 or evidence that a side effect exceeds tolerance.

Use Bonferroni-adjusted 97.5% one-sided bounds for the two side effects. Repeated null-world checks of false scale-up decisions are a separate task. For `unsubscribe_60d` and `refund_customer_flag`, prespecify **selected-policy minus no-contact IPW policy-value differences**, with upper bounds from the same batch bootstrap. Raw coupon-arm rates or selected-customer averages cannot substitute for policy-level effects. Synthetic intervals describe sampling uncertainty within the assumed world, not structural uncertainty in real markets.

## 9. Follow-up timing experiment

At D+7, randomize a common eligible population to no contact, D+7, D+14, or D+21 sending schedules. Hold content/benefits fixed and use the same 90-day outcome window starting at D+7. Prespecify suppression when customers repurchase or withdraw consent before their scheduled send; retain suppressed customers in original ITT denominators. Do not compare only customers who remain unrepurchased at each later date. This follow-up is needed to compare send timing causally.
