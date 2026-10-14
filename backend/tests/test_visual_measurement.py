"""Known pixels and geometry must produce reproducible facts without inferred compliance."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.visual_measurement import compare_length, find_color_patch, measure_color, measure_distance, scan_color_bands

loader = importlib.util.spec_from_file_location("measure_visual", ROOT / "scripts/measure_visual.py")
cli = importlib.util.module_from_spec(loader)
loader.loader.exec_module(cli)


class VisualMeasurementTests(unittest.TestCase):
    def test_solid_sample_excludes_noise_and_stays_in_the_search_region(self):
        image = Image.new("RGB", (10, 10), "#FFFFFF")
        ImageDraw.Draw(image).rectangle((2, 2, 4, 4), fill="#000000")
        patch = find_color_patch(image, [2, 2, 10, 10], color_hex="#FFFFFF")
        self.assertEqual(patch, [5, 2, 8, 5])
        self.assertTrue(measure_color(image, patch)["uniform_opaque_region"])
        self.assertIsNone(find_color_patch(image, [2, 2, 5, 5], color_hex="#FFFFFF"))
        self.assertIsNone(find_color_patch(image, [0, 0, 2, 2], color_hex="#FFFFFF"))
        with self.assertRaises(ValueError):
            find_color_patch(image, [0, 0, 10, 10], color_hex="#FFFFFF", side_px=True)

    def test_color_counts_preserve_background_and_text_noise(self):
        image = Image.new("RGB", (10, 10), "#FFFFFF")
        image.putpixel((0, 0), (17, 20, 26))
        image.putpixel((1, 0), (250, 250, 250))
        result = measure_color(image, [0, 0, 10, 10], expected_hex="#ffffff")
        self.assertEqual(result["dominant_hex"], "#FFFFFF")
        self.assertEqual(result["comparison"]["matching_pixel_count"], 98)
        self.assertFalse(result["uniform_opaque_region"])
        self.assertFalse(result["comparison"]["all_pixels_match"])
        tolerant = measure_color(image, [0, 0, 10, 10], expected_hex="#ffffff", max_channel_delta=5)
        self.assertEqual(tolerant["comparison"]["matching_pixel_count"], 99)

    def test_transparency_is_not_an_observed_white_background(self):
        image = Image.new("RGBA", (2, 2), (255, 255, 255, 0))
        image.putpixel((0, 0), (255, 255, 255, 128))
        empty = measure_color(image, [0, 0, 2, 2], expected_hex="#FFFFFF")
        self.assertEqual(empty["status"], "no_opaque_pixels")
        self.assertIsNone(empty["dominant_hex"])
        self.assertEqual(empty["comparison"]["matching_pixel_count"], 0)
        image.putpixel((1, 1), (255, 255, 255, 255))
        self.assertEqual(measure_color(image, [0, 0, 2, 2])["dominant_ratio"], 0.25)

    def test_gradient_is_not_averaged_into_a_fictitious_color(self):
        image = Image.new("RGB", (4, 1))
        image.putdata([(0, 0, 0), (40, 40, 40), (80, 80, 80), (120, 120, 120)])
        result = measure_color(image, [0, 0, 4, 1])
        self.assertEqual(result["dominant_ratio"], 0.25)
        self.assertFalse(result["uniform_opaque_region"])
        self.assertNotIn("#3C3C3C", [item["hex"] for item in result["palette"]])

    def test_scan_reports_multiple_background_runs_without_selecting_a_floor(self):
        image = Image.new("RGB", (8, 20), "#000000")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 3, 7, 6), fill="#FFFFFF")
        draw.rectangle((0, 12, 7, 17), fill="#FFFFFF")
        result = scan_color_bands(image, [0, 2, 8, 19], background_hex="#FFFFFF")
        self.assertEqual([(b["bbox_px"], b["length_px"]) for b in result["bands"]],
                         [([0, 3, 8, 7], 4), ([0, 12, 8, 18], 6)])
        self.assertEqual(result["status"], "multiple_candidates")
        self.assertFalse(result["semantic_boundary_verified"])
        self.assertEqual(len(scan_color_bands(image, [0, 0, 8, 20], background_hex="#FFFFFF", min_length_px=5)["bands"]), 1)

    def test_horizontal_scan_and_noise_require_explicit_threshold(self):
        image = Image.new("RGB", (12, 4), "#000000")
        ImageDraw.Draw(image).rectangle((5, 0, 7, 3), fill="#FFFFFF")
        image.putpixel((6, 0), (250, 250, 250))
        strict = scan_color_bands(image, [2, 0, 11, 4], background_hex="#FFFFFF", axis="horizontal")
        self.assertEqual([b["length_px"] for b in strict["bands"]], [1, 1])
        loose = scan_color_bands(image, [2, 0, 11, 4], background_hex="#FFFFFF", axis="horizontal", min_matching_ratio=0.75)
        self.assertEqual(loose["bands"][0]["bbox_px"], [5, 0, 8, 4])
        self.assertEqual(loose["bands"][0]["length_px"], 3)
        self.assertEqual(scan_color_bands(image, [0, 0, 12, 4], background_hex="#FF0000")["status"], "no_band")

    def test_edge_geometry_distinguishes_gap_touch_and_overlap(self):
        image = Image.new("RGB", (100, 100))
        gap = measure_distance(image, [5, 10, 80, 30], [20, 54, 90, 70])
        self.assertEqual(gap["distance_px"], 24)
        self.assertEqual(gap["evidence_bbox_px"], [20, 30, 80, 54])
        self.assertFalse(gap["semantic_boundary_verified"])
        self.assertEqual(measure_distance(image, [5, 10, 80, 30], [20, 30, 90, 70])["relationship"], "touching")
        overlap = measure_distance(image, [5, 10, 80, 80], [20, 30, 90, 50])
        self.assertEqual(overlap["relationship"], "overlap")
        self.assertEqual(overlap["evidence_bbox_px"], [20, 30, 80, 50])
        self.assertEqual(measure_distance(image, [0, 10, 20, 40], [30, 20, 50, 60], axis="horizontal")["distance_px"], 10)
        for first, second in [([0, 30, 10, 40], [0, 0, 10, 10]), ([0, 0, 10, 10], [20, 20, 30, 30])]:
            with self.assertRaises(ValueError):
                measure_distance(image, first, second)

    def test_calibration_and_acceptance_are_not_invented(self):
        self.assertEqual(compare_length(12, expected_design_px=24)["status"], "needs_calibration")
        params = {"expected_design_px": 24, "image_px_per_design_px": 0.5, "calibration_source": "approved 750px design / 375px capture"}
        calibrated = compare_length(12, **params)
        self.assertEqual(calibrated["observed_design_px"], 24)
        self.assertEqual(calibrated["status"], "measured_without_acceptance_tolerance")
        self.assertEqual(compare_length(12, **params, tolerance_design_px=0)["status"], "within_tolerance")
        self.assertEqual(compare_length(14, **params, tolerance_design_px=1)["status"], "outside_tolerance")
        with self.assertRaises(ValueError):
            compare_length(12, expected_design_px=24, image_px_per_design_px=0.5)

    def test_invalid_coordinates_and_thresholds_fail(self):
        image = Image.new("RGB", (10, 10))
        for box in (None, [], [0, 0, 0, 2], [-1, 0, 2, 2], [0, 0, 11, 2], [True, 0, 2, 2], [0.0, 0, 2, 2]):
            with self.subTest(box=box), self.assertRaises(ValueError):
                measure_color(image, box)
        for color in ("white", "#FFF", None):
            with self.assertRaises(ValueError):
                scan_color_bands(image, [0, 0, 10, 10], background_hex=color)
        for value in (0, 1.1, float("nan"), True, "1"):
            with self.assertRaises(ValueError):
                scan_color_bands(image, [0, 0, 10, 10], background_hex="#FFFFFF", min_matching_ratio=value)
        for value in (float("inf"), True, "24"):
            with self.assertRaises(ValueError):
                compare_length(24, expected_design_px=value)

    def test_plan_retains_rule_identity_and_calibration_status(self):
        image = Image.new("RGB", (10, 10), "#FFFFFF")
        item = {"id": "gap", "rule_id": "OV009", "kind": "bands", "params": {"bbox": [0, 0, 10, 10], "background_hex": "#FFFFFF"}, "length_comparison": {"expected_design_px": 24}}
        result = cli.measure_plan(image, {"measurements": [item]})[0]
        self.assertEqual(result["rule_id"], "OV009")
        self.assertEqual(result["measurement"]["bands"][0]["length_comparison"]["status"], "needs_calibration")
        with self.assertRaises(ValueError):
            cli.measure_plan(image, {"measurements": [item, item]})

    def test_capture_identity_requires_hash_and_dimensions(self):
        capture = {"venue": {"venue_id": "venue-1", "project_id": "project-1"},
                   "screens": [{"file": "venues/v1/screen-1.png", "sha256": hashlib.sha256(b"original").hexdigest(), "width": 10, "height": 20}]}
        source = Path("screen-1.png")
        digest = hashlib.sha256(b"original").hexdigest()
        self.assertEqual(cli.capture_identity(capture, source, digest, (10, 20))["venue"]["project_id"], "project-1")
        with self.assertRaises(ValueError):
            cli.capture_identity(capture, source, hashlib.sha256(b"changed").hexdigest(), (10, 20))
        with self.assertRaises(ValueError):
            cli.capture_identity(capture, source, digest, (20, 20))


if __name__ == "__main__":
    unittest.main()
