import copy
import json
from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path

from crm_retention_lab.config import load_config
from crm_retention_lab.schema import TABLE_COLUMNS
from crm_retention_lab.storage import (
    check_output_separation, load_observed, verify_run_hashes, write_run,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def project_temporary_directory():
    # Keep test I/O in the checkout, including on restricted Windows hosts.
    base = (ROOT / ".test-tmp").resolve()
    base.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="storage-", dir=base)
    resolved = Path(temporary.name).resolve()
    if base not in resolved.parents:
        raise RuntimeError("Temporary directory escaped the project test workspace")
    try:
        yield str(resolved)
    finally:
        # The resolved cleanup target was checked before any recursive cleanup.
        temporary.cleanup()


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from crm_retention_lab.contracts import validate_dataset
        from crm_retention_lab.simulation import generate_dataset
        cls.config = load_config(ROOT / "configs/smoke_v0_1.json", customers=40)
        cls.observed, cls.oracle = generate_dataset(cls.config)
        cls.report = validate_dataset(cls.observed, cls.config)
        if not cls.report["valid"]:
            raise AssertionError(cls.report)

    def test_round_trip_preserves_types_and_separates_oracle(self):
        with project_temporary_directory() as temporary:
            root = Path(temporary)
            manifest = write_run(root / "run", self.observed, self.oracle, self.config,
                                 self.report, oracle_output=root / "oracle")
            self.assertEqual(load_observed(root / "run/observed"), self.observed)
            self.assertEqual(verify_run_hashes(root / "run"), self.config)
            self.assertTrue(manifest["oracle"]["written_separately"])
            self.assertEqual(set(p.stem for p in (root / "run/observed").iterdir()), set(TABLE_COLUMNS))

    def test_tampering_and_overwrite_are_rejected(self):
        with project_temporary_directory() as temporary:
            output = Path(temporary) / "run"
            write_run(output, self.observed, self.oracle, self.config, self.report)
            with self.assertRaisesRegex(ValueError, "not empty"):
                write_run(output, self.observed, self.oracle, self.config, self.report)
            with (output / "observed/customers.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_run_hashes(output)

    def test_config_tampering_is_rejected(self):
        with project_temporary_directory() as temporary:
            output = Path(temporary) / "run"
            write_run(output, self.observed, self.oracle, self.config, self.report)
            altered = copy.deepcopy(self.config)
            altered["reproducibility"]["base_seed"] += 1
            (output / "config.snapshot.json").write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot hash mismatch"):
                verify_run_hashes(output)

    def test_oracle_file_in_observed_folder_is_rejected(self):
        with project_temporary_directory() as temporary:
            output = Path(temporary) / "run"
            write_run(output, self.observed, self.oracle, self.config, self.report)
            (output / "observed/oracle.jsonl").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "allowlist"):
                load_observed(output / "observed")

    def test_outputs_cannot_nest(self):
        with project_temporary_directory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "non-nested"):
                check_output_separation(root / "run", root / "run/oracle")
            with self.assertRaisesRegex(ValueError, "non-nested"):
                check_output_separation(root / "run/observed", root / "run")


if __name__ == "__main__":
    unittest.main()
