# Stage 3 experiment and integrated report validation

Executed 2026-11-08, Windows / Python 3.14.3. Historical checks used existing synthetic training data without opening new evaluation customers or oracle.

## Inputs and outputs

- `data/generated/train-diagnostic-v0.1`, `sim-8aecf9722a5328b9`: configuration/eight source-table hashes passed; source manifest unchanged.
- 15,284 assignments: control 5,105, information 5,064, coupon 5,115; all completed 90-day settlement.
- Private marts `data/generated/train-experiment-final-v0.1`, separate and Git-excluded.
- [Experiment aggregates](../report/data/experiment.json) and [checks](../report/data/experiment_checks.json).
- [Integrated HTML](CRM_DIAGNOSTIC.html) then contained 4 diagnostic + 5 experiment = 9 interactive charts; all 9 SVGs exported.

## Calculation and boundary checks

| Check | Result |
| --- | --- |
| Python 3.14 | 147 tests: 143 passed, 4 link-permission skips |
| Python 3.10 core | 147 tests: 104 passed, 43 external-package/link skips |
| Dependencies | `pip check` passed; existing SciPy 1.18.1, no extra installation |
| Welch | Statistic, degrees of freedom, p, and interval match independent `ttest_ind(equal_var=False)` |
| Newcombe | Matches literature examples maintained by statsmodels and boundary cases |
| One-sided Wilson | Matches SciPy binomial-test Wilson upper bounds |
| Holm / sparse cases | Order, fixed family size, empty groups, zero variance, immaturity |
| Full ITT | Immaturity stops before report changes; no send/open-based exclusions |
| Accounting | All 15,284 customer profits/orders/refunds/spend reconcile; 0 mismatches |
| Timing | First orders excluded; payment day-60 and record day-90 boundaries excluded |
| Public boundary | No IDs/marts/oracle; diagnostics and source hashes preserved |

Actual symlink/hardlink cases skipped for permissions, but pure boundary guards passed. Python 3.10 optional skips do not imply experiment-render validation in that environment.

## Result linkage

- Information−control: KRW +888.3066/customer; individual 95% interval +168.5809 to +1,608.0322; Holm p=0.0155664.
- Coupon−control: +2,198.8321; interval +1,475.2336 to +2,922.4307; Holm p=7.9843×10⁻⁹.
- Coupon−information: +1,310.5256; interval +576.6605 to +2,044.3906; Holm p=0.000932778.
- Waterfall component mean differences sum to the final effect without another coupon deduction.
- SRM p=0.8664486; maximum |SMD|=0.0575325; no post-hoc exclusions.
- Only information-arm refunds passed among four 98.75% one-sided side-effect bounds. These differ from profit's individual 95% intervals and the final locked policy's 97.5% rule.

## Browser and rendering checks

Plotly 7.1.0 / Kaleido 1.5.0 / Quarto 1.11.9 produced an approximately 6.61MB single HTML. Offline Chrome rendered 9 charts with 0 JavaScript errors and 0 external HTTP(S) requests. KM legend clicks toggled curves/intervals together; incremental-profit hover exposed differences, intervals, Holm p, and both denominators.

Desktop 1440px and mobile 390px were checked without page overflow. Chart widths 880px/339px were reviewed for text, axes, annotations, waterfall components, and one-sided bounds; top side-effect labels were unclipped. Source, code, mart, specification, aggregate, QMD, render, and final HTML hashes matched; relative links were valid. See [analysis manifest](../report/data/analysis_manifest.json), [render manifest](RENDER_MANIFEST.json), and `compare-arms` in the [run guide](../docs/RUN_GUIDE.md).

## Remaining at this checkpoint

Independent pilot power, uplift/selection/lock/final evaluation had not run yet; later policy work is recorded separately. Average synthetic effects do not establish real-market success or universal rollout. Remote CI and GitHub/Pages publication had not occurred.
