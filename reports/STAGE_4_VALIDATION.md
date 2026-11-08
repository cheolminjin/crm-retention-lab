# Stage 4: policy analysis and report validation

Validation date: 2026-11-08. Reviewed the [integrated HTML](CRM_DIAGNOSTIC.html), [policy aggregates](../report/data/policy.json), and [analysis results](../docs/STAGE_4_RESULTS.md). The data are synthetic; no real campaign was sent. This is the historical stage-4 validation record. Current English rendering checks are recorded separately in [English release validation](ENGLISH_RELEASE_VALIDATION.md).

## Code and environment

| Environment | Total tests | Passed | Skipped |
| --- | --- | --- | --- |
| Python 3.14.3; locked analysis dependencies | 218 | 214 | 4 |
| Python 3.10.7; no external analysis packages | 218 | 133 | 85 |

The 3.14 skips concern link tests unsupported in that environment. The 3.10 run skips optional-analysis-dependency and link tests. `pip check` passed. After the final interpretation edits, 30 relevant mart/report tests passed again.

New checks cover training-only fitting, unseen categories, new missingness, negative profit, single-class outcomes, policy split timing and namespaces, rounded-down budgets, one action per customer, duplicated bootstrap occurrences, hand-calculated DR/IPW, side effects, fixed costs, lock-tampering rejection, and aggregate-driven charts and interpretation.

## Lock and independent-evaluation audit

- The final policy was the same HGB λ=0.5 selected on validation; training models were not refitted afterward.
- Actual lock time was `2026-11-08T13:36:48.977…+00:00`; final source generation was recorded at `2026-11-08T13:38:22+00:00`. Execution UTC times differ from synthetic business dates 2026-03-01/08-01.
- Lock digest, model, code, configuration, analysis digest, and final source-manifest hashes were checked. Decision code was unchanged after locking.
- All 15,284 training, 15,167 validation, and 15,363 final assigned customers completed 90-day settlement. ID namespaces and seeds were separate.
- Six fixed policies used identical resampling indices with B=2,000 each; final results did not trigger reselection.
- All 61 daily batches met contact, reservation, and predicted-risk conditions. Bootstrap constraint violations totaled 0.
- Private customer-level allocations contained 15,363 rows; overall and daily summaries matched public results. Public aggregates contained no individual customer ID values or absolute local paths.
- No-contact DR/IPW differences versus itself were exactly 0. Every policy used all 15,363 customers as its denominator, rather than only matching assignments.
- The selected policy's DR interval included 0 and both side-effect upper bounds met tolerance, supporting `modify_or_collect_more_evidence`.

This audit used lock, aggregate, and allocation records. It did not rerun analysis to search final results or reselect a model.

## Report and visualization

- Quarto 1.11.9 added sections 9–12 and five policy charts to the existing report: 14 Plotly charts including the nine diagnostic/experiment charts.
- All five new charts had HTML, JSON, and SVG exports, using the same public aggregates as the tables.
- Offline local Chrome rendered all 14 charts with 0 JavaScript errors and 0 external HTTP requests.
- Reviewed desktop 1440×1000 and mobile 390×844 layouts. Mobile document width was 390px without page overflow; policy charts scrolled within a 630px area, with 291px actual scroll movement verified.
- Checked KM legend toggling and confidence-interval hover, experiment Holm-value hover, policy DR/95% interval/B=2,000 hover, and side-effect 97.5% upper-bound hover.
- Visually reviewed selection, incremental profit, allocation, side effects, package-level allocation, and mobile header. See the [policy profit preview](figures/policy-profit-preview.png).
- Final HTML/input hashes are in [RENDER_MANIFEST.json](RENDER_MANIFEST.json); aggregate/code hashes are in [analysis_manifest.json](../report/data/analysis_manifest.json).

## Remaining scope

Independent pilot power, repeated A/A-world coverage and false scale-up rates, structural-shift scenarios, clean remote installation, and GitHub Actions execution remain separate tasks. Customer bootstrap intervals do not validate all of those uncertainties or actual market performance. No GitHub upload occurred in this validation stage.
