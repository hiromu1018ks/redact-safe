"""
Unit tests for bbox_normalizer.py
"""

import sys
import os
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bbox_normalizer import (
    normalize_bboxes,
    _convert_bboxes_to_pdf_points,
    _group_and_merge_lines,
    _is_same_line,
    _merge_group,
    _apply_rotation,
)


class TestConvertBboxesToPdfPoints(unittest.TestCase):
    """Tests for pixel-to-PDF-point coordinate conversion."""

    def test_single_region_conversion(self):
        """A single region's bbox_px should be converted to bbox_pt."""
        regions = [
            {"bbox_px": [100.0, 200.0, 50.0, 20.0], "text": "hello"},
        ]
        result = _convert_bboxes_to_pdf_points(regions, dpi=300.0)
        self.assertEqual(len(result), 1)

        bbox_pt = result[0]["bbox_pt"]
        # 300dpi: 1px = 72/300 pt = 0.24pt
        self.assertAlmostEqual(bbox_pt[0], 24.0, places=1)  # 100 * 0.24
        self.assertAlmostEqual(bbox_pt[1], 48.0, places=1)  # 200 * 0.24
        self.assertAlmostEqual(bbox_pt[2], 12.0, places=1)  # 50 * 0.24
        self.assertAlmostEqual(bbox_pt[3], 4.8, places=1)   # 20 * 0.24
        self.assertEqual(result[0]["text"], "hello")

    def test_empty_regions(self):
        """Empty input should return empty list."""
        result = _convert_bboxes_to_pdf_points([], dpi=300.0)
        self.assertEqual(result, [])

    def test_region_without_bbox_skipped(self):
        """Regions without bbox_px should be skipped."""
        regions = [
            {"text": "no bbox here"},
            {"bbox_px": [100.0, 200.0, 50.0, 20.0]},
        ]
        result = _convert_bboxes_to_pdf_points(regions, dpi=300.0)
        self.assertEqual(len(result), 1)

    def test_different_dpi(self):
        """Conversion should respect the DPI parameter."""
        regions = [
            {"bbox_px": [72.0, 72.0, 72.0, 72.0]},
        ]
        # At 72dpi: 1px = 1pt, so bbox should be [72, 72, 72, 72]
        result = _convert_bboxes_to_pdf_points(regions, dpi=72.0)
        bbox = result[0]["bbox_pt"]
        self.assertAlmostEqual(bbox[0], 72.0, places=1)
        self.assertAlmostEqual(bbox[1], 72.0, places=1)
        self.assertAlmostEqual(bbox[2], 72.0, places=1)
        self.assertAlmostEqual(bbox[3], 72.0, places=1)


class TestIsSameLine(unittest.TestCase):
    """Tests for same-line detection."""

    def test_overlapping_bboxes_same_line(self):
        """Two bboxes with vertical overlap should be on the same line."""
        a = {"x_left": 0, "x_right": 100, "y_top": 10, "y_bottom": 30, "height": 20}
        b = {"x_left": 110, "x_right": 200, "y_top": 15, "y_bottom": 35, "height": 20}
        self.assertTrue(_is_same_line(a, b, 0.5))

    def test_non_overlapping_close_bboxes_same_line(self):
        """Bboxes close vertically (within threshold) should be on same line."""
        a = {"x_left": 0, "x_right": 100, "y_top": 10, "y_bottom": 30, "height": 20}
        b = {"x_left": 110, "x_right": 200, "y_top": 35, "y_bottom": 55, "height": 20}
        # gap = 35 - 30 = 5, threshold = 20 * 0.5 = 10
        self.assertTrue(_is_same_line(a, b, 0.5))

    def test_far_apart_bboxes_different_line(self):
        """Bboxes far apart vertically should be on different lines."""
        a = {"x_left": 0, "x_right": 100, "y_top": 10, "y_bottom": 30, "height": 20}
        b = {"x_left": 110, "x_right": 200, "y_top": 50, "y_bottom": 70, "height": 20}
        # gap = 50 - 30 = 20, threshold = 20 * 0.5 = 10
        self.assertFalse(_is_same_line(a, b, 0.5))

    def test_contained_bbox_same_line(self):
        """A bbox fully contained within another's vertical range."""
        a = {"x_left": 0, "x_right": 100, "y_top": 10, "y_bottom": 40, "height": 30}
        b = {"x_left": 110, "x_right": 200, "y_top": 15, "y_bottom": 25, "height": 10}
        self.assertTrue(_is_same_line(a, b, 0.5))

    def test_different_heights(self):
        """Different heights should use max height for threshold."""
        a = {"x_left": 0, "x_right": 100, "y_top": 10, "y_bottom": 30, "height": 20}
        b = {"x_left": 110, "x_right": 200, "y_top": 31, "y_bottom": 71, "height": 40}
        # gap = 31 - 30 = 1, threshold = 40 * 0.5 = 20
        self.assertTrue(_is_same_line(a, b, 0.5))


class TestGroupAndMergeLines(unittest.TestCase):
    """Tests for line grouping and merging."""

    def test_two_adjacent_on_same_line(self):
        """Two horizontally adjacent bboxes on the same line should be merged."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 50.0, 10.0], "text": "hello", "confidence": 0.95, "engine": "paddleocr"},
            {"bbox_pt": [65.0, 22.0, 40.0, 8.0], "text": "world", "confidence": 0.90, "engine": "paddleocr"},
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(len(result), 1)

        merged = result[0]
        # bbox should span from min x to max x, min y to max y
        self.assertEqual(merged["bbox_pt"][0], 10.0)   # x
        self.assertEqual(merged["bbox_pt"][1], 20.0)   # y
        self.assertEqual(merged["bbox_pt"][2], 95.0)   # width (65+40 - 10)
        self.assertEqual(merged["bbox_pt"][3], 10.0)   # height (30 - 20)
        self.assertEqual(merged["text"], "helloworld")
        self.assertEqual(merged["merged_count"], 2)
        self.assertAlmostEqual(merged["confidence"], 0.925, places=3)

    def test_two_lines_not_merged(self):
        """Bboxes on different lines should not be merged."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 50.0, 10.0], "text": "line1"},
            {"bbox_pt": [10.0, 100.0, 50.0, 10.0], "text": "line2"},
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(len(result), 2)

    def test_single_region_unchanged(self):
        """A single region should pass through unchanged."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 50.0, 10.0], "text": "solo"},
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "solo")

    def test_empty_regions(self):
        """Empty input should return empty list."""
        result = _group_and_merge_lines([], threshold=0.5)
        self.assertEqual(result, [])

    def test_three_on_same_line(self):
        """Three bboxes on the same line should be merged into one."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 30.0, 10.0], "text": "A"},
            {"bbox_pt": [45.0, 22.0, 30.0, 8.0], "text": "B"},
            {"bbox_pt": [80.0, 20.0, 30.0, 10.0], "text": "C"},
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "ABC")
        self.assertEqual(result[0]["merged_count"], 3)

    def test_mixed_lines(self):
        """Multiple lines with varying numbers of regions."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 30.0, 10.0], "text": "A1"},
            {"bbox_pt": [45.0, 22.0, 30.0, 8.0], "text": "A2"},   # same line as A1
            {"bbox_pt": [10.0, 80.0, 30.0, 10.0], "text": "B1"},
            {"bbox_pt": [10.0, 140.0, 30.0, 10.0], "text": "C1"},
            {"bbox_pt": [45.0, 142.0, 30.0, 8.0], "text": "C2"},   # same line as C1
            {"bbox_pt": [80.0, 141.0, 30.0, 9.0], "text": "C3"},   # same line as C1
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["text"], "A1A2")
        self.assertEqual(result[1]["text"], "B1")
        self.assertEqual(result[2]["text"], "C1C2C3")

    def test_merge_preserves_most_common_engine(self):
        """Merged region should report the most common engine."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 30.0, 10.0], "text": "A", "engine": "paddleocr"},
            {"bbox_pt": [45.0, 22.0, 30.0, 8.0], "text": "B", "engine": "paddleocr"},
            {"bbox_pt": [80.0, 20.0, 30.0, 10.0], "text": "C", "engine": "tesseract"},
        ]
        result = _group_and_merge_lines(regions, threshold=0.5)
        self.assertEqual(result[0]["engine"], "paddleocr")


class TestApplyRotation(unittest.TestCase):
    """Tests for rotation correction."""

    def test_no_rotation(self):
        """Rotation 0 should leave bboxes unchanged."""
        regions = [
            {"bbox_pt": [10.0, 20.0, 50.0, 30.0]},
        ]
        result = _apply_rotation(regions, 0, 595.28, 841.89)
        self.assertEqual(result[0]["bbox_pt"], [10.0, 20.0, 50.0, 30.0])
        self.assertNotIn("rotation_corrected", result[0])

    def test_90_degree_rotation(self):
        """90-degree rotation should correctly transform bbox coordinates."""
        regions = [
            {"bbox_pt": [100.0, 200.0, 50.0, 30.0]},
        ]
        result = _apply_rotation(regions, 90, 595.28, 841.89)
        bbox = result[0]["bbox_pt"]
        self.assertEqual(len(bbox), 4)
        # 90° CW: ox=ry, oy=page_h-rx-rw, ow=rh, oh=rw
        self.assertAlmostEqual(bbox[0], 200.0, places=1)
        self.assertAlmostEqual(bbox[1], 841.89 - 100.0 - 50.0, places=1)
        self.assertAlmostEqual(bbox[2], 30.0, places=1)
        self.assertAlmostEqual(bbox[3], 50.0, places=1)
        self.assertTrue(result[0]["rotation_corrected"])

    def test_180_degree_rotation(self):
        """180-degree rotation should correctly transform bbox coordinates."""
        regions = [
            {"bbox_pt": [100.0, 200.0, 50.0, 30.0]},
        ]
        result = _apply_rotation(regions, 180, 595.28, 841.89)
        bbox = result[0]["bbox_pt"]
        # 180°: ox=pw-rx-rw, oy=ph-ry-rh, ow=rw, oh=rh
        self.assertAlmostEqual(bbox[0], 595.28 - 100.0 - 50.0, places=1)
        self.assertAlmostEqual(bbox[1], 841.89 - 200.0 - 30.0, places=1)
        self.assertAlmostEqual(bbox[2], 50.0, places=1)
        self.assertAlmostEqual(bbox[3], 30.0, places=1)

    def test_270_degree_rotation(self):
        """270-degree rotation should correctly transform bbox coordinates."""
        regions = [
            {"bbox_pt": [100.0, 200.0, 50.0, 30.0]},
        ]
        result = _apply_rotation(regions, 270, 595.28, 841.89)
        bbox = result[0]["bbox_pt"]
        # 270° CW: ox=pw-ry-rh, oy=rx, ow=rh, oh=rw
        self.assertAlmostEqual(bbox[0], 595.28 - 200.0 - 30.0, places=1)
        self.assertAlmostEqual(bbox[1], 100.0, places=1)
        self.assertAlmostEqual(bbox[2], 30.0, places=1)
        self.assertAlmostEqual(bbox[3], 50.0, places=1)

    def test_region_without_bbox_skipped(self):
        """Regions without bbox_pt should pass through unchanged."""
        regions = [
            {"text": "no bbox"},
        ]
        result = _apply_rotation(regions, 90, 595.28, 841.89)
        self.assertEqual(len(result), 1)
        self.assertNotIn("rotation_corrected", result[0])


class TestNormalizeBboxes(unittest.TestCase):
    """Integration tests for the full normalization pipeline."""

    def test_full_pipeline_with_merge(self):
        """Full pipeline: convert → merge → no rotation."""
        regions = [
            {"bbox_px": [100.0, 200.0, 50.0, 20.0], "text": "hello", "confidence": 0.9, "engine": "test"},
            {"bbox_px": [155.0, 202.0, 40.0, 18.0], "text": "world", "confidence": 0.8, "engine": "test"},
        ]
        result = normalize_bboxes(
            regions, dpi=300.0, rotation_deg=0,
            page_width_pt=595.28, page_height_pt=841.89,
            merge_lines=True,
        )
        # Should merge into one region
        self.assertEqual(len(result), 1)
        self.assertIn("bbox_pt", result[0])
        self.assertEqual(result[0]["text"], "helloworld")
        self.assertEqual(result[0]["merged_count"], 2)

    def test_full_pipeline_no_merge(self):
        """Full pipeline with merge_lines=False."""
        regions = [
            {"bbox_px": [100.0, 200.0, 50.0, 20.0], "text": "hello"},
            {"bbox_px": [155.0, 202.0, 40.0, 18.0], "text": "world"},
        ]
        result = normalize_bboxes(
            regions, dpi=300.0, rotation_deg=0,
            page_width_pt=595.28, page_height_pt=841.89,
            merge_lines=False,
        )
        # Should not merge
        self.assertEqual(len(result), 2)
        for r in result:
            self.assertIn("bbox_pt", r)

    def test_full_pipeline_with_rotation(self):
        """Full pipeline with 180-degree rotation."""
        regions = [
            {"bbox_px": [100.0, 200.0, 50.0, 20.0], "text": "test"},
        ]
        result = normalize_bboxes(
            regions, dpi=300.0, rotation_deg=180,
            page_width_pt=595.28, page_height_pt=841.89,
            merge_lines=True,
        )
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].get("rotation_corrected", False))

    def test_empty_regions(self):
        """Empty regions should return empty list."""
        result = normalize_bboxes(
            [], dpi=300.0, rotation_deg=0,
            page_width_pt=595.28, page_height_pt=841.89,
        )
        self.assertEqual(result, [])


class TestMergeGroup(unittest.TestCase):
    """Tests for the _merge_group helper."""

    def test_merge_two_regions(self):
        """Merging two regions should compute correct bounding box."""
        group = [
            {"index": 0, "x_left": 10, "x_right": 60, "y_top": 20, "y_bottom": 30, "height": 10},
            {"index": 1, "x_left": 65, "x_right": 105, "y_top": 22, "y_bottom": 28, "height": 6},
        ]
        original = [
            {"bbox_pt": [10, 20, 50, 10], "text": "AB", "confidence": 0.9, "engine": "test"},
            {"bbox_pt": [65, 22, 40, 6], "text": "CD", "confidence": 0.8, "engine": "test"},
        ]
        merged = _merge_group(group, original)
        self.assertEqual(merged["bbox_pt"][0], 10)
        self.assertEqual(merged["bbox_pt"][1], 20)
        self.assertEqual(merged["bbox_pt"][2], 95)  # 105 - 10
        self.assertEqual(merged["bbox_pt"][3], 10)  # 30 - 20
        self.assertEqual(merged["text"], "ABCD")
        self.assertAlmostEqual(merged["confidence"], 0.85, places=3)
        self.assertEqual(merged["merged_count"], 2)

    def test_merge_without_text_or_confidence(self):
        """Merging regions without text/confidence should handle gracefully."""
        group = [
            {"index": 0, "x_left": 10, "x_right": 60, "y_top": 20, "y_bottom": 30, "height": 10},
        ]
        original = [
            {"bbox_pt": [10, 20, 50, 10]},
        ]
        merged = _merge_group(group, original)
        self.assertEqual(merged["text"], "")
        self.assertIsNone(merged["confidence"])


if __name__ == "__main__":
    unittest.main()
