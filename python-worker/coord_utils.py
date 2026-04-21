"""
Coordinate conversion utilities for RedactSafe.

Canonical coordinate system: PDF point (1pt = 1/72 inch), origin at top-left.
This module provides conversion between PDF points and pixel coordinates,
as well as page rotation correction for bounding boxes.
"""

from typing import Tuple, List

# 1 inch = 72 PDF points
POINTS_PER_INCH = 72.0


def pdf_point_to_pixel(
    x_pt: float,
    y_pt: float,
    dpi: float = 300.0,
) -> Tuple[float, float]:
    """Convert PDF point coordinates to pixel coordinates.

    Args:
        x_pt: X coordinate in PDF points.
        y_pt: Y coordinate in PDF points.
        dpi: Resolution in dots per inch.

    Returns:
        (x_px, y_px) in pixel coordinates.
    """
    scale = dpi / POINTS_PER_INCH
    return (x_pt * scale, y_pt * scale)


def pixel_to_pdf_point(
    x_px: float,
    y_px: float,
    dpi: float = 300.0,
) -> Tuple[float, float]:
    """Convert pixel coordinates to PDF point coordinates.

    Args:
        x_px: X coordinate in pixels.
        y_px: Y coordinate in pixels.
        dpi: Resolution in dots per inch.

    Returns:
        (x_pt, y_pt) in PDF point coordinates.
    """
    scale = POINTS_PER_INCH / dpi
    return (x_px * scale, y_px * scale)


def bbox_pdf_point_to_pixel(
    bbox: List[float],
    dpi: float = 300.0,
) -> List[float]:
    """Convert a bounding box from PDF points to pixels.

    Args:
        bbox: [x, y, width, height] in PDF points.
        dpi: Resolution in dots per inch.

    Returns:
        [x, y, width, height] in pixels.
    """
    x_pt, y_pt, w_pt, h_pt = bbox
    x_px, y_px = pdf_point_to_pixel(x_pt, y_pt, dpi)
    w_px = w_pt * dpi / POINTS_PER_INCH
    h_px = h_pt * dpi / POINTS_PER_INCH
    return [x_px, y_px, w_px, h_px]


def bbox_pixel_to_pdf_point(
    bbox: List[float],
    dpi: float = 300.0,
) -> List[float]:
    """Convert a bounding box from pixels to PDF points.

    Args:
        bbox: [x, y, width, height] in pixels.
        dpi: Resolution in dots per inch.

    Returns:
        [x, y, width, height] in PDF points.
    """
    x_px, y_px, w_px, h_px = bbox
    x_pt, y_pt = pixel_to_pdf_point(x_px, y_px, dpi)
    w_pt = w_px * POINTS_PER_INCH / dpi
    h_pt = h_px * POINTS_PER_INCH / dpi
    return [x_pt, y_pt, h_pt]


def rotate_bbox(
    bbox: List[float],
    rotation_deg: int,
    page_width_pt: float,
    page_height_pt: float,
) -> List[float]:
    """Correct a bounding box for page rotation.

    When OCR runs on a rasterized image, the image is rendered with rotation applied.
    The OCR results are in the rotated (display) coordinate space. This function
    converts them back to the original PDF coordinate space.

    Args:
        bbox: [x, y, width, height] in the rotated (display) coordinate space.
        rotation_deg: Page rotation in degrees (0, 90, 180, 270).
        page_width_pt: Width of the page in PDF points (unrotated).
        page_height_pt: Height of the page in PDF points (unrotated).

    Returns:
        [x, y, width, height] in the original (unrotated) PDF coordinate space.

    Raises:
        ValueError: If rotation_deg is not 0, 90, 180, or 270.
    """
    if rotation_deg == 0:
        return list(bbox)

    if rotation_deg not in (90, 180, 270):
        raise ValueError(
            f"Unsupported rotation: {rotation_deg}. Must be 0, 90, 180, or 270."
        )

    rx, ry, rw, rh = bbox

    if rotation_deg == 90:
        # 90° CW: display coords → original coords
        # Display (rx, ry) maps to original (ry, page_height - rx - rw)
        ox = ry
        oy = page_height_pt - rx - rw
        ow = rh
        oh = rw
        return [ox, oy, ow, oh]

    elif rotation_deg == 180:
        # 180°: display coords → original coords
        ox = page_width_pt - rx - rw
        oy = page_height_pt - ry - rh
        ow = rw
        oh = rh
        return [ox, oy, ow, oh]

    elif rotation_deg == 270:
        # 270° CW (= 90° CCW): display coords → original coords
        ox = page_width_pt - ry - rh
        oy = rx
        ow = rh
        oh = rw
        return [ox, oy, ow, oh]

    # Should never reach here
    return list(bbox)
