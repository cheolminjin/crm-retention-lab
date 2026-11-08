# Data generation, analysis, and report guide

Run commands from the repository root. Stage 1 uses only the Python standard library. The full local environment is Windows / Python 3.14.3; Python 3.10.7 was also checked for dependency-free core compatibility.

## 1. Environment

On a new computer, install a working Python 3.10 or newer. If `python` opens an installation prompt, use the installed executable explicitly. For dependency-free generation/validation:

```text
python -m venv --without-pip .venv
```

Source-checkout execution needs no package installation for stage 1. `.venv` is excluded from Git. **Full analysis/visualization was validated on Python 3.14.3**; the 3.10 check does not validate optional analysis packages. For full analysis, create a normal Python 3.14 environment with `python -m venv .venv`, or add pip to an existing environment with `python -m ensurepip`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-analysis.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

The lock records actual Windows / Python 3.14.3 dependencies; other operating systems await CI verification. Install [Quarto separately](https://quarto.org/docs/get-started/) (validated version 1.11.9). SVG export also needs Chrome/Chromium. Use an ASCII-only Windows Quarto installation path: this environment encountered Pandoc Lua loading failures under a Korean path, resolved with the same distribution in an ASCII path.

## 2. Tests

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/run.py test
```

macOS/Linux equivalent:

```sh
.venv/bin/python scripts/run.py test
```

Both use the same source entry point. Actual local execution was on Windows; the prepared GitHub Actions workflow is intended to check Linux later.

## 3. Development data

```powershell
.\.venv\Scripts\python.exe scripts/run.py generate --config configs/smoke_v0_1.json --output data/generated/my-first-run --oracle-output data/oracle/my-first-run
```

Defaults: 1,000 customers, seed 101, January–June 2025 deliveries, cutoff 2025-07-01. This is outside final evaluation. Explicit overrides such as `--customers 200` and `--seed 202` are available. Observed/oracle directories cannot overlap. Existing populated outputs are never overwritten; use a new name such as `my-second-run`.

```text
data/generated/my-first-run/
├─ observed/                 # Eight allowed tables, JSONL
├─ config.snapshot.json      # Effective configuration
├─ validation.json           # Checks and results
└─ manifest.json             # Seed, runtime, config/code/file hashes

data/oracle/my-first-run/
├─ latent_customers.jsonl    # Hidden consumption/preferences/price sensitivity
└─ ORACLE_NOTICE.json        # Excluded from analysis; potential outcomes not implemented
```

JSONL preserves numbers, nulls, booleans, and reason lists with one object per line. Marts also use JSONL; Parquet is not implemented.

## 4. Validate saved files

```powershell
.\.venv\Scripts\python.exe scripts/run.py validate --run-dir data/generated/my-first-run
```

Configuration/source hashes are checked before table contracts. Changed data or inconsistent ledgers/eligibility produce errors and nonzero exit status. Passing does not prove market realism.

## 5. Scenarios

| CLI value | Meaning |
| --- | --- |
| `base` | Information/coupon effects partly associated with observed features |
| `no_behavior_effect` | Zero purchase-behavior effects; send costs and discounts on organic purchases remain |
| `a_a_zero_cost` | Zero treatment-driven behavior and CRM costs; product/normal order costs remain |

Append, for example, `--scenario no_behavior_effect` to `generate` and use new output paths. Cost, demand, and response-shift scenarios remain unimplemented and are rejected by the CLI. Incremental coupon purchase effects require delivered, unused, unexpired coupons. Information effects may persist for their prespecified duration after redemption. Coefficients are assumptions, not market estimates.

## 6. Public sample

```powershell
.\.venv\Scripts\python.exe scripts/run.py sample --config configs/smoke_v0_1.json --customers 20 --output data/sample/new-example
```

This generates a separate 20-customer synthetic sample without saving oracle files. See the [sample guide](../data/sample/README.md). Samples demonstrate schema, not treatment effects.

## 7. Current boundaries

- Transactions cover initial purchases and 60 days after D+14, not long-run histories.
- Customers not yet at D+14 have no assignment/eligibility decision. Final profit is `None` until 90-day settlement.
- Oracle contains latent traits, not action-specific potential outcomes or true average effects.
- Training-only fitting, validation selection, policy locking, and independent final evaluation are implemented. Real-market rollout and independent pilot power remain separate work.
- Remote GitHub Actions, package distribution, and real message sending have not occurred.

## 8. Training-only diagnosis and HTML

Use new source/mart names if these paths already exist. Commands update the aggregates, charts, and QMD under `report`.

```powershell
.\.venv\Scripts\python.exe scripts/run.py generate --config configs/train_diagnostic_v0_1.json --output data/generated/train-diagnostic-v0.1 --oracle-output data/oracle/train-diagnostic-v0.1
.\.venv\Scripts\python.exe scripts/run.py diagnose --run-dir data/generated/train-diagnostic-v0.1 --output data/generated/train-analysis-v0.1 --report-dir report --static-svg
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'C:\Tools\Quarto\bin\quarto.cmd'
```

Replace the Quarto path, or omit `--quarto` when on PATH. On macOS/Linux use `.venv/bin/python` and `quarto`. `quarto render report/index.qmd --to html` only renders; `render_report.py` also copies to `reports/CRM_DIAGNOSTIC.html` and records hashes.

For Windows temporary-path encoding or permission failures, add `--temp-dir 'C:\path\to\writable-ascii-temp'`. This environment required ASCII installation and temporary paths. `--static-svg` is optional for diagnosis; failure leaves HTML/JSON and records SVG errors in the manifest. If Chrome is not discovered, set `$env:BROWSER_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'`. Quarto combines precomputed aggregates/charts without running analysis.

| Output | Contents / publication |
| --- | --- |
| `data/generated/train-analysis-v0.1/*.jsonl` | Customer features/outcomes; Git-excluded |
| `report/data/diagnostics.json` | ID-free diagnostic aggregates |
| `report/data/analysis_manifest.json` | Input/source/mart/aggregate hashes and versions |
| `report/assets/figures/*` | Four charts: HTML fragments, JSON, optional SVG |
| `report/assets/plotly.min.js` | Installed JS bundle; regenerated, Git-excluded |
| `report/index.qmd`, `_quarto.yml`, `styles.css`, `theme.scss` | Report content/configuration/styles |
| `report/_site/index.html` | Quarto output; Git-excluded |
| `reports/CRM_DIAGNOSTIC.html` | Reviewed single-file public report |
| `reports/RENDER_MANIFEST.json` | Quarto version and render-input/HTML hashes |

`diagnose` validates input hashes/contracts and reads training data only. `--as-of` can request an earlier snapshot but cannot exceed source cutoff or prespecified training availability. Keep sources, marts, and public reports in separate directories. See [stage-2 methods](STAGE_2_METHODS.md).

## 9. Add the three-arm comparison

Reuse the same sources. `compare-arms` retains four diagnostic charts and adds five experiment charts/interpretation. SciPy 1.18.1 is included in the lock.

```powershell
.\.venv\Scripts\python.exe scripts/run.py compare-arms --run-dir data/generated/train-diagnostic-v0.1 --output data/generated/train-experiment-final-v0.1 --report-dir report --static-svg
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'YOUR_QUARTO_PATH'
```

Use new mart names for existing outputs. Quarto/temporary-path options follow section 8. Refresh any open browser to see the updated `reports/CRM_DIAGNOSTIC.html`.

- Added aggregates: `report/data/experiment.json`, `report/data/experiment_checks.json`.
- Added charts: `arm_profit`, `profit_effects`, `coupon_info_waterfall`, `safety_effects`, `balance`.
- Training enrollment must end and every assignment complete 90-day settlement. Immaturity or reconciliation failure stops before report updates.
- There is no option to remove failed sends/unopened messages.
- `diagnose` creates stage 2 only; use `compare-arms` to retain the experiment section.

See the [prespecified methods](STAGE_3_ANALYSIS_SPEC.md) and [results](STAGE_3_RESULTS.md). Independent pilot power and policy models are outside this command.

## 10. Lock a policy and evaluate independently

Candidates/selection rules are fixed in the [stage-4 specification](STAGE_4_POLICY_SPEC.md) and `configs/policy_analysis_v0_1.json`. If paths exist, use a new run name consistently. Do not generate final sources first: `select-policy` refuses an existing final path.

```powershell
.\.venv\Scripts\python.exe scripts/run.py generate --config configs/validation_policy_v0_1.json --output data/generated/policy-validation-v0.1 --oracle-output data/oracle/policy-validation-v0.1
.\.venv\Scripts\python.exe scripts/run.py select-policy --train-run data/generated/train-diagnostic-v0.1 --validation-run data/generated/policy-validation-v0.1 --output artifacts/runs/policy-v0.1 --final-run data/generated/policy-final-v0.1
.\.venv\Scripts\python.exe scripts/run.py evaluate-policy --policy-dir artifacts/runs/policy-v0.1 --generate-final
.\.venv\Scripts\python.exe scripts/run.py report-policy --policy-dir artifacts/runs/policy-v0.1 --report-dir report --static-svg
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'YOUR_QUARTO_PATH'
```

`select-policy` fits preprocessing/two models on training only and screens eight validation candidates, saving policy JSON/digest and model/code/configuration hashes. `evaluate-policy --generate-final` verifies the lock before generating/evaluating final customers from the locked profile. Oracle is stored separately and never read by fitting/evaluation.

An existing completed `analysis.json` prevents reevaluation. Interrupted runs can resume after verifying identical locks/sources, reusing completed policy summaries. This is not a way to change a policy after seeing results. **For report-only regeneration, run the last two commands only.** After rerunning `compare-arms`, use `report-policy` to reattach stage 4.

| Output | Purpose |
| --- | --- |
| `artifacts/runs/policy-v0.1/models.joblib` | Locally fitted models; Git-excluded |
| `artifacts/runs/policy-v0.1/policy.lock.json` | Policy/code/config/source lock with local paths; Git-excluded |
| `artifacts/runs/policy-v0.1/selected_customer_actions.jsonl` | Customer actions; Git-excluded |
| `artifacts/runs/policy-v0.1/{train,validation,final_test}` | Time-separated, independently namespaced marts; Git-excluded |
| `report/data/policy.json` | Public aggregates/lock evidence without customer IDs or local paths |
| `report/assets/figures/policy_*` | Five selection/value/allocation/side-effect/package charts |

The environment adds scikit-learn 1.9.1 and joblib 1.6.0. Only load locally generated model files after hash verification. Python 3.10 checks core standard-library compatibility; the full locked analysis environment is Python 3.14.3.

## 11. Final PDF

The [print PDF](../output/pdf/CRM_FINAL_REPORT.pdf) includes all 13 report sections, 17 tables, and 14 charts, with a cover, clickable contents, page numbers, and vector charts sized for print. Page count is recorded in the current release validation. Hover and legend toggling remain HTML-only.

`scripts/render_pdf.cjs` verifies HTML/aggregate hashes and generates PDF without fitting or reevaluation. It requires Node.js, Playwright, and Chrome/Chromium; the recorded local execution used the bundled Codex runtime.

```powershell
# Point to the node_modules directory containing Playwright.
$env:NODE_PATH = 'PATH_TO_NODE_MODULES'
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node scripts/render_pdf.cjs
```

PDF: `output/pdf/CRM_FINAL_REPORT.pdf`; hashes: adjacent `PDF_MANIFEST.json`; intermediate print HTML/SVG: Git-excluded `tmp/pdfs/`; layout: `report/pdf.css`. Use `pdfinfo` and `pdftoppm` to inspect every page for text, tables, charts, and pagination.

## 12. Rebuild the final report from public aggregates

A fresh checkout can rebuild the final report without customer-level sources or fitted models. Install the Python analysis environment and Quarto, then run:

```powershell
.\.venv\Scripts\python.exe scripts/refresh_report.py --static-svg
.\.venv\Scripts\python.exe scripts/render_report.py --quarto 'YOUR_QUARTO_PATH'
```

`refresh_report.py` verifies four aggregates and the recorded policy-lock digest, then rebuilds 14 charts, Quarto source, and the local Plotly bundle. It does not estimate effects, fit models, or select policies. Original analysis-source hashes are retained; current presentation-code hashes are recorded separately under `presentation_refresh`.

`--static-svg` optionally requires Chrome/Kaleido. Omitting it updates HTML/JSON without generating SVG. When explicitly requested, SVG failure makes this command fail without updating the final manifest. Generate HTML before PDF using section 11. Windows ASCII temporary-path options follow section 8.
