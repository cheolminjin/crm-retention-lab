# Public synthetic sample

`smoke-v0.1/` contains 20 synthetic customers for inspecting schemas and relationships. It contains no real customer/company data and cannot support effect estimation or performance claims.

- [Run manifest](smoke-v0.1/manifest.json): purpose, seed, runtime, file hashes, and row counts.
- [Configuration snapshot](smoke-v0.1/config.snapshot.json): complete generation assumptions.
- [Validation results](smoke-v0.1/validation.json): contract checks.
- `smoke-v0.1/observed/`: 8 related observed tables in JSONL format.

Oracle files are excluded. Customer/order IDs belong to a fictional system; real names and contact details are not generated. See the [run guide](../../docs/RUN_GUIDE.md) for sample-generation commands.
