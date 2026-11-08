"""Run from a source checkout without installing third-party packages."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crm_retention_lab.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
