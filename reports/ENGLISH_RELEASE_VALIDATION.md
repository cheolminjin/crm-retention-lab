# English release validation

This record and its JSON manifest describe the pre-publication checkpoint. The recorded README hash predates the later publication links and CI badge. See [GitHub publication](../docs/GITHUB_PREPARATION.md) for the repository and subsequent remote checks.

Verified 2026-11-09. The README, public design/method/result/run documents, historical validation records, generated Quarto source, chart labels/hover/annotations, HTML, PDF, and public preview images are in English. The README structure was informed by [four public examples](../docs/README_REFERENCE_NOTES.md). No hiring outcome is inferred from those examples.

## Preserved analysis

| Check against the pre-translation version | Result |
| --- | --- |
| Public analysis aggregates | All 4 SHA-256 hashes unchanged |
| Protected analysis source and configurations | All 25 files unchanged |
| Plotly trace numeric values | All 14 figures unchanged, including intervals and custom data |
| Report tables | 17 tables; numeric tokens matched cell by cell across 341 cells |
| Report source links | All 8 method links unchanged and in the same order |
| Report file paths and commands | Unchanged |
| Report-body numeric values | Unchanged after explicit language/unit normalization |
| Model fitting, policy selection, effect estimation | Not rerun |

Raw number-token differences are limited to five numeric three-arm expressions spelled out in English, one per-customer count expression translated without a numeral, and one Korean currency-unit expression expanded to **KRW 3,000,000**. These are language/unit representations, not changed quantities. Currency remains KRW, and rate differences remain percentage points. The name **Dudík** and the meaning of integer rounding down are preserved.

Decision vocabulary is consistent: **Within tolerance**, **Not established**, **Evidence of an increase**, **exploratory baselines**, and **locked policy**. The final conclusion remains **modify operating conditions or collect more evidence**. Passing resource and side-effect criteria does not establish a profit improvement when its interval includes zero.

Historical validation documents are explicitly identified as earlier checkpoints. Their test counts and measurements are not presented as new English-release measurements.

## HTML and PDF

- Both editions retain **13 sections, 17 tables, and 14 charts**; all HTML/print table cells match.
- The final PDF has **22 pages**, all rendered to PNG and visually reviewed. No blank pages or text/chart clipping was observed.
- Previously affected labels **56.4%**, **14,545 KRW**, and **+888 KRW** are visible. No-contact send cost displays **0 KRW**.
- Chart margins/fonts accommodate English labels. All 14 chart text-bound checks pass.
- Offline Chrome produced **0 JavaScript errors and 0 external HTTP(S) requests**; profit hover includes Holm information.
- At a 390px viewport, document width remains 390px. All 14 charts scroll within the page at a readable minimum width of 760px.
- Three public PNG previews and all 14 SVG charts were refreshed from the English plots.
- Authored public text and rendered report text contain no Korean text. The unchanged embedded Plotly library contains multilingual country-name aliases; these are third-party lookup data, not report content or interface labels.

## Tests and public-only reproduction

The full suite ran **218 tests: 214 passed, 4 skipped, 0 failed**. Skips concern Windows hardlink/symlink creation permissions. Wording assertions were translated; numeric and contract assertions were retained. After the final chart-title padding adjustment, all **11 visualization tests** passed again.

A copy containing only public candidate files rebuilt identical Quarto source with `scripts/refresh_report.py`, restored the missing local Plotly bundle, and preserved aggregate hashes without private sources or fitted models. A deliberately altered aggregate was rejected before output changes. This reused the installed local analysis environment; it was not a fresh remote package-installation test.

Relative documentation/image links were checked. Public candidate scanning found no personal absolute workspace paths or matches for the checked secret-key patterns. Full generated data, oracle, fitted models, customer-level recommendations, and review scratch files remain excluded by Git.

## Review records and publication status

Machine-readable results are in [ENGLISH_RELEASE_VALIDATION.json](ENGLISH_RELEASE_VALIDATION.json). Artifact hashes are in the [analysis manifest](../report/data/analysis_manifest.json), [HTML manifest](RENDER_MANIFEST.json), and [PDF manifest](../output/pdf/PDF_MANIFEST.json). The private pre-translation snapshot and body diff remain in Git-excluded review storage.

No additional interpretation requires author confirmation. At this checkpoint, no remote repository, commit, push, Pages deployment, or real campaign sending had been performed. Repository destination, visibility, and license were open publication choices. Independent pilot power, repeated A/A calibration, external validation, and remote CI were incomplete at this checkpoint; subsequent publication and CI are recorded in the linked publication document.
