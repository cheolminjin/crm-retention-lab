# Reference cases and design choices

Reviewed 2026-11-08. These public project descriptions and methods informed the design; their code was not downloaded and rerun for verification. We did not verify whether individual projects were used in successful job applications.

## 1. PA Data Analytics: synthetic Shopify cohort analysis

[Cohort retention analysis](https://www.padataanalytics.com/case-studies/shopify-cohort-retention-analysis/)

This portfolio uses Shopify-style synthetic orders generated with Python, identifies itself as a demonstration rather than client work, and analyzes repeat-purchase patterns by cohort. It informed prominent synthetic-data disclosure and cohort/time breakdowns. This project extends diagnosis into randomized intervention and cost-aware policy comparison. The reference's repurchase rates are not used as measured Korean coffee-retail benchmarks or targets.

## 2. umar80643: Customer Retention Uplift Modeling

[GitHub repository](https://github.com/umar80643/customer-retention-uplift-modeling)

This synthetic randomized-offer project distinguishes customer risk from changes caused by an offer and discusses how model advantages can vary across effect structures. It informed risk-first versus effect-first policy comparisons and checks under changing generation structures. Here, first-to-repeat purchase replaces churn prevention, three actions replace a binary offer, and contribution profit defines value. Its performance numbers are not expected results for this project.

## 3. parisaMSTFV: Marketing Experiment Incrementality

[GitHub repository](https://github.com/parisaMSTFV/marketing-experiment-incrementality)

This synthetic randomized campaign separates behavioral gains from economic value after costs and reports redesign decisions when uncertainty remains. It informed ITT, discounts on organic purchases, prespecified economic decisions, and reporting unfavorable conclusions. This project adds customer-level actions under shared operating constraints. CUPED is not copied directly: first-time buyers lack extensive pretreatment repeat-revenue histories, so useful covariates must be assessed first.

## 4. Kevin Hillstrom: MineThatData E-Mail Challenge

[Experiment and data](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html?m=0) · [Uplift solution](https://blog.minethatdata.com/2008/05/best-answer-e-mail-analytics-challenge.html)

The public challenge randomized 64,000 customers into two product-category emails and no contact, then compared visits, purchases, and spending. It asks whom to contact and whom to leave uncontacted. Mens/Womens identify promoted product categories, not recipients' genders.

It informed the three-arm/no-contact structure, targeting question, and separation of revenue from response metrics. This project generates its own world rather than reproducing those data and explicitly controls content equivalence and coupon costs. A separate external benchmark could follow a review of access/use terms; those data are not mixed into or redistributed with this project.

## 5. Official method documentation

| Source | Use |
| --- | --- |
| [lifelines: univariate survival analysis](https://lifelines.readthedocs.io/en/latest/Survival%20analysis%20with%20lifelines.html) | Kaplan–Meier and censoring implementation |
| [scikit-learn: Ensemble methods](https://scikit-learn.org/stable/modules/ensemble.html) | Histogram gradient boosting and validation |
| [EconML: Doubly Robust Learning](https://www.pywhy.org/EconML/spec/estimation/dr.html) | DR background and possible future estimator extensions |

Current online documentation can differ from installed versions; check the installed version and lock dependencies. DR **policy-value evaluation** and DR **treatment-effect learning** are related but distinct. V1 uses a T-learner for effect learning.

## 6. Original project assumptions

The fictional coffee shop, D+14 eligibility, 60-day outcomes plus 30-day settlement, products, prices, coupon, budget, side-effect tolerances, time splits, and generation assumptions are original portfolio choices. They are not measured reference-case values or validated industry standards. Problem and validation structures informed an independent implementation; wording, charts, and code were not copied. Any future file reuse requires separate attribution and license records.

README-specific examples are documented in [README_REFERENCE_NOTES.md](README_REFERENCE_NOTES.md).
