"""Check plotted denominators, missingness, intervals, and offline exports."""

import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crm_retention_lab.diagnostics import kaplan_meier_curve

HAS_PLOTLY = importlib.util.find_spec("plotly") is not None
if HAS_PLOTLY:
    from crm_retention_lab.visuals import FIGURE_IDS, create_figures, export_figures

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _temporary_directory():
    base = (ROOT / ".test-tmp").resolve()
    base.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="visuals-", dir=base)
    resolved = Path(temporary.name).resolve()
    if base not in resolved.parents:
        raise RuntimeError("Temporary export escaped the project test workspace")
    try:
        yield str(resolved)
    finally:
        temporary.cleanup()


def _diagnostic_fixture():
    curves = []
    for grams in (200, 500, 1000):
        curve = kaplan_meier_curve([3, 7, 10], [True, False, True])
        curves.append({**curve, "group": f"{grams}g", "first_pack_grams": grams})
    return {
        "metadata": {"input_simulation_id": "sim-test", "snapshot_id": "snapshot-test",
                     "as_of": "2025-06-01T00:00:00+09:00", "analysis_scope": "train"},
        "eligibility_flow": {"first_delivery_customers": 20, "d14_reached": 17,
                             "d14_pending": 3, "eligible": 12, "ineligible": 5,
                             "assigned_total": 12, "exclusion_reasons_overlap": True},
        "cohorts": [
            {"assigned_month": "2025-01", "n_control": 10, "is_fully_mature": True,
             "cells": [{"day": day, "n": 10, "events": 2, "rate": 0.2,
                        "ci_lower": 0.05, "ci_upper": 0.51, "is_mature": True} for day in (7, 14, 30, 60)]},
            {"assigned_month": "2025-05", "n_control": 5, "is_fully_mature": False,
             "cells": [{"day": day, "n": 0, "events": 0, "rate": None,
                        "ci_lower": None, "ci_upper": None, "is_mature": False} for day in (7, 14, 30, 60)]},
        ],
        "km_curves": curves,
        "segments": [{"feature": "first_pack_grams", "value": grams, "label": f"{grams}g",
                      "n_eligible_control": 12, "n_mature": 10, "events": 4,
                      "rate": 0.4, "ci_lower": 0.17, "ci_upper": 0.69} for grams in (200, 500, 1000)],
    }


@unittest.skipUnless(HAS_PLOTLY, "Install the report extra to run Plotly tests")
class VisualTests(unittest.TestCase):
    def test_four_figures_use_same_snapshot_and_do_not_modify_diagnostics(self):
        data = _diagnostic_fixture()
        before = copy.deepcopy(data)
        figures = create_figures(data)
        self.assertEqual(tuple(figures), FIGURE_IDS)
        self.assertEqual(data, before)
        for figure in figures.values():
            self.assertTrue(figure.layout.meta["synthetic"])
            self.assertEqual(figure.layout.meta["snapshot_id"], "snapshot-test")
            captions = " ".join(annotation.text for annotation in figure.layout.annotations)
            self.assertIn("2025-06-01", captions)
            self.assertIn("snapshot-test", captions)

    def test_eligibility_flow_preserves_customer_counts_and_scope(self):
        figure = create_figures(_diagnostic_fixture())["eligibility_flow"]
        self.assertEqual(list(figure.data[0].x), [20, 17, 12, 12])
        self.assertAlmostEqual(figure.data[0].customdata[2][0], 12 / 20)
        self.assertTrue(any("distinct from a churn rate" in annotation.text for annotation in figure.layout.annotations))

    def test_immature_cohort_cells_remain_missing_even_if_input_contains_rate(self):
        data = _diagnostic_fixture()
        data["cohorts"][1]["cells"][0]["rate"] = 0.9
        figure = create_figures(data)["cohort_heatmap"]
        heatmap = figure.data[0]
        self.assertEqual(list(heatmap.z[0]), [0.2] * 4)
        self.assertEqual(list(heatmap.z[1]), [None] * 4)
        self.assertEqual(list(figure.data[1].text), ["NA"] * 4)
        self.assertEqual(heatmap.customdata[0][0][:2], [10, 2])
        self.assertEqual(heatmap.zmin, 0)
        self.assertEqual(heatmap.zmax, 1)

    def test_km_uses_cumulative_repurchase_intervals_and_at_risk_without_extrapolation(self):
        data = _diagnostic_fixture()
        figure = create_figures(data)["pack_km"]
        line = next(trace for trace in figure.data if trace.name and trace.name.startswith("200g"))
        expected = data["km_curves"][0]["points"]
        self.assertEqual(list(line.y), [point["cumulative_repurchase"] for point in expected])
        self.assertEqual(line.customdata[0][0], 3)
        self.assertAlmostEqual(line.y[list(line.x).index(3)], 1 / 3)
        self.assertIsNone(line.y[-1], "curve must not extend beyond the observed support")
        self.assertFalse(line.connectgaps)
        self.assertEqual(line.line.shape, "hv")
        self.assertEqual(list(figure.data[0].y), [point["cumulative_repurchase_ci_lower"] for point in expected])
        self.assertEqual(list(figure.data[1].y), [point["cumulative_repurchase_ci_upper"] for point in expected])
        self.assertTrue(any(trace.marker.symbol == "line-ns" for trace in figure.data if trace.mode == "markers"))

    def test_segment_plot_uses_mature_denominator_and_asymmetric_intervals(self):
        figure = create_figures(_diagnostic_fixture())["pack_repeat_60d"]
        point = figure.data[0]
        self.assertEqual(list(point.x), [0.4])
        self.assertIn("n=10", point.y[0])
        self.assertAlmostEqual(point.error_x.array[0], 0.69 - 0.4)
        self.assertAlmostEqual(point.error_x.arrayminus[0], 0.4 - 0.17)
        self.assertEqual(point.customdata[0][1:3], [10, 12])

    def test_empty_populations_and_missing_segments_do_not_become_zero_rates(self):
        data = _diagnostic_fixture()
        data["cohorts"] = []
        data["km_curves"] = []
        for segment in data["segments"]:
            segment.update(n_mature=0, events=0, rate=None, ci_lower=None, ci_upper=None)
        figures = create_figures(data)
        self.assertFalse(figures["cohort_heatmap"].data)
        self.assertFalse(figures["pack_km"].data)
        self.assertTrue(all(list(trace.text) == ["NA"] for trace in figures["pack_repeat_60d"].data))

    def test_final_holdout_cannot_be_passed_to_planning_visuals(self):
        data = _diagnostic_fixture()
        data["metadata"]["analysis_scope"] = "final_holdout"
        with self.assertRaisesRegex(ValueError, "train"):
            create_figures(data)

    def test_fragments_and_json_are_deterministic_and_reference_no_cdn(self):
        figure = create_figures(_diagnostic_fixture())["eligibility_flow"]
        with _temporary_directory() as directory:
            metadata = export_figures({"eligibility_flow": figure}, directory)
            paths = metadata["figures"]["eligibility_flow"]
            html = Path(paths["html"]).read_text(encoding="utf-8")
            serialized = Path(paths["json"]).read_text(encoding="utf-8")
            self.assertIn('id="crm-eligibility_flow"', html)
            self.assertNotIn("<html>", html)
            self.assertNotIn('src="https://', html)
            self.assertIn('"responsive": true', html)
            self.assertEqual(json.loads(serialized)["data"][0]["x"], [20, 17, 12, 12])
            self.assertEqual(metadata["static_svg"]["status"], "not_requested")
            export_figures({"eligibility_flow": figure}, directory)
            self.assertEqual(Path(paths["html"]).read_text(encoding="utf-8"), html)
            self.assertEqual(Path(paths["json"]).read_text(encoding="utf-8"), serialized)

    def test_standalone_html_embeds_local_plotly_bundle(self):
        figure = create_figures(_diagnostic_fixture())["eligibility_flow"]
        with _temporary_directory() as directory:
            metadata = export_figures({"eligibility_flow": figure}, directory, standalone=True)
            path = metadata["figures"]["eligibility_flow"]["standalone_html"]
            html = Path(path).read_text(encoding="utf-8")
            self.assertIn("<html>", html)
            self.assertIn("plotly.js", html)
            self.assertNotIn('src="https://cdn.plot.ly/', html)
            self.assertGreater(len(html), 1_000_000)

    def test_static_renderer_is_optional_and_failure_reason_is_reported(self):
        figure = create_figures(_diagnostic_fixture())["eligibility_flow"]
        with _temporary_directory() as directory, patch("crm_retention_lab.visuals.importlib.util.find_spec", return_value=None):
            metadata = export_figures({"eligibility_flow": figure}, directory, static_svg=True)
            self.assertEqual(metadata["static_svg"]["status"], "unavailable")
            self.assertIn("Kaleido", metadata["static_svg"]["errors"][0])
            paths = metadata["figures"]["eligibility_flow"]
            self.assertIsNone(paths["svg"])
            self.assertTrue(Path(paths["html"]).is_file())
            self.assertTrue(Path(paths["json"]).is_file())

    def test_export_rejects_path_traversal_before_creating_output(self):
        figure = create_figures(_diagnostic_fixture())["eligibility_flow"]
        with _temporary_directory() as directory:
            with self.assertRaises(ValueError):
                export_figures({"../outside": figure}, Path(directory) / "not-created")
            self.assertFalse((Path(directory) / "not-created").exists())


if __name__ == "__main__":
    unittest.main()
