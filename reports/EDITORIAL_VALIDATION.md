# Historical editorial and display validation

This record describes the **approved Korean-language edit before the English release**. Its labels are translated here for public documentation; historical counts and measurements refer to that earlier revision. Current English checks are in [ENGLISH_RELEASE_VALIDATION.md](ENGLISH_RELEASE_VALIDATION.md).

The approved 67 sentence/heading/chart-note edits and 4 display fixes were applied to generation code, then Quarto HTML and PDF were rebuilt. Original aggregates and analysis/policy code were preserved.

| Check | Historical result |
| --- | --- |
| Approved versus generated body | Matched apart from approved display fixes |
| Number/unit tokens | 0 additions/deletions after approved normalization |
| Paths, commands, source links | 0 additions/deletions |
| Aggregate JSON | All 4 matched previous SHA-256 |
| Chart data | All 14 trace sets matched except display strings and `cliponaxis` |
| Defined terms | Preserved; duplicate section-12 definition removed |
| Integer-rounding wording / Dudík | Original spellings preserved |

Display-only changes were `1000g → 1,000g` twice and negative-zero currency formatting to zero once. Values were unchanged. PDF numeric comparison added one requested reference to three arms in its reading guide. The rule-policy name was aligned with the code's package/tips definition.

General synthetic-world limitations were consolidated in section 13; individual intervals, conditional effects, bootstrap scope, and allocation limitations remained in their relevant sections. No new reasons, values, or interpretations were introduced.

## Historical rendering and execution checks

HTML and print source both retained 13 sections, 17 tables, 14 charts, 341 table cells, and 8 method-source links. Offline HTML had no external requests or browser errors. The Korean PDF remained 22 pages; every page was rendered to PNG and reviewed. Labels 56.4%, KRW 14,545, and KRW +888 were unclipped, and no-contact send cost displayed KRW 0.

Of 218 tests, 214 passed and 4 skipped because of Windows hardlink/symlink permissions; none failed. Three existing wording-test expectations were updated to approved text. A public-files-only copy ran `scripts/refresh_report.py` without private sources/models, restored Plotly JS, reproduced identical QMD, and preserved aggregate hashes. Deliberately tampered aggregates failed before output changes.

No models were refitted, policies reselected, or effects re-estimated. Original analysis-code hashes and current presentation-code hashes remain separate. Detailed historical measurements are in [EDITORIAL_VALIDATION.json](EDITORIAL_VALIDATION.json).

## Author confirmation

No interpretation item required further author confirmation. GitHub destination, visibility, and license remained undecided.
