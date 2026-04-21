"""
BBox Normalizer for RedactSafe.

Normalizes OCR output bounding boxes:
1. Converts pixel coordinates to PDF point coordinates
2. Groups nearby bboxes into lines and merges into minimum bounding rectangles
3. Applies page rotation correction
"""

from typing import Any, Dict, List, Optional, Tuple

from coord_utils import bbox_pixel_to_pdf_point, rotate_bbox


def normalize_bboxes(
    regions: List[Dict[str, Any]],
    dpi: float,
    rotation_deg: int = 0,
    page_width_pt: float = 595.28,
    page_height_pt: float = 841.89,
    merge_lines: bool = True,
    line_merge_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """Normalize a list of OCR text regions.

    Pipeline:
    1. Convert bbox_px (pixel) to bbox_pt (PDF point)
    2. Optionally merge nearby bboxes into lines
    3. Apply rotation correction

    Args:
        regions: List of OCR text regions, each containing at least "bbox_px".
                 May also contain "text", "confidence", "engine" etc.
        dpi: DPI used for the rasterization that produced the pixel coordinates.
        rotation_deg: Page rotation in degrees (0, 90, 180, 270).
        page_width_pt: Unrotated page width in PDF points.
        page_height_pt: Unrotated page height in PDF points.
        merge_lines: If True, merge nearby bboxes into line groups.
        line_merge_threshold: Fraction of bbox height used as vertical proximity
                              threshold for grouping into the same line (default 0.5).

    Returns:
        List of normalized regions with "bbox_pt" in PDF point coordinates.
    """
    if not regions:
        return []

    # Step 1: Convert pixel bboxes to PDF points
    converted = _convert_bboxes_to_pdf_points(regions, dpi)

    # Step 2: Merge nearby bboxes into lines
    if merge_lines:
        merged = _group_and_merge_lines(converted, line_merge_threshold)
    else:
        merged = converted

    # Step 3: Apply rotation correction
    if rotation_deg != 0:
        corrected = _apply_rotation(merged, rotation_deg, page_width_pt, page_height_pt)
    else:
        corrected = merged

    return corrected


def _convert_bboxes_to_pdf_points(
    regions: List[Dict[str, Any]], dpi: float
) -> List[Dict[str, Any]]:
    """Convert all regions from pixel coordinates to PDF point coordinates."""
    result = []
    for region in regions:
        bbox_px = region.get("bbox_px")
        if not bbox_px or len(bbox_px) < 4:
            continue

        bbox_pt = bbox_pixel_to_pdf_point(bbox_px, dpi)
        # bbox_pixel_to_pdf_point returns [x, y, w, h] - round to 2 decimal places
        bbox_pt = [round(v, 2) for v in bbox_pt]

        new_region = dict(region)
        new_region["bbox_pt"] = bbox_pt
        # Keep bbox_px for reference
        result.append(new_region)

    return result


def _group_and_merge_lines(
    regions: List[Dict[str, Any]],
    threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """Group nearby bboxes into lines and merge each group into one bbox.

    Two bboxes are considered part of the same line if their vertical ranges
    overlap or are within the threshold fraction of the taller bbox's height.

    Args:
        regions: List of regions with "bbox_pt" in PDF points.
        threshold: Vertical proximity threshold as fraction of max height.

    Returns:
        List of merged regions. Each merged region contains:
        - bbox_pt: merged bounding box
        - text: concatenated text of all merged regions (if "text" keys exist)
        - confidence: average confidence (if "confidence" keys exist)
        - merged_count: number of original regions merged
        - source_regions: list of original region data
    """
    if not regions:
        return []

    if len(regions) == 1:
        return regions

    # Extract line-level info for grouping
    # Each entry: (index, x_left, x_right, y_top, y_bottom, height)
    line_info = []
    for i, region in enumerate(regions):
        bbox = region.get("bbox_pt", [])
        if len(bbox) < 4:
            continue
        x, y, w, h = bbox
        line_info.append({
            "index": i,
            "x_left": x,
            "x_right": x + w,
            "y_top": y,
            "y_bottom": y + h,
            "height": h,
        })

    if not line_info:
        return regions

    # Sort by y_top (top to bottom), then by x_left (left to right)
    line_info.sort(key=lambda info: (info["y_top"], info["x_left"]))

    # Group into lines using a single pass
    groups: List[List[Dict]] = []
    current_group = [line_info[0]]

    for i in range(1, len(line_info)):
        prev = current_group[-1]
        curr = line_info[i]

        if _is_same_line(prev, curr, threshold):
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]

    groups.append(current_group)

    # Merge each group
    merged_regions = []
    for group in groups:
        if len(group) == 1:
            # Single region, no merge needed
            merged_regions.append(regions[group[0]["index"]])
        else:
            merged = _merge_group(group, regions)
            merged_regions.append(merged)

    return merged_regions


def _is_same_line(a: Dict, b: Dict, threshold: float) -> bool:
    """Check if two bbox entries belong to the same text line.

    They are on the same line if their vertical ranges overlap or are
    within the threshold fraction of the max height apart.
    """
    max_height = max(a["height"], b["height"])
    proximity_threshold = max_height * threshold

    # Check vertical overlap
    y_top_max = max(a["y_top"], b["y_top"])
    y_bottom_min = min(a["y_bottom"], b["y_bottom"])

    if y_bottom_min >= y_top_max:
        # Vertical overlap exists
        return True

    # No overlap - check if they are close enough
    gap = y_top_max - y_bottom_min
    return gap <= proximity_threshold


def _merge_group(
    group: List[Dict],
    original_regions: List[Dict],
) -> Dict:
    """Merge a group of bbox entries into a single region.

    Computes the minimum bounding rectangle for the group and
    concatenates text/confidence if available.
    """
    # Compute merged bbox
    x_min = min(info["x_left"] for info in group)
    y_min = min(info["y_top"] for info in group)
    x_max = max(info["x_right"] for info in group)
    y_max = max(info["y_bottom"] for info in group)

    bbox_pt = [
        round(x_min, 2),
        round(y_min, 2),
        round(x_max - x_min, 2),
        round(y_max - y_min, 2),
    ]

    # Collect text and confidence from original regions
    texts = []
    confidences = []
    source_indices = []

    for info in group:
        idx = info["index"]
        source_indices.append(idx)
        region = original_regions[idx]

        text = region.get("text", "")
        if text:
            texts.append(text)

        conf = region.get("confidence")
        if conf is not None:
            confidences.append(float(conf))

    merged_text = "".join(texts) if texts else ""
    avg_confidence = (
        round(sum(confidences) / len(confidences), 4)
        if confidences
        else None
    )

    # Determine engine: prefer the most common engine
    engines = [original_regions[idx].get("engine", "") for idx in source_indices]
    engine = _most_common(engines) if engines else ""

    return {
        "bbox_pt": bbox_pt,
        "text": merged_text,
        "confidence": avg_confidence,
        "engine": engine,
        "merged_count": len(group),
        "source_indices": source_indices,
    }


def _most_common(items: List[str]) -> str:
    """Return the most common string in a list."""
    from collections import Counter
    if not items:
        return ""
    counter = Counter(items)
    return counter.most_common(1)[0][0]


def _apply_rotation(
    regions: List[Dict[str, Any]],
    rotation_deg: int,
    page_width_pt: float,
    page_height_pt: float,
) -> List[Dict[str, Any]]:
    """Apply rotation correction to all regions."""
    result = []
    for region in regions:
        bbox_pt = region.get("bbox_pt")
        if not bbox_pt or len(bbox_pt) < 4:
            result.append(region)
            continue

        try:
            corrected = rotate_bbox(
                bbox_pt, rotation_deg, page_width_pt, page_height_pt
            )
            corrected = [round(v, 2) for v in corrected]
            new_region = dict(region)
            new_region["bbox_pt"] = corrected
            new_region["rotation_corrected"] = True
            result.append(new_region)
        except ValueError:
            # If rotation is unsupported, keep original
            result.append(region)

    return result


# --- JSON-RPC entry point ---


def normalize_ocr_results(
    pdf_data_b64: str,
    page_num: int,
    regions: List[Dict[str, Any]],
    dpi: float = 300.0,
    rotation_deg: int = 0,
    password: str = "",
    merge_lines: bool = True,
) -> Dict[str, Any]:
    """Normalize OCR results for a PDF page.

    This is the entry point called from the JSON-RPC handler.
    It combines coordinate conversion, line merging, and rotation correction
    into a single operation.

    Args:
        pdf_data_b64: Base64-encoded PDF data.
        page_num: Zero-based page number.
        regions: OCR text regions with "bbox_px" coordinates.
        dpi: DPI used for rasterization.
        rotation_deg: Page rotation (auto-detected if 0 and pdf_data provided).
        password: PDF password if encrypted.
        merge_lines: Whether to merge nearby bboxes into lines.

    Returns:
        Dict with normalized regions and metadata.
    """
    import fitz
    import base64

    pdf_bytes = base64.b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        page = doc[page_num]
        page_width_pt = round(page.rect.width, 2)
        page_height_pt = round(page.rect.height, 2)

        # Auto-detect rotation if not specified
        if rotation_deg == 0:
            detected_rotation = page.rotation
            if detected_rotation != 0:
                rotation_deg = detected_rotation

        normalized = normalize_bboxes(
            regions=regions,
            dpi=dpi,
            rotation_deg=rotation_deg,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
            merge_lines=merge_lines,
        )

        return {
            "page": page_num + 1,
            "normalized_regions": normalized,
            "region_count": len(normalized),
            "input_count": len(regions),
            "merge_ratio": (
                round(len(normalized) / len(regions), 4)
                if regions
                else 0.0
            ),
            "rotation_deg": rotation_deg,
            "page_width_pt": page_width_pt,
            "page_height_pt": page_height_pt,
            "dpi": dpi,
        }
    finally:
        doc.close()
