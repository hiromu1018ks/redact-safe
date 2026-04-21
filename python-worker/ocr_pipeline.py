"""
OCR Pipeline for RedactSafe.

Provides:
- Digital PDF text extraction (PyMuPDF) for text-layer PDFs
- PaddleOCR-based layout analysis and text recognition
- Tesseract fallback for low-confidence OCR results
"""

import io
import uuid
from typing import Dict, List, Optional, Tuple, Any

# Lazy imports for optional dependencies
_paddle_ocr_engine = None
_paddle_layout_engine = None
_tesseract_available = None


def _get_paddle_ocr_engine():
    """Lazy-initialize PaddleOCR recognition engine."""
    global _paddle_ocr_engine
    if _paddle_ocr_engine is None:
        from paddleocr import PaddleOCR
        _paddle_ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang="japan",
            show_log=False,
            use_gpu=False,
            det_db_thresh=0.3,
            det_db_box_thresh=0.5,
            det_db_unclip_ratio=1.6,
        )
    return _paddle_ocr_engine


def _get_paddle_layout_engine():
    """Lazy-initialize PaddleOCR layout analysis engine."""
    global _paddle_layout_engine
    if _paddle_layout_engine is None:
        from paddleocr import PPStructure
        _paddle_layout_engine = PPStructure(
            show_log=False,
            use_gpu=False,
            layout=True,
            table=False,
            ocr=False,
        )
    return _paddle_layout_engine


def _check_tesseract() -> bool:
    """Check if Tesseract is available on the system."""
    global _tesseract_available
    if _tesseract_available is None:
        import shutil
        _tesseract_available = shutil.which("tesseract") is not None
    return _tesseract_available


def _render_page_to_image(
    doc, page_num: int, dpi: int = 300
) -> "PIL.Image.Image":
    """Render a PDF page to a PIL Image at the specified DPI."""
    import fitz
    from PIL import Image

    page = doc[page_num]
    # Use matrix for DPI scaling
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_data = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_data))
    return img


def _image_to_numpy(img: "PIL.Image.Image"):
    """Convert PIL Image to numpy array (RGB)."""
    import numpy as np
    return np.array(img.convert("RGB"))


def analyze_layout(
    doc, page_num: int, dpi: int = 300
) -> List[Dict[str, Any]]:
    """Analyze page layout using PaddleOCR PPStructure.

    Returns a list of detected layout regions with type and bbox.
    """
    engine = _get_paddle_layout_engine()
    img = _render_page_to_image(doc, page_num, dpi)
    img_np = _image_to_numpy(img)

    result = engine(img_np)

    regions = []
    for item in result:
        bbox = item.get("bbox", [])
        if len(bbox) == 4:
            # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y = min(xs), min(ys)
            w, h = max(xs) - x, max(ys) - y
            regions.append({
                "bbox_px": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "type": _normalize_layout_type(item.get("type", "unknown")),
                "score": round(float(item.get("score", 0.0)), 4),
            })

    return regions


def _normalize_layout_type(raw_type: str) -> str:
    """Normalize PaddleOCR layout type to application types."""
    mapping = {
        "text": "paragraph",
        "figure": "image",
        "figure_caption": "caption",
        "table": "table",
        "table_caption": "table_caption",
        "header": "header",
        "footer": "footer",
        "title": "title",
        "reference": "reference",
        "equation": "equation",
    }
    return mapping.get(raw_type.lower(), raw_type.lower())


def recognize_text_paddleocr(
    doc, page_num: int, dpi: int = 300
) -> List[Dict[str, Any]]:
    """Run PaddleOCR text recognition on a single PDF page.

    Returns a list of text regions with bbox, text, and confidence.
    """
    engine = _get_paddle_ocr_engine()
    img = _render_page_to_image(doc, page_num, dpi)
    img_np = _image_to_numpy(img)

    result = engine.ocr(img_np, cls=True)

    regions = []
    if result is None:
        return regions

    # PaddleOCR returns list of pages; we process one page
    for page_result in result:
        if page_result is None:
            continue
        for line in page_result:
            bbox_points, (text, confidence) = line
            # bbox_points: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            x, y = min(xs), min(ys)
            w, h = max(xs) - x, max(ys) - y
            regions.append({
                "bbox_px": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "text": text,
                "confidence": round(float(confidence), 4),
                "engine": "paddleocr",
            })

    return regions


def recognize_text_tesseract(
    doc, page_num: int, dpi: int = 300, lang: str = "jpn+eng"
) -> List[Dict[str, Any]]:
    """Run Tesseract OCR as fallback for low-confidence regions.

    Returns a list of text regions with bbox, text, and confidence.
    """
    if not _check_tesseract():
        return []

    import pytesseract
    from PIL import Image

    img = _render_page_to_image(doc, page_num, dpi)

    # Get word-level results with bounding boxes
    data = pytesseract.image_to_data(
        img, lang=lang, output_type=pytesseract.Output.DICT
    )

    regions = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue

        conf = int(data["conf"][i])
        if conf < 0:
            continue  # -1 means no text detected

        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]

        regions.append({
            "bbox_px": [float(x), float(y), float(w), float(h)],
            "text": text,
            "confidence": round(conf / 100.0, 4),
            "engine": "tesseract",
        })

    return regions


def run_ocr_pipeline(
    doc, page_num: int, dpi: int = 300
) -> Dict[str, Any]:
    """Run the full OCR pipeline on a single PDF page.

    Steps:
    1. Layout analysis (PaddleOCR PPStructure)
    2. Text recognition (PaddleOCR)
    3. Tesseract fallback for low-confidence regions

    Returns a dict with layout regions and text regions.
    """
    # Step 1: Layout analysis
    layout_regions = analyze_layout(doc, page_num, dpi)

    # Step 2: PaddleOCR text recognition
    text_regions = recognize_text_paddleocr(doc, page_num, dpi)

    # Step 3: Check for low-confidence regions and fall back to Tesseract
    low_conf_regions = [
        r for r in text_regions
        if r["confidence"] < 0.5
    ]

    tesseract_regions = []
    if low_conf_regions:
        tesseract_regions = recognize_text_tesseract(doc, page_num, dpi)
        # Merge: replace low-confidence PaddleOCR results with Tesseract results
        # where Tesseract has higher confidence for overlapping regions
        text_regions = _merge_ocr_results(text_regions, tesseract_regions)

    return {
        "page": page_num + 1,
        "layout_regions": layout_regions,
        "text_regions": text_regions,
        "tesseract_used": len(tesseract_regions) > 0,
        "tesseract_available": _check_tesseract(),
        "dpi": dpi,
    }


def run_ocr_pipeline_base64(
    pdf_data_b64: str,
    page_num: int,
    dpi: int = 300,
    password: str = "",
) -> Dict[str, Any]:
    """Run the full OCR pipeline on a page from base64-encoded PDF data.

    This is the entry point called from the JSON-RPC handler.
    """
    import fitz

    pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        return run_ocr_pipeline(doc, page_num, dpi)
    finally:
        doc.close()


def run_layout_analysis_base64(
    pdf_data_b64: str,
    page_num: int,
    dpi: int = 300,
    password: str = "",
) -> Dict[str, Any]:
    """Run layout analysis only on a page from base64-encoded PDF data.

    This is the entry point called from the JSON-RPC handler.
    """
    import fitz

    pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        layout_regions = analyze_layout(doc, page_num, dpi)
        return {
            "page": page_num + 1,
            "layout_regions": layout_regions,
            "dpi": dpi,
        }
    finally:
        doc.close()


def _merge_ocr_results(
    paddle_regions: List[Dict],
    tesseract_regions: List[Dict],
) -> List[Dict]:
    """Merge PaddleOCR and Tesseract results.

    For each low-confidence PaddleOCR region, if a Tesseract region
    overlaps significantly and has higher confidence, replace it.
    """
    if not tesseract_regions:
        return paddle_regions

    result = []
    for p_region in paddle_regions:
        if p_region["confidence"] >= 0.5:
            # Keep high-confidence PaddleOCR results
            result.append(p_region)
            continue

        # Find best overlapping Tesseract region
        best_tess = _find_best_overlap(p_region, tesseract_regions)
        if best_tess and best_tess["confidence"] > p_region["confidence"]:
            best_tess["engine"] = "tesseract_fallback"
            result.append(best_tess)
        else:
            result.append(p_region)

    return result


def _find_best_overlap(
    region: Dict, candidates: List[Dict], iou_threshold: float = 0.3
) -> Optional[Dict]:
    """Find the candidate region with the highest IoU overlap."""
    best = None
    best_iou = iou_threshold

    rb = region["bbox_px"]
    rx1, ry1 = rb[0], rb[1]
    rx2, ry2 = rb[0] + rb[2], rb[1] + rb[3]

    for cand in candidates:
        cb = cand["bbox_px"]
        cx1, cy1 = cb[0], cb[1]
        cx2, cy2 = cb[0] + cb[2], cb[1] + cb[3]

        # Intersection
        ix1 = max(rx1, cx1)
        iy1 = max(ry1, cy1)
        ix2 = min(rx2, cx2)
        iy2 = min(ry2, cy2)

        if ix1 >= ix2 or iy1 >= iy2:
            continue

        inter = (ix2 - ix1) * (iy2 - iy1)
        area_r = (rx2 - rx1) * (ry2 - ry1)
        area_c = (cx2 - cx1) * (cy2 - cy1)
        union = area_r + area_c - inter

        if union > 0:
            iou = inter / union
            if iou > best_iou:
                best_iou = iou
                best = cand

    return best


# --- Digital PDF Text Extraction (PyMuPDF) ---


def check_text_layer(doc, page_num: int) -> bool:
    """Check if a PDF page has an extractable text layer.

    Returns True if the page contains text content (not just images).
    """
    page = doc[page_num]
    text_dict = page.get_text("dict")
    blocks = text_dict.get("blocks", [])
    for block in blocks:
        if block.get("type") == 0:  # text block
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        return True
    return False


def extract_text_digital(
    doc, page_num: int, rotation_deg: int = 0
) -> Dict[str, Any]:
    """Extract text and bounding boxes from a digital PDF using PyMuPDF.

    Uses page.get_text("rawdict") to get character-level quads,
    then groups them into text regions (lines) with bounding boxes.

    Confidence is fixed at 1.0 for digital text extraction path.

    Returns a dict with text_regions, extraction_path, and page info.
    """
    page = doc[page_num]

    # Apply rotation correction to page rect
    rect = page.rect
    page_width_pt = round(rect.width, 2)
    page_height_pt = round(rect.height, 2)

    text_dict = page.get_text("rawdict")
    blocks = text_dict.get("blocks", [])

    text_regions = []
    for block in blocks:
        if block.get("type") != 0:  # skip image blocks
            continue

        block_bbox = block.get("bbox", [])  # [x0, y0, x1, y1] in PDF points
        if not block_bbox or len(block_bbox) < 4:
            continue

        for line in block.get("lines", []):
            line_bbox = line.get("bbox", [])  # [x0, y0, x1, y1]
            if not line_bbox or len(line_bbox) < 4:
                continue

            # Collect text and spans for this line
            line_text_parts = []
            for span in line.get("spans", []):
                span_text = span.get("text", "")
                if span_text.strip():
                    line_text_parts.append(span_text)

            line_text = "".join(line_text_parts).strip()
            if not line_text:
                continue

            # Calculate bbox in PDF points [x, y, width, height]
            x0, y0, x1, y1 = line_bbox
            bbox_pt = [
                round(x0, 2),
                round(y0, 2),
                round(x1 - x0, 2),
                round(y1 - y0, 2),
            ]

            # Get font info from first span
            font_info = {}
            spans = line.get("spans", [])
            if spans:
                first_span = spans[0]
                font_info = {
                    "font": first_span.get("font", ""),
                    "size": round(first_span.get("size", 0), 2),
                    "flags": first_span.get("flags", 0),
                }

            region_id = str(uuid.uuid4())

            text_regions.append({
                "id": region_id,
                "bbox_pt": bbox_pt,
                "text": line_text,
                "confidence": 1.0,
                "engine": "digital_extraction",
                "font": font_info,
                "block_bbox": [
                    round(block_bbox[0], 2),
                    round(block_bbox[1], 2),
                    round(block_bbox[2] - block_bbox[0], 2),
                    round(block_bbox[3] - block_bbox[1], 2),
                ],
            })

    return {
        "page": page_num + 1,
        "extraction_path": "digital",
        "text_regions": text_regions,
        "has_text_layer": len(text_regions) > 0,
        "page_width_pt": page_width_pt,
        "page_height_pt": page_height_pt,
        "rotation_deg": rotation_deg,
    }


def extract_text_digital_base64(
    pdf_data_b64: str,
    page_num: int,
    password: str = "",
) -> Dict[str, Any]:
    """Extract text from a digital PDF page using base64-encoded data.

    Entry point for JSON-RPC handler.
    """
    import fitz

    pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        page = doc[page_num]
        rotation_deg = page.rotation
        return extract_text_digital(doc, page_num, rotation_deg)
    finally:
        doc.close()


def run_text_extraction(
    pdf_data_b64: str,
    page_num: int,
    dpi: int = 300,
    password: str = "",
) -> Dict[str, Any]:
    """Unified text extraction: tries digital path first, falls back to OCR.

    Returns a dict with extraction_path ("digital" or "ocr"), text_regions,
    and metadata about the extraction process.
    """
    import fitz

    pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        page = doc[page_num]
        rotation_deg = page.rotation

        # Step 1: Check for text layer
        has_text = check_text_layer(doc, page_num)

        if has_text:
            # Digital extraction path
            result = extract_text_digital(doc, page_num, rotation_deg)
            return result
        else:
            # OCR fallback path
            ocr_result = run_ocr_pipeline(doc, page_num, dpi)
            ocr_result["extraction_path"] = "ocr"
            ocr_result["has_text_layer"] = False
            return ocr_result
    finally:
        doc.close()
