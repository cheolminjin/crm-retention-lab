"""End-to-end experiment export and all-ITT readiness guards."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from crm_retention_lab.config import load_config
from crm_retention_lab.contracts import validate_dataset
from crm_retention_lab.diagnostics import summarize_diagnostics
from crm_retention_lab.marts import build_marts
from crm_retention_lab.reporting import run_diagnosis
from crm_retention_lab.simulation import generate_dataset
from crm_retention_lab.storage import file_hash, write_run


ROOT = Path(__file__).resolve().parents[1]
HAS_ANALYSIS = all(importlib.util.find_spec(name) is not None for name in ("scipy", "plotly"))


@unittest.skipUnless(HAS_ANALYSIS, "Three-arm report integration requires analysis dependencies")
class ComparePipelineTests(unittest.TestCase):
    def setUp(self):
        base = (ROOT / ".test-tmp").resolve()
        base.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="compare-", dir=base)
        self.root = Path(self.temporary.name)
        if base not in self.root.resolve().parents:
            raise RuntimeError("Temporary comparison run escaped the checkout")
        self.addCleanup(self.temporary.cleanup)

    def raw(self, profile):
        config = load_config(ROOT / "configs" / profile, customers=120, seed=3206)
        observed, oracle = generate_dataset(config)
        validation = validate_dataset(observed, config)
        self.assertTrue(validation["valid"])
        path = self.root / "raw"
        write_run(path, observed, oracle, config, validation)
        return path, observed, config

    def test_full_comparison_keeps_prior_diagnosis_and_raw_run_unchanged(self):
        source, observed, config = self.raw("train_diagnostic_v0_1.json")
        original = {str(path.relative_to(source)): file_hash(path) for path in source.rglob("*") if path.is_file()}
        baseline = summarize_diagnostics(build_marts(observed, config), config)
        report = self.root / "public"
        result = run_diagnosis(source, self.root / "private", report, include_experiment=True)
        self.assertEqual(result["experiment_status"], "ready")
        self.assertEqual(json.loads((report / "data/diagnostics.json").read_text(encoding="utf-8")), baseline)
        self.assertEqual({str(path.relative_to(source)): file_hash(path) for path in source.rglob("*") if path.is_file()}, original)
        figures = list((report / "assets/figures").glob("*.json"))
        self.assertEqual(len(figures), 9)
        checks = json.loads((report / "data/experiment_checks.json").read_text(encoding="utf-8"))
        self.assertEqual(checks["finance_reconciliation"]["status"], "passed")
        experiment = json.loads((report / "data/experiment.json").read_text(encoding="utf-8"))
        self.assertEqual(experiment["population"]["total_assigned"], baseline["summary"]["train_assigned_customers"])
        self.assertEqual(len(experiment["primary_comparisons"]), 3)
        self.assertEqual(len(experiment["guardrails"]), 4)
        public = "\n".join(path.read_text(encoding="utf-8") for path in (report / "data").glob("*.json"))
        self.assertFalse(any(row["customer_id"] in public for row in observed["customers"]))

    def test_immature_itt_run_preserves_existing_report_and_creates_no_marts(self):
        source, _, _ = self.raw("smoke_v0_1.json")
        report = self.root / "public"
        report.mkdir()
        sentinel = report / "index.qmd"
        sentinel.write_text("existing reviewed report", encoding="utf-8")
        target = self.root / "private"
        with self.assertRaisesRegex(ValueError, "All training assignments"):
            run_diagnosis(source, target, report, include_experiment=True)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing reviewed report")
        self.assertFalse(target.exists())
        self.assertEqual(list(report.iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main()
