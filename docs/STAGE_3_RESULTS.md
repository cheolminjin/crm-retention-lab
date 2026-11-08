# Stage 3: incremental profit and rollout conditions

**In this synthetic training population, information + coupon increased mean contribution profit by KRW 1,311 per assigned customer versus information alone. Neither active arm established compliance with both unsubscribe and refund tolerances, so these results do not establish a full-rollout decision.**

This is a historical summary of the three-arm randomized experiment, not actual company revenue or market approval. Source values are in the [experiment aggregates](../report/data/experiment.json) and [assignment, balance, contact, and ledger checks](../report/data/experiment_checks.json).

## Population and method

The existing training simulation `sim-8aecf9722a5328b9` was used without changing coefficients, seeds, customers, or selecting favorable observations. The [stage-3 specification](STAGE_3_ANALYSIS_SPEC.md) fixed methods before calculating three-arm results, after control diagnostics were already known. It was not an externally preregistered confirmatory experiment.

- Population: 15,284 training customers without another payment by D+14 and meeting consent/eligibility rules.
- Assignment: no contact 5,105; information 5,064; information + coupon 5,115; each probability 1/3.
- Dates: 2025-01-15–2025-06-30 assignments, 60-day purchases plus 30-day settlement, observed before 2025-10-01 00:00 +09:00.
- Denominator: all 15,284 customers completed 90-day settlement; ITT retains failed/unopened sends and unused coupons.
- Primary outcome: 60-day contribution profit per assigned customer, excluding first orders and including discounts, refunds, product/shipping/payment/send costs. This simulated management-accounting measure is not net income.
- Inference: Welch two-sided individual 95% intervals and Holm-adjusted p-values for three profit contrasts; secondary outcomes are exploratory.

Validation/final customers were neither generated nor opened at this stage. Customer-level policies had not yet been evaluated.

## Assignment and ledger checks

SRM chi-square was 0.2867 with **p=0.8664**, above the prespecified investigation threshold `p<0.001`. This indicates no detected count anomaly, not proof of flawless assignment. Eleven pretreatment features plus last-session missingness were compared. Maximum pairwise `|SMD|` was **0.0575** for first-delivery month, below reference 0.1. Numeric features use the square root of average sample variances; categorical features use the largest absolute level-indicator SMD. Session recency and missingness were checked separately. This reference is neither a hypothesis test nor a deletion rule.

Recalculating ledger profit and send costs matched mart profit for **all 15,284 customers, with 0 mismatches**. First orders, payments outside 60 days, and records after the 90-day freeze were excluded.

## Mean contribution profit

| Arm | Assigned customers | Profit per customer, KRW | 60-day payment rate |
| --- | ---: | ---: | ---: |
| No contact | 5,105 | 14,544.86 | 61.33% |
| Information | 5,064 | 15,433.17 | 62.52% |
| Information + coupon | 5,115 | 16,743.70 | 67.78% |

Payment rates retain events later refunded and are neither profitability nor long-run retention measures.

| Prespecified contrast | Incremental profit, KRW/assigned customer | Two-sided individual 95% interval | Holm-adjusted p |
| --- | ---: | ---: | ---: |
| Information − no contact | +888.31 | +168.58 to +1,608.03 | 0.01557 |
| Information + coupon − no contact | +2,198.83 | +1,475.23 to +2,922.43 | 7.98×10⁻⁹ |
| Information + coupon − information | +1,310.53 | +576.66 to +2,044.39 | 0.000933 |

All three comparisons support positive average incremental profit in this synthetic population. The last directly measures adding a coupon to the same information. Effects compare means over each arm's full assignments, not total profits. **Intervals are individual; Holm adjustment applies to the three p-values.** These are not simultaneous intervals, and neither intervals nor p-values capture real-market mismatch.

## Operational delivery and redemption

All rates use **every assigned customer** in the corresponding arm.

| Observed action | Information: n=5,064 | Information + coupon: n=5,115 |
| --- | ---: | ---: |
| Attempted | 5,064 / 100.00% | 5,115 / 100.00% |
| Delivered | 4,757 / 93.94% | 4,808 / 94.00% |
| Opened | 2,066 / 40.80% | 1,980 / 38.71% |
| Clicked | 528 / 10.43% | 479 / 9.36% |
| Coupon issued | Not applicable | 4,808 / 94.00% |
| Coupon redeemed | Not applicable | 837 / 16.36% |

Controls have 0 additional CRM sends by design and no comparable open rate. Redemption need not be a subset of recorded opens/clicks, so this is not necessarily a monotonically shrinking funnel. Lower coupon-arm opens do not negate its total profit effect or justify restricting causal analysis to openers.

## Discounts counted once

These are **per-assigned-customer means** for orders in the repurchase window, excluding first-order discounts.

| Revenue/discount component, KRW | No contact | Information | Information + coupon |
| --- | ---: | ---: | ---: |
| List-price item subtotal | 34,133.40 | 36,114.14 | 40,174.39 |
| Other discounts | 0 | 0 | 0 |
| Redeemed CRM discounts | 0 | 0 | 490.91 |
| Discounted item revenue | 34,133.40 | 36,114.14 | 39,683.48 |

Total redeemed discounts were **KRW 2,511,000** across 837 customers. KRW 490.91 divides this by all 5,115 coupon assignments. Adding KRW 20 send cost yields observed spending of KRW 510.91 per assigned customer. Redemption spending differs from coupon face-value reservation.

| Ledger component | Information + coupon − information, KRW/assigned customer |
| --- | ---: |
| Discounted item revenue | +3,569.34 |
| Customer shipping charges | +182.43 |
| Refunds | −88.86 |
| Cost of goods | −1,831.79 |
| Inventory recovery | 0 |
| Outbound shipping | −329.54 |
| Fulfillment | −76.89 |
| Payment fees | −93.79 |
| Return handling | −20.38 |
| Send costs | 0 |
| **Incremental contribution profit** | **+1,310.53** |

Displays round to two decimals; calculations use full precision. Starting from discounted revenue means the KRW 490.91 coupon amount is not subtracted again. Components are an accounting decomposition, not independently identified causal mediation effects.

## Side-effect tolerances

The family contains **two active arms × two side effects = four control contrasts**. Divide family one-sided alpha 0.05 by 4 and use **98.75% one-sided Newcombe score upper bounds**. Differences and bounds are percentage points.

| Contrast | Outcome | Observed difference | 98.75% upper bound | Tolerance | Status |
| --- | --- | ---: | ---: | ---: | --- |
| Information − no contact | Unsubscribe | +0.163 pp | +0.542 pp | +0.5 pp | Not established |
| Information − no contact | Refunded customer | −0.102 pp | +0.811 pp | +1.0 pp | Within tolerance |
| Information + coupon − no contact | Unsubscribe | +0.722 pp | +1.174 pp | +0.5 pp | Not established |
| Information + coupon − no contact | Refunded customer | +0.441 pp | +1.379 pp | +1.0 pp | Not established |

Denominators include all assignments, not only buyers. Unsubscribe counts were 30/38/67 and refunded-customer counts 226/219/249 for control/information/coupon. **Only information-arm refunds established compliance.** Information-arm unsubscribe point estimates were below tolerance but the adjusted bound exceeded it; coupon unsubscribe point estimates already exceeded tolerance. “Not established” means the upper bound did not fit within tolerance, not that every case establishes excess harm.

The [analysis plan](ANALYSIS_PLAN.md) uses separate 97.5% one-sided bounds for **two side effects of one locked final policy**. That rule is not substituted for this four-comparison family. Newcombe/Bonferroni coverage is a nominal approximation, not an exact finite-sample binomial guarantee.

## Planning decision and remaining scope at this stage

The analysis compares average incremental profit after costs and considers coupon value alongside side-effect uncertainty. Neither active arm passed both side-effect conditions. Arm averages also do not evaluate customer-specific policies subject to a 30% contact cap and reservation budget. They do not establish universal coupon sending, approval for 10,000 customers, or individually optimal benefits.

Independent pilot power simulation remained undone; no post-hoc observed-effect power or favorable sample enlargement was used. Uplift fitting, validation selection, and locked-policy final evaluation were still pending at this stage; subsequent results are in [STAGE_4_RESULTS.md](STAGE_4_RESULTS.md). Preserve this as the training-population average experiment in a fixed synthetic world.

## Reproduction

Prepare the analysis environment at the repository root. Sources/settings are unchanged from stage 2. Use a new analysis output directory when one already exists.

```powershell
.\.venv\Scripts\python.exe scripts/run.py compare-arms --run-dir data/generated/train-diagnostic-v0.1 --output data/generated/train-experiment-final-v0.1 --report-dir report --static-svg
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'YOUR_QUARTO_PATH'
```

Replace `YOUR_QUARTO_PATH` or omit `--quarto` when on PATH. `--static-svg` is optional after static-export setup; see [RUN_GUIDE.md](RUN_GUIDE.md). JSON and charts share aggregates. Source/analysis/render manifests link outputs to generation; customer marts and oracle are excluded from public aggregates. HTML generation is separate from GitHub publication.
