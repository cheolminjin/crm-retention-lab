"""Protect immutable source data and the private/public artifact boundary."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crm_retention_lab.reporting import run_diagnosis


HAS_PLOTLY = importlib.util.find_spec("plotly") is not None
ROOT = Path(__file__).resolve().parents[1]


def project_temporary_directory():
    # Keep fixture writes and recursive cleanup inside the permitted checkout.
    base = (ROOT / ".test-tmp").resolve()
    base.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="reporting-", dir=base)
    if base not in Path(temporary.name).resolve().parents:
        raise RuntimeError("Temporary report escaped the project test workspace")
    return temporary


class ReportingGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = project_temporary_directory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "raw"
        self.target = self.root / "private"
        self.report = self.root / "public"
        self.source.mkdir()
        (self.source / "sentinel.txt").write_text("immutable raw bytes", encoding="utf-8")

    def assert_rejected_before_read(self, target, report):
        with patch("crm_retention_lab.reporting.verify_run_hashes") as verify:
            with self.assertRaises(ValueError):
                run_diagnosis(self.source, target, report)
            verify.assert_not_called()
        self.assertEqual((self.source / "sentinel.txt").read_text(encoding="utf-8"), "immutable raw bytes")

    def test_rejects_source_overlap_in_both_directions_before_reading(self):
        for target, report in (
            (self.source, self.report),
            (self.source / "marts", self.report),
            (self.root, self.report),
            (self.target, self.source),
            (self.target, self.source / "report"),
            (self.target, self.root),
        ):
            with self.subTest(target=target, report=report):
                self.assert_rejected_before_read(target, report)

    def test_rejects_private_public_same_or_nested_directories(self):
        for target, report in (
            (self.target, self.target),
            (self.target, self.target / "public"),
            (self.report / "private", self.report),
        ):
            with self.subTest(target=target, report=report):
                self.assert_rejected_before_read(target, report)

    def test_nonempty_private_output_is_never_overwritten(self):
        self.target.mkdir()
        sentinel = self.target / "features.jsonl"
        sentinel.write_text("existing private data", encoding="utf-8")
        self.assert_rejected_before_read(self.target, self.report)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing private data")
        self.assertFalse(self.report.exists())

    def test_source_hash_failure_creates_no_outputs(self):
        with patch("crm_retention_lab.reporting.verify_run_hashes", side_effect=ValueError("hash mismatch")):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                run_diagnosis(self.source, self.target, self.report)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.report.exists())

    def test_invalid_observed_data_creates_no_outputs(self):
        with patch("crm_retention_lab.reporting.verify_run_hashes", return_value={}), \
                patch("crm_retention_lab.reporting.load_observed", return_value={}), \
                patch("crm_retention_lab.reporting.validate_dataset", return_value={"valid": False, "errors": ["bad foreign key"]}):
            with self.assertRaisesRegex(ValueError, "Input validation failed"):
                run_diagnosis(self.source, self.target, self.report)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.report.exists())

    def test_resolved_public_file_escape_is_rejected_without_symlink_privileges(self):
        original_resolve = Path.resolve
        for relative, escaped in (
            ("data/diagnostics.json", self.source / "sentinel.txt"),
            ("assets/figures/pack_km.html", self.target / "features.jsonl"),
        ):
            public_file = self.report / relative

            def resolve(path, *args, **kwargs):
                if path == public_file:
                    return original_resolve(escaped, *args, **kwargs)
                return original_resolve(path, *args, **kwargs)

            with self.subTest(relative=relative), patch.object(Path, "resolve", resolve):
                self.assert_rejected_before_read(self.target, self.report)

    def symlink_or_skip(self, link, destination, directory=False):
        try:
            link.symlink_to(destination, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"This system does not permit test symlinks: {error}")

    def test_public_data_symlink_cannot_expose_private_marts(self):
        self.report.mkdir()
        self.target.mkdir()
        self.symlink_or_skip(self.report / "data", self.target, directory=True)
        self.assert_rejected_before_read(self.target, self.report)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_public_figure_directory_symlink_cannot_write_into_raw_run(self):
        (self.report / "assets").mkdir(parents=True)
        self.symlink_or_skip(self.report / "assets" / "figures", self.source, directory=True)
        self.assert_rejected_before_read(self.target, self.report)

    def test_generated_report_leaf_symlink_cannot_overwrite_raw_file(self):
        (self.report / "data").mkdir(parents=True)
        self.symlink_or_skip(self.report / "data" / "diagnostics.json", self.source / "sentinel.txt")
        self.assert_rejected_before_read(self.target, self.report)

    def test_generated_report_hardlink_cannot_overwrite_raw_file(self):
        (self.report / "data").mkdir(parents=True)
        try:
            (self.report / "data" / "diagnostics.json").hardlink_to(self.source / "sentinel.txt")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"This filesystem does not support test hardlinks: {error}")
        self.assert_rejected_before_read(self.target, self.report)

    def test_shared_output_inode_is_rejected_without_hardlink_privileges(self):
        (self.report / "data").mkdir(parents=True)
        shared_file = self.report / "data" / "diagnostics.json"
        shared_file.write_text("shared bytes", encoding="utf-8")
        original_stat = Path.stat

        def stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == shared_file:
                fields = list(result)
                fields[3] = 2  # st_nlink: the same inode is linked elsewhere.
                return os.stat_result(fields)
            return result

        with patch.object(Path, "stat", stat):
            self.assert_rejected_before_read(self.target, self.report)
        self.assertEqual(shared_file.read_text(encoding="utf-8"), "shared bytes")


@unittest.skipUnless(HAS_PLOTLY, "Report export integration needs optional Plotly")
class ReportingArtifactTests(unittest.TestCase):
    def test_export_preserves_raw_hashes_and_publishes_aggregate_data_only(self):
        from crm_retention_lab.config import load_config
        from crm_retention_lab.contracts import validate_dataset
        from crm_retention_lab.simulation import generate_dataset
        from crm_retention_lab.storage import file_hash, write_run

        project = Path(__file__).resolve().parents[1]
        config = load_config(project / "configs/smoke_v0_1.json", customers=30, seed=1307)
        observed, oracle = generate_dataset(config)
        validation = validate_dataset(observed, config)
        self.assertTrue(validation["valid"])
        with project_temporary_directory() as directory:
            root = Path(directory)
            source, private, public = root / "raw", root / "private", root / "public"
            write_run(source, observed, oracle, config, validation)
            before = {path.relative_to(source).as_posix(): file_hash(path) for path in source.rglob("*") if path.is_file()}
            run_diagnosis(source, private, public)
            after = {path.relative_to(source).as_posix(): file_hash(path) for path in source.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            self.assertTrue((private / "features.jsonl").is_file())
            self.assertTrue((private / "outcomes.jsonl").is_file())
            self.assertFalse(any(path.name in {"features.jsonl", "outcomes.jsonl", "latent_customers.jsonl"} for path in public.rglob("*")))
            customer_ids = {row["customer_id"] for row in observed["customers"]}
            for path in public.rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    self.assertFalse(any(customer_id in text for customer_id in customer_ids), path.name)


if __name__ == "__main__":
    unittest.main()
