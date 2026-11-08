# Stage 2 diagnosis and visualization validation

Executed 2026-11-08 on Windows. This is the historical stage-2 synthetic-training diagnostic record, not a campaign-effect validation. Later stages use the same HTML path; see [stage 3](STAGE_3_VALIDATION.md) and [stage 4](STAGE_4_VALIDATION.md).

## Inputs and findings

- Profile `configs/train_diagnostic_v0_1.json`, seed `20261108`, simulation `sim-8aecf9722a5328b9`.
- Sources `data/generated/train-diagnostic-v0.1`: 8 tables, 595,470 rows; hashes/contracts passed.
- Private marts `data/generated/train-analysis-final-v0.1`, separate from reports and Git-excluded.
- 20,000 first deliveries → 15,284 eligible assignments; 4,716 excluded; overlapping reasons total 5,089.
- All 5,105 controls settled through 90 days; 3,131 payments within 60 days, rate 61.3320%, Wilson 95% interval 59.9881–62.6589%.
- KM median 36.3965 days after assignment, approximately 50.4 after delivery; not an optimal send-date estimate.
- No validation/final customers or oracle inputs used.

## Calculation checks

| Check | Result |
| --- | --- |
| Python 3.14.3 | 112 tests: 108 passed, 4 link-permission skips |
| Python 3.10.7 core | 112 tests: 95 passed, 17 optional-package/link skips |
| Dependencies | `pip check` passed; development wrapt replaced with stable 2.5.2 |
| Small-case KM | Matches lifelines to 12 decimal places for ties, censoring, no/all events |
| Independent full-data aggregation | All 15,284 rows match orders, profit, refunds, spend, unsubscribe, repurchase, first-event time |
| Feature availability | 19,415 pre-assignment but late-recorded events excluded |
| Full-data KM | Survival/interval maximum error versus lifelines <1×10⁻¹⁴ |
| Source/public boundary | 30-customer integrated export preserves source hashes and excludes customer IDs/marts/oracle |

Actual symlink/hardlink cases skipped for permissions; pure path-escape/multiple-link guards passed. Passing tests does not validate real coffee-market assumptions.

## Report checks

Plotly 7.1.0, Kaleido 1.5.0, lifelines 0.30.3, and Quarto 1.11.9 produced four shared-aggregate charts and four SVGs. The [HTML](CRM_DIAGNOSTIC.html) was then approximately 6.52MB, with embedded scripts/styles. Offline Chrome rendered all four charts, legend groups, and hover values/95% intervals with 0 JavaScript errors and 0 external HTTP(S) requests.

Desktop 1440px and mobile 390px were reviewed; mobile body width stayed 390px without overflow. The narrow-screen toolbar was hidden where it obscured titles. Static widths 880px/342px and final browser views were inspected, fixing text/axis/cell/legend/annotation clipping. Source, mart, aggregate, QMD, render-input, and HTML hashes matched; relative README/docs links were valid.

Korean Windows paths caused Quarto Lua/temp encoding problems, resolved with ASCII installation/temp paths. `scripts/render_report.py --quarto ... --temp-dir ...` exposes the workaround.

## Reproduction and remaining work at this checkpoint

See [run guide](../docs/RUN_GUIDE.md), [methods](../docs/STAGE_2_METHODS.md), [dependency lock](../requirements-analysis.lock.txt), [analysis manifest](../report/data/analysis_manifest.json), and [render manifest](RENDER_MANIFEST.json). Sources are not overwritten; public outputs can be regenerated. Actions core/analysis-export jobs were prepared. Remote CI, other operating systems, GitHub/Pages publication, average effects, uplift, and policy evaluation had not run at this checkpoint.
