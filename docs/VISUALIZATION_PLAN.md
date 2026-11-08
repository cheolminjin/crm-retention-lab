# Visualization research and design

Research/initial implementation: 2026-11-08. This records the original choice of **Plotly + Quarto**. At the stage-3 checkpoint, four diagnostic and five experiment charts were implemented on the 20,000-customer training profile. The later policy stage added five charts, bringing the integrated report to 14. Budget exploration and web publication remain future work.

## 1. Selected approach

Use **Plotly charts within a Quarto narrative report**, connecting the business question, evidence, and decision. A future GitHub Pages site can host the HTML; README/PDF/slides use static exports of the same results.

- Plotly provides hover, zoom, and legend interaction.
- Quarto organizes charts, tables, narrative, methods, and code.
- GitHub Pages hosts completed static HTML/CSS/JavaScript.
- Static images make key charts directly readable in README, PDF, and slides.

This combination is a project-specific judgment, supported by [Plotly HTML export](https://plotly.com/python/interactive-html-export/), [Quarto dashboards](https://quarto.org/docs/dashboards/), and [Quarto GitHub Pages publishing](https://quarto.org/docs/publishing/github-pages.html). Marketing planning needs room beside charts to explain findings and campaign implications. The initial proposal was a 4–5-section narrative, adding exploration after results were available.

## 2. Alternatives considered

| Approach | Output | Strength | Relative effort | Project role |
| --- | --- | --- | --- | --- |
| Matplotlib static charts | PNG/SVG/PDF | Precise axes, annotations, intervals | Low; font/export QA | README/slides/static survival curves |
| Plotly HTML alone | Browser chart files | Hover/zoom/legends without Python server | Low–medium; narrative integration needed | Early prototype |
| Plotly + Quarto | Narrative HTML | Evidence, assumptions, conclusions, code; static hosting | Medium; Quarto CLI/configuration | **Primary portfolio** |
| Plotly + Streamlit | Interactive Python app | Recalculate budgets/targeting conditions | Medium–high; runtime/hosting/state | Possible later simulator |

Effort levels are relative project judgments, not official benchmarks. Sources: [Matplotlib savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html), [Plotly export](https://plotly.com/python/interactive-html-export/), [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## 3. Publication and execution boundaries

GitHub repository previews differ from GitHub Pages. Notebook previews do not run arbitrary JavaScript interactions, so README uses images and links to HTML. See [GitHub non-code files](https://docs.github.com/en/repositories/working-with-files/using-files/working-with-non-code-files) and [Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

Static HTML supports hover, zoom, and selection among precomputed data. Refitting Python models or rerunning bootstrap in response to input requires another execution mechanism; [Quarto distinguishes client/server interactions](https://quarto.org/docs/dashboards/interactivity/index.html). Precomputed cohort/package summaries suffice here. A bounded budget scenario set could also be static; unrestricted recalculation would justify an app.

Plotly PNG/SVG/PDF export needs Kaleido and compatible Chrome/Chromium. SVG export was verified on Windows with Kaleido/Chrome. Survival static plots could also use lifelines/Matplotlib. See [static image export](https://plotly.com/python/static-image-export/).

## 4. Chart design

These are design requirements, not effect claims. Each chart identifies synthetic data, cutoff, population, unit, and sample size.

| Business question | Chart | Required interpretation | Implementation |
| --- | --- | --- | --- |
| How many first buyers are CRM-eligible? | Eligibility flow / horizontal bars | First delivery → D+14 → eligible; distinguish pending/no consent/prior purchase | Diagnostic stage |
| Which cohorts repurchase later? | Assignment month × 7/14/30/60-day heatmap | Eligible controls; whole cohort passes 90-day freeze; immature cells blank | Diagnostic stage |
| How does timing vary? | `1−S(t)` curves with 95% intervals | Eligible controls; time since assignment; risk sets/censor marks | Diagnostic stage |
| Which situations motivate hypotheses? | Segment points/intervals | Pretreatment control groups; common period and sample counts | Diagnostic stage |
| What did information/coupons add? | Effect/interval plot | info−control, coupon−control, coupon−info; zero line; KRW/customer; multiplicity | Implemented |
| What remains after costs? | Contribution-profit waterfall | Same denominators; revenues/costs/returns/sends; no duplicate discounts | Coupon−information implemented |
| Which policy fits the budget? | Budget cap × estimated incremental profit | Shared contact/reservation limits; spending distinct; uncertainty | Fixed-cap policy results implemented; budget exploration pending |
| Who receives what? | Segment/action/message operating table | Eligibility, no contact/information/coupon, copy, CTA, suppression | Final campaign proposal pending |

### Interpretation rules

- Eligibility is not churn. Pending D+14 customers are not lost; exclusion reasons overlap.
- The generator covers only 60 days after D+14, not 6-/12-month retention.
- Final heatmaps require 90-day freeze; KM handles right censoring. Recent 7-/14-day diagnostics would need a separate provisional definition, not early final labels.
- Repurchase is `1−S(t)`, not `S(t)`; [KaplanMeierFitter](https://lifelines.readthedocs.io/en/stable/fitters/univariate/KaplanMeierFitter.html) supports cumulative distributions, intervals, and risk sets.
- Natural timing does not establish optimal send dates.
- Segment differences motivate hypotheses, not causal claims based on oracle traits or post-treatment opens/redemption.
- Arm-average profit differs from policy-level incremental profit; do not compare totals from different populations as equal effects.
- Subtract discounts once when starting at list revenue, and never again when starting at discounted revenue. Component bars are not independent mediation effects or separately invented intervals.
- Budget/target exploration belongs to training/validation. Final screens show a locked policy rather than enabling reselection on test results.
- Show unsubscribe/refund tolerances and confidence upper bounds beside profit.

## 5. Reading sequence

1. Business question, customer journey, eligibility.
2. Cohorts, cumulative repurchase, segment hypotheses.
3. Three-arm effects, costs, uncertainty.
4. Feasible policies and target/message/benefit decisions.
5. Assumptions, metrics, censoring, splits, locks, reproduction.

Center each view on one question and one or two charts. Before analysis, titles are questions; afterward, use findings supported by results. Do not prewrite success claims such as reduced coupon waste.

## 6. Visual rules and outputs

Keep no contact gray, information blue, and coupons orange; use labels/line styles as well as color. Use white backgrounds, limited colors, and whitespace; avoid decorative 3D, dual axes, and doughnuts for core comparisons. Show KRW/customer or an explicit rollout population, and percentage-point differences. Core findings/denominators must remain readable without hover. Check mobile axes, legends, and tables. HTML/static outputs share aggregates without view-layer recalculation. The English release uses system fonts and distributes no font files.

Outputs: `report/assets/figures/*.html|json|svg`, `report/data/diagnostics.json`, `report/index.qmd`, and `reports/CRM_DIAGNOSTIC.html`. Quarto scratch output stays in `report/_site`, preserving design documents in `docs/`. Final HTML embeds Plotly/styles and removes Google web-font dependencies.

## 7. Visual references

- [Quarto Customer Churn dashboard](https://jjallaire.github.io/customer-churn-dashboard/): Python layout reference for cards/charts/tables, not evidence of our effects.
- [Quarto HTML article](https://quarto-dev.github.io/quarto-gallery/articles/html/html.html): prose/charts/tables/foldable code; R example used only for structure.
- [Plotly waterfall examples](https://plotly.com/python/waterfall-charts/): accounting decomposition display.

The implemented sequence is **analysis marts → Plotly charts → SVG from the same results → Quarto report**. See [methods](STAGE_2_METHODS.md) and [commands](RUN_GUIDE.md). Reconsider a dashboard app only when required recalculation is defined.
