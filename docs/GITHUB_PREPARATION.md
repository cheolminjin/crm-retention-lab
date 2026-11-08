# GitHub publication

Published on **2026-11-09 (Asia/Seoul)** as the public repository [cheolminjin/crm-retention-lab](https://github.com/cheolminjin/crm-retention-lab), with default branch `main`. Only this independent project repository was uploaded. The local branch `codex/report-polish` tracks `origin/main`.

The initial commit is [`526cece163ec918ff68f795de2b829ba2b0558ba`](https://github.com/cheolminjin/crm-retention-lab/commit/526cece163ec918ff68f795de2b829ba2b0558ba). All **156 published file paths, Git blob hashes, and file modes** matched the local commit when checked against GitHub's recursive tree response; the response was not truncated.

## Included and excluded files

The repository includes source, configurations, tests, execution guides, selected synthetic samples, aggregate JSON, Quarto source, Plotly charts, final HTML/PDF, and validation manifests. `.gitignore` excludes full generated data, oracle state, customer-level predictions/allocations, fitted models, virtual environments, secret environment files, and rendering scratch files.

`.gitattributes` disables automatic line-ending conversion to preserve bytes used by aggregate, lock, and report hashes across platforms.

## Reading and rebuilding reports

- Download HTML from GitHub and open it locally. Bundled Plotly supports interaction without an external CDN.
- PDF is the static print edition; interaction is available in HTML.
- [Run guide, section 12](RUN_GUIDE.md#12-rebuild-the-final-report-from-public-aggregates) rebuilds the report from public aggregates without full source data or fitted models.
- [Historical editorial validation](../reports/EDITORIAL_VALIDATION.md) records the earlier Korean copy edit. [English release validation](../reports/ENGLISH_RELEASE_VALIDATION.md) records the English edition's checks.

## CI

The [initial GitHub Actions run](https://github.com/cheolminjin/crm-retention-lab/actions/runs/42496278666) passed all five jobs for the initial commit:

- Core checks on Windows and Linux, each with Python 3.10 and 3.14: unit/integration tests, smoke-data generation, and saved-data/hash validation.
- Analysis on Linux / Python 3.14.10: fresh installation from `requirements-analysis.lock.txt`, **218 tests passed with no skips**, diagnostic data/chart export, and a three-arm comparison using a 600-customer smoke run.

The workflow is `.github/workflows/checks.yml`. It does not repeat the full final policy fit/selection/evaluation or Quarto/PDF rendering. Those results retain their separate local validation records. The [English release validation](../reports/ENGLISH_RELEASE_VALIDATION.md) and its JSON manifest describe the earlier pre-publication checkpoint; their README hash predates the publication links and CI badge.

## License and deployment

A project license remains undecided; no LICENSE file is present. GitHub Pages is not deployed. Publication does not send campaign messages.
