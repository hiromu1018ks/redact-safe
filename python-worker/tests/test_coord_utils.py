"""Unit tests for coordinate conversion utilities."""

import sys
import os
import unittest

# Add parent directory to path so we can import coord_utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coord_utils import (
    pdf_point_to_pixel,
    pixel_to_pdf_point,
    bbox_pdf_point_to_pixel,
    bbox_pixel_to_pdf_point,
    rotate_bbox,
    POINTS_PER_INCH,
)


class TestPdfPointToPixel(unittest.TestCase):
    """Tests for PDF point to pixel conversion."""

    def test_origin(self):
        """Origin (0,0) should map to (0,0) at any DPI."""
        x, y = pdf_point_to_pixel(0, 0, 72)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.0)

    def test_one_inch(self):
        """72 PDF points = 1 inch = DPI pixels at given DPI."""
        x, y = pdf_point_to_pixel(72, 72, 72)
        self.assertAlmostEqual(x, 72.0)
        self.assertAlmostEqual(y, 72.0)

    def test_300dpi(self):
        """At 300 DPI, 72pt should be 300 pixels."""
        x, y = pdf_point_to_pixel(72, 72, 300)
        self.assertAlmostEqual(x, 300.0)
        self.assertAlmostEqual(y, 300.0)

    def test_half_inch_300dpi(self):
        """At 300 DPI, 36pt (0.5 inch) should be 150 pixels."""
        x, y = pdf_point_to_pixel(36, 36, 300)
        self.assertAlmostEqual(x, 150.0)
        self.assertAlmostEqual(y, 150.0)

    def test_a4_page_width(self):
        """A4 width is 595.28pt ≈ 210mm. At 300 DPI: 595.28 * 300/72 ≈ 2480.33px."""
        x, _ = pdf_point_to_pixel(595.28, 0, 300)
        self.assertAlmostEqual(x, 595.28 * 300 / 72, places=2)

    def test_a4_page_height(self):
        """A4 height is 841.89pt ≈ 297mm. At 300 DPI: 841.89 * 300/72 ≈ 3507.88px."""
        _, y = pdf_point_to_pixel(0, 841.89, 300)
        self.assertAlmostEqual(y, 841.89 * 300 / 72, places=2)


class TestPixelToPdfPoint(unittest.TestCase):
    """Tests for pixel to PDF point conversion."""

    def test_roundtrip(self):
        """Converting PDF points → pixels → PDF points should return original values."""
        original_x, original_y = 100.5, 200.75
        dpi = 300.0
        x_px, y_px = pdf_point_to_pixel(original_x, original_y, dpi)
        x_pt, y_pt = pixel_to_pdf_point(x_px, y_px, dpi)
        self.assertAlmostEqual(x_pt, original_x, places=10)
        self.assertAlmostEqual(y_pt, original_y, places=10)

    def test_300px_to_pt(self):
        """300 pixels at 300 DPI should be 72 PDF points (1 inch)."""
        x, y = pixel_to_pdf_point(300, 300, 300)
        self.assertAlmostEqual(x, 72.0)
        self.assertAlmostEqual(y, 72.0)

    def test_roundtrip_various_dpi(self):
        """Roundtrip should work at various DPI values."""
        for dpi in [72, 96, 150, 200, 300, 600]:
            ox, oy = 123.456, 789.012
            px, py = pdf_point_to_pixel(ox, oy, dpi)
            rx, ry = pixel_to_pdf_point(px, py, dpi)
            self.assertAlmostEqual(rx, ox, places=8, msg=f"Failed at DPI={dpi}")
            self.assertAlmostEqual(ry, oy, places=8, msg=f"Failed at DPI={dpi}")


class TestBboxConversion(unittest.TestCase):
    """Tests for bounding box conversion."""

    def test_bbox_pdf_to_pixel(self):
        """Convert a bbox from PDF points to pixels at 300 DPI."""
        bbox = [100.0, 200.0, 50.0, 30.0]
        result = bbox_pdf_point_to_pixel(bbox, 300)
        scale = 300 / POINTS_PER_INCH
        expected = [100 * scale, 200 * scale, 50 * scale, 30 * scale]
        for r, e in zip(result, expected):
            self.assertAlmostEqual(r, e, places=8)

    def test_bbox_pixel_to_pdf(self):
        """Convert a bbox from pixels to PDF points at 300 DPI."""
        scale = 300 / POINTS_PER_INCH
        bbox = [100 * scale, 200 * scale, 50 * scale, 30 * scale]
        result = bbox_pixel_to_pdf_point(bbox, 300)
        expected = [100.0, 200.0, 50.0, 30.0]
        for r, e in zip(result, expected):
            self.assertAlmostEqual(r, e, places=8)

    def test_bbox_roundtrip(self):
        """Bbox roundtrip should return original values."""
        original = [72.5, 144.0, 36.0, 18.0]
        for dpi in [72, 150, 300]:
            px_bbox = bbox_pdf_point_to_pixel(original, dpi)
            pt_bbox = bbox_pixel_to_pdf_point(px_bbox, dpi)
            for o, r in zip(original, pt_bbox):
                self.assertAlmostEqual(o, r, places=8, msg=f"Failed at DPI={dpi}")


class TestRotateBbox(unittest.TestCase):
    """Tests for page rotation correction of bounding boxes."""

    def setUp(self):
        # A4 page dimensions in PDF points
        self.page_width = 595.28
        self.page_height = 841.89

    def test_zero_rotation(self):
        """0° rotation should return the bbox unchanged."""
        bbox = [100.0, 200.0, 50.0, 30.0]
        result = rotate_bbox(bbox, 0, self.page_width, self.page_height)
        self.assertEqual(result, [100.0, 200.0, 50.0, 30.0])

    def test_invalid_rotation(self):
        """Invalid rotation should raise ValueError."""
        bbox = [0.0, 0.0, 10.0, 10.0]
        with self.assertRaises(ValueError):
            rotate_bbox(bbox, 45, self.page_width, self.page_height)
        with self.assertRaises(ValueError):
            rotate_bbox(bbox, -90, self.page_width, self.page_height)

    def test_90_degree_rotation_top_left(self):
        """90° CW: a bbox at top-left of rotated view should map correctly."""
        # In rotated view (90° CW), display width = page_height, display height = page_width
        # A bbox at (0, 0, 100, 50) in rotated space
        # Original: x = ry = 0, y = page_height - rx - rw = 841.89 - 0 - 100 = 741.89
        # Width = rh = 50, Height = rw = 100
        bbox = [0.0, 0.0, 100.0, 50.0]
        result = rotate_bbox(bbox, 90, self.page_width, self.page_height)
        self.assertAlmostEqual(result[0], 0.0)  # x
        self.assertAlmostEqual(result[1], self.page_height - 100.0)  # y
        self.assertAlmostEqual(result[2], 50.0)  # w
        self.assertAlmostEqual(result[3], 100.0)  # h

    def test_180_degree_rotation_center(self):
        """180°: a bbox in the center should flip to the opposite corner."""
        # Display (100, 100, 50, 30) at 180°
        # Original: x = page_width - 100 - 50 = 445.28
        # y = page_height - 100 - 30 = 711.89
        bbox = [100.0, 100.0, 50.0, 30.0]
        result = rotate_bbox(bbox, 180, self.page_width, self.page_height)
        self.assertAlmostEqual(result[0], self.page_width - 150.0)  # 595.28 - 100 - 50
        self.assertAlmostEqual(result[1], self.page_height - 130.0)  # 841.89 - 100 - 30
        self.assertAlmostEqual(result[2], 50.0)  # w unchanged
        self.assertAlmostEqual(result[3], 30.0)  # h unchanged

    def test_270_degree_rotation(self):
        """270° CW (= 90° CCW) rotation."""
        # Display (100, 100, 50, 30) at 270° CW
        # Original: x = page_width - ry - rh = 595.28 - 100 - 30 = 465.28
        # y = rx = 100
        # w = rh = 30, h = rw = 50
        bbox = [100.0, 100.0, 50.0, 30.0]
        result = rotate_bbox(bbox, 270, self.page_width, self.page_height)
        self.assertAlmostEqual(result[0], self.page_width - 130.0)  # 595.28 - 100 - 30
        self.assertAlmostEqual(result[1], 100.0)  # y
        self.assertAlmostEqual(result[2], 30.0)  # w = rh
        self.assertAlmostEqual(result[3], 50.0)  # h = rw

    def test_90_then_inverse_270(self):
        """Rotating by 90° then 270° should return the original bbox."""
        original = [72.0, 144.0, 50.0, 30.0]
        rotated_90 = rotate_bbox(original, 90, self.page_width, self.page_height)
        # The effective display dimensions after 90° rotation are (page_height, page_width)
        restored = rotate_bbox(rotated_90, 270, self.page_width, self.page_height)
        for o, r in zip(original, restored):
            self.assertAlmostEqual(o, r, places=8)

    def test_180_then_180(self):
        """Two 180° rotations should return the original bbox."""
        original = [100.0, 200.0, 60.0, 40.0]
        rotated = rotate_bbox(original, 180, self.page_width, self.page_height)
        restored = rotate_bbox(rotated, 180, self.page_width, self.page_height)
        for o, r in zip(original, restored):
            self.assertAlmostEqual(o, r, places=8)

    def test_square_page_90(self):
        """Square page: 90° rotation should swap width/height but keep position."""
        size = 500.0
        bbox = [100.0, 200.0, 50.0, 30.0]
        result = rotate_bbox(bbox, 90, size, size)
        # x = ry = 200, y = 500 - 100 - 50 = 350, w = 30, h = 50
        self.assertAlmostEqual(result[0], 200.0)
        self.assertAlmostEqual(result[1], 350.0)
        self.assertAlmostEqual(result[2], 30.0)
        self.assertAlmostEqual(result[3], 50.0)


class TestIntegration(unittest.TestCase):
    """Integration tests combining coordinate conversion and rotation."""

    def test_ocr_pipeline_simulation(self):
        """Simulate the full OCR pipeline: image render → OCR → convert back to PDF coords.

        Scenario: A4 page with 90° rotation.
        1. Page is rasterized at 300 DPI with rotation applied.
           Effective display dimensions: (841.89pt * 300/72, 595.28pt * 300/72) pixels.
        2. OCR detects text at pixel coordinates (1000, 500, 200, 50).
        3. Convert pixel bbox to PDF points (in rotated space).
        4. Apply inverse rotation to get original PDF coordinates.
        """
        page_width = 595.28
        page_height = 841.89
        rotation = 90
        dpi = 300.0

        # OCR result in pixels (rotated view)
        ocr_bbox_px = [1000.0, 500.0, 200.0, 50.0]

        # Step 1: Convert pixels to PDF points (rotated space)
        bbox_rotated_pt = bbox_pixel_to_pdf_point(ocr_bbox_px, dpi)

        # Step 2: Apply inverse rotation
        bbox_original_pt = rotate_bbox(
            bbox_rotated_pt, rotation, page_width, page_height
        )

        # Verify the result is valid (within page bounds)
        x, y, w, h = bbox_original_pt
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertLessEqual(x + w, page_width + 1)  # small tolerance
        self.assertLessEqual(y + h, page_height + 1)

    def test_no_rotation_pipeline(self):
        """Pipeline with 0° rotation should be a simple pixel-to-PDF conversion."""
        page_width = 595.28
        page_height = 841.89
        dpi = 300.0

        ocr_bbox_px = [1000.0, 500.0, 200.0, 50.0]
        bbox_pt = bbox_pixel_to_pdf_point(ocr_bbox_px, dpi)
        bbox_original = rotate_bbox(bbox_pt, 0, page_width, page_height)

        # Should be the same as the direct conversion
        for o, r in zip(bbox_pt, bbox_original):
            self.assertAlmostEqual(o, r)


if __name__ == "__main__":
    unittest.main()
