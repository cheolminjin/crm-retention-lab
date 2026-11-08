# Stage 2: repurchase diagnosis and interpretation

This stage examines **which first-purchase customer situations should inform CRM planning** for a fictional coffee shop. It identifies D+14 eligibility among 20,000 first-delivery customers and diagnoses control-group timing and segment differences. Information/coupon incrementality, profitability, and uplift policies are outside this stage's results. All values are synthetic, not measured coffee-consumer behavior or brand performance.

## Population and timing

| Item | Run definition |
| --- | --- |
| Profile | [`train_diagnostic_v0_1.json`](../configs/train_diagnostic_v0_1.json) |
| Generator | [`generator_v0_1.json`](../configs/generator_v0_1.json), `base` scenario |
| Customers / seed | 20,000 first deliveries; `20261108` |
| Simulation ID | `sim-8aecf9722a5328b9` |
| First deliveries | 2025-01-01–2025-06-16 at 09:00 Korean time |
| Eligibility / assignment | 14 days after first delivery at 09:00; 2025-01-15–2025-06-30 |
| Scope | Prespecified `train` split only |
| Cutoff | Records before 2025-10-01 00:00 +09:00 |
| Purchase window | Assignment inclusive; assignment+60 days exclusive |
| Final labels | Only after assignment+90-day settlement |

This profile did not generate validation/final customers. Even the last assignment completed settlement, so all 5,105 controls have mature outcomes. The diagnostic code separately handles censoring and immature labels for shorter runs. Day 14 on assignment-based charts is **day 28 after first delivery**; the 60-day window ends at day 74 after delivery.

## Eligibility

Customers must reach 14 days after delivery without another payment and satisfy order-status, consent, and contactability rules. Eligible customers are randomized to no contact, information, or information + coupon. The diagnostic denominator is primarily **controls receiving no additional CRM message**; essential order/delivery notices are identical across arms.

| Selection stage | Customers | Definition |
| --- | ---: | --- |
| Training first deliveries scheduled for D+14 assessment | 20,000 | First delivery and scheduled assignment |
| Reached D+14 | 20,000 | Before cutoff |
| Eligible / assigned | 15,284 | 76.42% of first deliveries |
| Ineligible | 4,716 | 23.58% of first deliveries |
| No contact | 5,105 | Main diagnostic population |
| Information / coupon | 5,064 / 5,115 | Assignment counts only at this stage |

Exclusion reasons were additional payment (1,163), missing consent (2,873), unavailable email (791), and full first-order refund (262). Reasons overlap, so their sum is not the ineligible count. This is campaign selection, not a churn funnel.

## Mart observation rules

Features require both occurrence and availability before assignment. Late-arriving analytics events are excluded even if they occurred earlier. Use observed package size, quantity, payment, discount, delivery time, channel, and early behavior. `first_pack_grams` is **one package's size**, not total purchased grams or actual consumption speed. Oracle traits/consumption are never read as analysis inputs.

A repurchase event is the first additional payment within the window. Later refunds do not erase that event. Repurchase is therefore distinct from net revenue or profitability; first orders are excluded.

## Chart calculations

### 1. Assignment-month cumulative repurchase heatmap

Rows are assignment months; columns are 7/14/30/60 days after assignment. Each cell divides controls with at least one payment in `[assignment, assignment+h days)` by all controls in that month. A payment exactly at assignment+7 days is excluded from the 7-day cell. Mark a cohort final only when every member passes 90-day label freeze; leave immature cells blank, not zero. All January–June cohorts matured. January starts on the 15th and is a partial month, so read counts alongside rates.

### 2. Kaplan–Meier cumulative repurchase

Time starts at assignment. `S(t)` estimates the probability of no repurchase yet; charts show **cumulative repurchase `1−S(t)`** for all controls and 200g/500g/1kg first-package groups. Censor non-repurchasers at `min(assignment+60 days, observation cutoff)`. Censoring means observation ended, not permanent churn. Unsubscribes do not censor purchase records.

Process tied payments before censoring. Risk sets count customers immediately before each time, including events/censoring at that time. Show censor marks and risk counts at 0/14/30/60 days. Do not extrapolate beyond observed follow-up. Greenwood variance with a log-log transformation gives survival intervals, transformed to `1−S(t)`. These are **pointwise 95% intervals**, not simultaneous bands. Small cases with ties, no events, and all events were checked against [lifelines](https://lifelines.readthedocs.io/en/stable/fitters/univariate/KaplanMeierFitter.html).

The median is the first time `S(t)≤0.5`, not the mean or buyers-only average. Report “not reached” when fewer than 50% repurchase during observation.

### 3. Segment-level 60-day repurchase

Show mature-control repurchase rates, sample sizes, and Wilson 95% intervals by first package; tip-view status is a supplementary grouping. Do not treat immature outcomes as nonpurchase. Package/tip groups were not randomized. Differences are associations for planning hypotheses, not effects of changing packages or showing tips. No segment-ranking or multiple-superiority tests were conducted.

## Findings in this synthetic sample

Of 5,105 controls, 3,131 repurchased within 60 days: **61.3%, Wilson 95% interval 60.0–62.7%**. The remaining 1,974 had no observed payment within 60 days and are not classified as permanently churned. The overall KM median was **36.4 days after assignment**, approximately 50.4 days after delivery; it is not an optimal send date.

| First package | Controls | Repurchasers | Rate | Wilson 95% interval | KM median after assignment |
| --- | ---: | ---: | ---: | ---: | ---: |
| 200g | 1,517 | 856 | 56.4% | 53.9–58.9% | 37.1 days |
| 500g | 1,845 | 1,194 | 64.7% | 62.5–66.9% | 30.2 days |
| 1kg | 1,743 | 1,081 | 62.0% | 59.7–64.3% | 41.3 days |

The 500g group had a higher observed rate and earlier median; 1kg customers had a later median. This supports a hypothesis of tailoring storage/brewing help and repurchase information using first products and early behavior. It does not establish coupon targets or package size as the cause.

## Uncertainty and limitations

Intervals describe customer-sample uncertainty within fixed synthetic rules and coefficients. They exclude real-market mismatch, incorrect consumption/demand assumptions, and price/channel changes. More simulated customers can narrow intervals without improving realism.

- Scope is D+14 non-repurchasers meeting contact eligibility, not early repurchasers, nonconsenting customers, or all first buyers.
- Transactions extend through D+74 after first delivery; no 6-month/12-month retention or long-run customer lifetime value is estimated.
- This run has complete maturity, without early administrative censoring. Shorter runs require KM censoring and an independence assumption between censoring and events.
- Payment rates differ from profit after discounts, refunds, shipping, and other costs. This stage makes no information/coupon ROI or incremental-revenue claim.
- All assignments occur at D+14; natural curves cannot identify the optimal sending date.

Planning outputs are customer hypotheses and tests, not claims of achieved real-world sales growth.

## Reproduction and validation

Run from the repository root after following [RUN_GUIDE.md](RUN_GUIDE.md). The original source path is `data/generated/train-diagnostic-v0.1`. Matching profiles, seeds, and generator code reproduce identical sources at another path. Validate source hashes/configuration before reading; build marts from observed tables without oracle access. Never edit source data to improve charts.

```powershell
.\.venv\Scripts\python.exe scripts/run.py generate --config configs/train_diagnostic_v0_1.json --output data/generated/train-diagnostic-v0.1 --oracle-output data/oracle/train-diagnostic-v0.1
.\.venv\Scripts\python.exe scripts/run.py validate --run-dir data/generated/train-diagnostic-v0.1
.\.venv\Scripts\python.exe scripts/run.py diagnose --run-dir data/generated/train-diagnostic-v0.1 --output data/generated/train-analysis-v0.1 --report-dir report
.\.venv\Scripts\python.exe scripts/run.py test --pattern test_diagnostics.py
```

Use new output names when directories already exist, updating downstream `--run-dir` accordingly. Add `--static-svg` after setting up static export. `diagnose` writes `report/data/diagnostics.json`, `report/data/analysis_manifest.json`, and inputs for `report/index.qmd`.

```powershell
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'YOUR_QUARTO_PATH'
```

Replace `YOUR_QUARTO_PATH` with the installed executable, or omit `--quarto` if on PATH. Validated version: Quarto 1.11.9. A render-only alternative is `quarto render report/index.qmd --to html`. The script checks QMD/manifest consistency, copies `report/_site/index.html` to `reports/CRM_DIAGNOSTIC.html`, and records input/HTML hashes in `reports/RENDER_MANIFEST.json`. Rendering does not publish to GitHub Pages.

Tests cover KM ties/endpoints, unreached medians, Wilson intervals, immature cohorts, training-only scope, and independent lifelines comparison. HTML and static charts use the same aggregates without recalculating metrics in the view.
