# GitHub publication preparation

Only `crm-retention-lab` is prepared as an independent Git repository, on branch `codex/report-polish`. Public candidate files are staged. No remote repository, commit, or push has been created.

## Included and excluded files

Include source, configurations, tests, execution guides, selected synthetic samples, aggregate JSON, Quarto source, Plotly charts, final HTML/PDF, and validation manifests. `.gitignore` excludes full generated data, oracle state, customer-level predictions/allocations, fitted models, virtual environments, secret environment files, and rendering scratch files.

`.gitattributes` disables automatic line-ending conversion to preserve bytes used by aggregate, lock, and report hashes across platforms.

## Reading and rebuilding reports

- Download HTML from GitHub and open it locally. Bundled Plotly supports interaction without an external CDN.
- PDF is the static print edition; interaction is available in HTML.
- [Run guide, section 12](RUN_GUIDE.md#12-rebuild-the-final-report-from-public-aggregates) rebuilds the report from public aggregates without full source data or fitted models.
- [Historical editorial validation](../reports/EDITORIAL_VALIDATION.md) records the earlier Korean copy edit. [English release validation](../reports/ENGLISH_RELEASE_VALIDATION.md) records the English edition's checks.

## CI

`.github/workflows/checks.yml` defines Windows/Linux standard-library checks and a locked analysis-environment job. Local tests have run; remote GitHub Actions has not. The referenced [actions/checkout v7](https://github.com/actions/checkout/tree/v7) and [actions/setup-python v7](https://github.com/actions/setup-python/tree/v7) tags were verified through the GitHub API.

## Publication choices still open

Repository URL/name, public/private visibility, and a project license remain undecided. No LICENSE file is present. Check local candidates with `git status --short` and `git diff --cached --stat`. Once those publication choices are specified, add the appropriate files before the first commit, remote connection, and push.
