# Python implementation and GitHub release plan

Status: **diagnosis, three-arm comparison, policy selection, and independent evaluation completed, 2026-11-08**. Implementation and actual analysis execution are distinguished below. See [stage-2 methods](STAGE_2_METHODS.md), [stage-3 results](STAGE_3_RESULTS.md), [stage-4 specification](STAGE_4_POLICY_SPEC.md), and the [integrated report](../reports/CRM_DIAGNOSTIC.html). Independent pilot power, repeated A/A inference validation, and real-market validation remain incomplete.

## 1. Completed and remaining work

- [x] Independent project folder, README, business question, eligibility rules, and message drafts.
- [x] Observed/mart/oracle boundaries, time splits, accounting, policy evaluation, and decisions.
- [x] Versioned design/generator JSON, references, and `.gitignore` for generated/private/large outputs.
- [x] Source-checkout Python package/CLI and dedicated environment.
- [x] 1,000-customer development data, 20-customer public sample, ledger/eligibility/storage validation.
- [x] GitHub Actions workflow passed all five jobs on the initial publication commit.
- [x] Python 3.14.3 environment and lock of installed analysis dependencies.
- [x] Separate 20,000-customer training profile and assignment-time feature/outcome marts.
- [x] Control cohorts, Kaplan–Meier, segment diagnostics, and calculation checks.
- [x] Four diagnostic Plotly charts, SVGs, Quarto HTML, and provenance hashes.
- [x] Three-arm ITT, Welch/Holm, SRM/SMD, settlement reconciliation, side-effect assessment, and five experiment charts.
- [ ] Discrete-time survival model and independent pilot power.
- [x] Ridge/HGB three-arm T-learners, training-only preprocessing, and 11-feature allowlist.
- [x] Daily budget/contact/predicted-risk constraints, validation selection, and policy lock.
- [x] DR/IPW, within-day reallocation bootstrap, side-effect evaluation, and report code.
- [x] HGB λ=0.5 locked before independent final evaluation of 15,363 customers.
- [x] Integrated numerical/visual validation: [stage-4 record](../reports/STAGE_4_VALIDATION.md).
- [x] Local independent Git repository and English public documentation/report preparation.
- [x] Public GitHub repository, initial upload, and remote CI verification on 2026-11-09.
- [ ] Final campaign presentation and license selection.

This project is separate from the parent employment-management application and shares none of its code, database, or dependency files. Relative paths allow this folder alone to become a repository.

## 2. Technology

| Purpose | Choice | Rationale / limits |
| --- | --- | --- |
| Runtime | Windows / Python 3.14.3 | Full analysis; Python 3.10.7 checks dependency-free core compatibility |
| Tables/randomness | Standard library | Generator/marts/diagnostics; customer/process SHA-256 seeds and independent `random.Random` streams |
| Storage | JSONL sources/marts; JSON aggregates/manifests | Preserves types; Parquet not implemented |
| Survival | KM in `diagnostics.py`; lifelines 0.30.3 comparison | Greenwood log-log intervals, censoring, ties; discrete-time model pending |
| Average effects | Welch, Holm, Newcombe | Training ITT comparisons completed |
| Conditional outcomes | scikit-learn Ridge, Logistic, HGB | T-learners; training-only fitting, no post-validation refit |
| Policy evaluation | NumPy IPW/DR and within-batch reallocation bootstrap | Known probabilities, observed outcomes, common HGB adjustment, no final reselection |
| Visualization | Plotly 7.1.0, Kaleido 1.5.0 | Shared aggregates for HTML/JSON/SVG; compatible Chrome/Chromium needed for SVG |
| Report | Quarto 1.11.9 | Narrative HTML from precomputed inputs |
| Validation | unittest, lifelines comparisons, `pip check` | Data/mart/diagnostic/report contracts and dependencies |
| Dependencies | Optional `pyproject.toml` extras and `requirements-analysis.lock.txt` | Generator dependency-free; full lock from Windows / Python 3.14.3 |

The lock includes transitive packages such as pandas, NumPy, and SciPy. A fresh Linux analysis installation and Windows/Linux core checks passed in [remote CI](GITHUB_PREPARATION.md#ci); macOS remains unverified. A dedicated `.venv` leaves the parent app unchanged. Additional causal libraries such as EconML are future options only when a needed estimator justifies them; V1 does not add multiple frameworks or deep learning merely for complexity.

## 3. Implemented structure and future files

```text
crm-retention-lab/
├─ README.md
├─ pyproject.toml                  # Dependency-free core; optional analysis
├─ requirements-analysis.lock.txt  # Python 3.14.3 environment
├─ configs/
│  ├─ design_v0_1.json
│  ├─ smoke_v0_1.json
│  ├─ train_diagnostic_v0_1.json    # 20,000 training customers
│  ├─ validation_policy_v0_1.json
│  ├─ final_policy_v0_1.json        # Generate only after locking
│  ├─ policy_analysis_v0_1.json
│  ├─ generator_v0_1.json
│  └─ scenarios/                   # FUTURE: additional structures/costs/demand
├─ docs/
├─ src/crm_retention_lab/
│  ├─ simulation.py                # Observed sources and oracle generation
│  ├─ contracts.py                 # Keys, types, time, finances
│  ├─ finance.py                   # Prices, ledger, mature profit
│  ├─ eligibility.py               # Pre-assignment eligibility
│  ├─ config.py / schema.py
│  ├─ storage.py                   # JSONL, hashes, oracle separation
│  ├─ marts.py                     # Features, labels, splits, freeze, namespaces
│  ├─ diagnostics.py               # KM, cohorts, Wilson intervals
│  ├─ visuals.py                   # Four diagnostic charts
│  ├─ reporting.py                 # Marts, aggregates, manifest, QMD
│  ├─ survival.py                  # FUTURE: discrete-time model
│  ├─ experiment.py                # Average effects, intervals, side effects
│  ├─ experiment_checks.py         # SRM, SMD, contacts, reconciliation
│  ├─ experiment_visuals.py        # Five experiment charts
│  ├─ experiment_reporting.py
│  ├─ uplift.py                    # Training-only Ridge/HGB T-learners
│  ├─ policy.py                    # Constrained daily allocation
│  ├─ policy_evaluation.py         # IPW, DR, reallocation bootstrap
│  ├─ policy_pipeline.py           # Fitting, selection, lock, final evaluation
│  ├─ policy_visuals.py            # Five policy charts
│  ├─ policy_reporting.py          # Sections 9–12
│  ├─ policy_report.py             # Integrate stored aggregates
│  └─ cli.py
├─ scripts/
│  ├─ run.py
│  ├─ render_report.py
│  ├─ refresh_report.py            # Public-aggregate rebuild without estimation
│  └─ render_pdf.cjs
├─ notebooks/                      # FUTURE: explanation/exploration
├─ tests/
├─ data/
│  ├─ sample/
│  ├─ generated/                   # Git-excluded
│  └─ oracle/                      # Git-excluded; separate validation only
├─ artifacts/runs/                 # Private marts/models/locks/allocations
├─ report/                         # QMD, aggregates, charts, styles
├─ reports/                        # Validation, final HTML, render manifest
├─ output/pdf/                     # Final PDF and manifest
└─ deliverables/                   # FUTURE: campaign proposal/presentation
```

Features/outcomes/splits are implemented in `marts.py`, not nonexistent `features.py` or `outcomes.py`; KM is in `diagnostics.py`, not the future `survival.py`. Keep small functions in modules until scale warrants subpackages. Core computations must not depend on notebook execution order.

## 4. Execution interfaces and provenance

Implemented commands: `generate`, `validate`, `sample`, `test`, `diagnose`, `compare-arms`, `select-policy`, `evaluate-policy`, and `report-policy`.

Diagnostic flow: `generate → validate → diagnose or compare-arms → scripts/render_report.py`.

- `generate` separates observed sources and oracle.
- `validate` rejects key/time/eligibility/cost or hash failures.
- `diagnose` validates sources, builds training marts, and exports cohort/KM/segment aggregates, charts, and QMD. No separate `build-marts` command exists.
- `compare-arms` adds mature full-ITT comparisons, checks, and five experiment charts.
- `scripts/render_report.py` checks QMD/manifest, renders Quarto, copies final HTML, and records hashes.

Policy flow: `select-policy → evaluate-policy --generate-final → report-policy → scripts/render_report.py`.

- `select-policy` fits two training models, screens eight validation candidates, and locks policy/model/config/code hashes. It refuses an existing final path. No separate `fit` command exists.
- `evaluate-policy` verifies locks, generates/validates independent final sources, and evaluates fixed policy/baselines without refitting, reselection, or oracle reads.
- `report-policy` merges saved final aggregates into the diagnostic/experiment report without reevaluation or disclosure of customer predictions/allocations/models.

Source manifests record code/config/source hashes, Python, seeds, schemas, counts, and maturity. Analysis manifests record inputs/marts/aggregates/QMD/environment; render manifests record Quarto/input/final-HTML hashes. Policy locks record selected IDs, models, validation selection, split sources, final profiles, and decision code. No repository commit is invented. Commands are in [RUN_GUIDE.md](RUN_GUIDE.md).

## 5. Milestones and acceptance criteria

| Stage | Deliverable | Evidence / remaining work |
| --- | --- | --- |
| 1. Environment/contracts: complete | Small generator/ledger | 1,000-customer smoke checks; fixed assumptions |
| 2. Training diagnosis: complete | 20,000-customer profile, marts, KM/cohorts, four charts | 15,284 assignments, 5,105 controls; null/censoring/interval checks |
| 3. Average experiment: complete except pilot power | Effects, accounting, multiplicity, side effects | All 15,284 ITT outcomes reconcile; independent pilot pending |
| 4. Policy selection/lock: complete | Baselines, T-learners, allocation | 15,167 validation customers select HGB λ=0.5; hashes locked |
| 5. Independent final evaluation: complete | DR/IPW, intervals, side effects, report | 15,363 final customers; KRW +281.94/customer, interval includes 0; repeated scenarios/A/A calibration pending |
| 6. Publication complete; presentation pending | Proposal, messages, slides, README | Public repository and fresh Linux analysis installation verified; final campaign presentation pending |

Stage 2 used a **training-only profile**, not the full 60,000-customer design: deliveries 2025-01-01–2025-06-16, assignments 2025-01-15–2025-06-30, cutoff 2025-10-01. No validation/final customers were generated then; all 5,105 controls passed 90-day freeze. Policy selection later used an independent validation seed; final generation followed the actual UTC lock.

Record reasons for data/design corrections. If a design changes after test outcomes are opened, do not continue calling that test untouched; use a new independently generated evaluation world.

## 6. Meaningful tests

| Risk | Check | Status |
| --- | --- | --- |
| Duplicate/broken relations | Keys, one assignment/customer, first-order ownership | Implemented |
| Future information | Feature occurrence/availability before assignment; records before label freeze; split maturity | Implemented |
| Late operational logs/unsettled finances | Zero operational delay; availability after occurrence; adjustments within 30 days | Implemented |
| Oracle leakage | Observed-field/feature allowlists and separated storage | Implemented |
| ITT denominator changes | Retain failed/unopened/unsubscribed assignments | Average and policy checks |
| Double-counted coupons | Hand-calculated revenue/cost/refund/send examples | Implemented |
| Recent-customer misclassification | Final labels null before assignment+90; administrative KM censoring | Implemented |
| Survival errors | Ties, no/all events, unreached median, lifelines comparison | Implemented |
| Chart/data mismatch | Shared aggregates and provenance hashes | Implemented |
| Split leakage | Availability, settlement, namespaces, train-only preprocessing, locks | Three-split fixtures and unseen/missing category tests |
| Resource violations | One action/customer, batch budget/contact caps, duplicate resamples | Implemented |
| Estimator errors | Hand-calculated three-arm IPW/DR; constant policy/HT agreement | Implemented |
| Wrong side-effect target | Selected-policy minus no-contact IPW, separate from predicted screening | Implemented |
| False validity | Cost-free A/A null behavior and interval coverage | Generator checks done; repeated inference pending |
| Behavioral effects without profit | Zero behavior plus discount/send costs | Generator checks done; effect evaluation pending |
| Seed/structure sensitivity | Fixed independent seeds plus structural scenarios | Broader sensitivity work pending |

The stage-4 suite had 218 tests: Windows / Python 3.14.3 **214 passed, 4 skipped**; dependency-free Python 3.10.7 **133 passed, 85 skipped**. Optional model/chart tests skip without dependencies. The later [publication CI run](GITHUB_PREPARATION.md#ci) passed all 218 tests on Linux with analysis dependencies. A single A/A p-value below 0.05 is not by itself failure; assess repeated false-positive rates and sampling error. A few sensitivity seeds differ from hundreds of calibration repetitions.

## 7. Portfolio narrative

1. Decision question and synthetic-data disclosure.
2. Fictional business, journey, constraints.
3. Observed problem and magnitude.
4. Customer hypotheses and alternatives.
5. Three-arm design, denominators, windows.
6. Average effects and discount accounting.
7. Purchase-risk versus incremental-profit targeting.
8. Shared-cap policy comparisons and uncertainty.
9. Target, message, benefit, and suppression plan.
10. Scale/modify/hold decision and budget.
11. Failure scenarios, limits, and real-world prerequisites.
12. Reproducible code and references.

Current diagnostics support items 3–4; the average experiment supports item 6. Policy modules connect items 7–8 and 10 to saved validation/final aggregates. Final values come only from post-lock independent evaluation in `report/data/policy.json`, never from claimed real-brand rollout performance.

## 8. Release checklist

- [x] Independent local repository containing this project only.
- [x] Locked Windows / Python 3.14.3 dependencies and local `pip check`.
- [x] Actual installation/core flow in remote GitHub Actions.
- [x] Fresh Linux installation from the documented analysis lock; numerical/chart tests and diagnostic/experiment smoke flows passed.
- [x] Small synthetic sample and generation instructions.
- [x] Exclusion rules for full generated data, models, secrets, and temporary outputs.
- [x] Tables/charts linked to source IDs and aggregate/render hashes.
- [x] Reference scope documented; no reference code/data copied.
- [ ] Select public licenses and add accurate license files.
- [x] English README, public documentation, and report preparation.
- [x] Create/connect the public remote, commit, and publish to `main`.

See [GITHUB_PREPARATION.md](GITHUB_PREPARATION.md) for current release boundaries and CI scope. The final campaign presentation and license selection remain incomplete.
