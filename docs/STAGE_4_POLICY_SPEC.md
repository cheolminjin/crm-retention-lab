# Customer-level CRM policy: specification before validation

Written 2026-11-08, after inspecting the training-period average experiment results. This is neither an external preregistration nor a real-market experiment. This specification and `configs/policy_analysis_v0_1.json` are fixed before generating validation and final data. Generator assumptions remain unchanged.

## Data and leakage prevention

Generate 20,000 validation customers and 20,000 final customers independently of the existing 20,000 training customers. This makes the initial 60,000-customer plan concrete as three separate cohorts, rather than spreading customers uniformly across the entire period. Do not increase the sample or choose seeds after seeing validation results.

| Purpose | Assignment dates; end exclusive | Outcome availability | Independent seed |
| --- | --- | --- | --- |
| Training | 2025-01-15–2025-07-01 | 2025-10-01 | 20261108; existing source |
| Validation | 2025-10-01–2025-12-01 | 2026-03-01 | 20261109 |
| Final evaluation | 2026-03-01–2026-05-01 | 2026-08-01 | 20261110 |

Source customer numbers are local to each run. Policy-mart identifiers use `simulation_id:customer_id`; identical numbers from independent seeds do not identify the same person. IDs and treatment arms are excluded from model inputs. Fit preprocessing and all models on training data only. Do not refit after validation. Generate final source data only after writing the policy lock.

## Model candidates

Compare two T-learners, each estimating contribution profit `mu_a(X)` separately for the three actions.

- Simple candidate: Ridge regression (alpha=100), median imputation, missingness indicators, standardization, and categorical one-hot encoding.
- Nonlinear candidate: HistGradientBoostingRegressor (15 leaves, minimum leaf size 80, L2=10, 120 iterations, learning rate 0.05, no early stopping).
- Predict unsubscribe and refund probabilities with arm-specific Logistic or HGB classifiers. Use an explicit constant probability when training has only one class.
- The risk baseline uses `1-p`, where a fixed Logistic model fitted on controls predicts repurchase probability.
- Allow only 11 pretreatment features. Transform missing values and unseen categories using training-fitted preprocessing. Unseen validation-season month categories are treated as unknown; extrapolation remains a limitation.

Individual treatment effects are unobserved. Prediction differences are not verified individual effects; evaluate the average value of each policy using observed RCT logs.

## Allocation rules

Batch customers assigned at 09:00 on the same day. Contact at most `floor(0.30×n)` customers and reserve at most `floor(300×n)` KRW daily. Reserve KRW 0 for no contact, KRW 20 for information, and KRW 3,020 for a coupon. Reserve the full face value even for unused coupons; this differs from realized discount spending.

There are eight uplift candidates: two models × lambda `{0,0.5,1,2}`. Score actions as `(mu_a−mu_control)−lambda×reserved_cost`. Require both positive predicted incremental profit and a positive score. Allocate in descending score order, with one action per customer and both resource caps enforced. If the best action does not fit, consider the next action. This deterministic greedy rule has fixed tie-breaking and makes no global-optimality claim.

All active candidates also enforce daily `sum(max(predicted_unsubscribe_difference,0))≤0.005×n` and `sum(max(predicted_refund_difference,0))≤0.01×n`. Predicted decreases cannot offset another customer's predicted increase. These are **prediction-based screening constraints**; independent evaluation must assess observed side effects.

Baselines are no contact, random information among eligible candidates, random coupons among eligible candidates, a package/tips rule, and coupons prioritized by non-repurchase risk. Active baselines share the budget, contact, positive predicted profit, and predicted side-effect constraints, using common HGB predictions. The rule assigns information to 200g customers with no tip views, coupons to 500g/1kg customers, and no contact otherwise. Random priorities use a fixed seed and ID hash.

## Validation selection

Evaluate profit for every candidate with DR, using the same training-fitted HGB outcome model for adjustment. A Ridge allocation policy does not receive a different adjustment model. Use the known randomization probability 1/3 and record IPW alongside DR.

Retain uplift candidates whose validation DR normal-approximation 95% lower bound exceeds the fixed-cost equivalent of KRW 10 per eligible customer and whose adjusted IPW side-effect upper bounds meet both tolerances. For screening, divide one-sided alpha 0.05 over 8 candidates × 2 outcomes = 16 comparisons. These fast validation intervals condition on fixed assignments and policy scores; they are screening tools, not final confirmatory intervals.

Among feasible candidates, retain those within one standard error of the highest DR point estimate, using the best candidate's standard error. Prefer Ridge if available. Within a model, prefer higher DR, then lower lambda and ID order for ties. Lock no contact if none qualify. Baselines are fixed comparators, not selection candidates.

The lock records the selected policy, model files, features, configuration, code, training/validation source hashes, and final generation profile. Do not reselect models, lambda, or thresholds after seeing final results.

## Independent final evaluation

The single confirmatory primary contrast is the locked policy's DR contribution profit versus no contact for everyone. IPW is a diagnostic estimator. Perform 2,000 customer bootstrap replicates **within assignment dates**, recalculating daily limits and allocation in every replicate. Treat duplicate sampled customers as separate occurrences; do not refit models. All fixed policies and no contact share the same resamples.

Assess unsubscribe and refund differences using separate 97.5% one-sided bootstrap upper bounds for IPW policy-value differences. Profit uses a two-sided 95% percentile interval. Apply confirmatory decisions only to the selected policy; baseline comparisons are exploratory. Do not switch to a better-performing baseline after final evaluation.

Planned incremental profit for 10,000 customers is `10000×incremental_contribution_profit−100000 KRW fixed_cost`. Fixed cost is zero if nobody is contacted. Do not subtract discounts or send costs already included in individual outcomes again. Classify a policy as a simulated scale-up candidate only if budget/contact constraints hold, the planned-profit lower bound is positive, and both side-effect upper bounds are within tolerance. Uncertain results require modification or more evidence; a negative profit upper bound supports holding the policy.

Intervals describe evaluation-customer sampling uncertainty conditional on the dates and fixed fitted/selected policy. They do not include the full uncertainty of fitting and selection or new markets and date compositions. Independent pilot power analysis and repeated null-world false-scale-up checks remain unfinished. This analysis does not authorize a real-market rollout.

References: [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [HGB](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html), [Doubly Robust Policy Evaluation and Learning](https://arxiv.org/abs/1103.4601).
