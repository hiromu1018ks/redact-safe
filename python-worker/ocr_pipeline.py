"""
OCR Pipeline for RedactSafe.

Provides:
- Digital PDF text extraction (PyMuPDF) for text-layer PDFs
- PaddleOCR-based layout analysis and text recognition
- Tesseract fallback for low-confidence OCR results
"""

import io
import os
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
        import sys
        from paddleocr import PaddleOCR
        # Suppress download messages that would corrupt stdout JSON pipe
        _old_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            _paddle_ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang="japan",
                show_log=False,
                use_gpu=False,
            )
        finally:
            sys.stdout = _old_stdout
    return _paddle_ocr_engine


def _get_paddle_layout_engine():
    """Lazy-initialize PaddleOCR layout analysis engine. Returns None if unavailable."""
    global _paddle_layout_engine
    if _paddle_layout_engine is None:
        try:
            import sys
            from paddleocr import PPStructure
            # Suppress download messages that would corrupt stdout JSON pipe
            _old_stdout = sys.stdout
            sys.stdout = sys.stderr
            try:
                _paddle_layout_engine = PPStructure(
                    show_log=False,
                    use_gpu=False,
                    layout=True,
                    table=False,
                    ocr=False,
                )
            finally:
                sys.stdout = _old_stdout
        except Exception:
            _paddle_layout_engine = False  # Sentinel: tried and failed
    if _paddle_layout_engine is False:
        return None
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
    """Render a PDF page to a PIL Image at the specified DPI.

    Uses Image.frombytes to avoid PNG encode/decode round-trip for efficiency.
    """
    import fitz
    from PIL import Image

    page = doc[page_num]
    # Use matrix for DPI scaling
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def _image_to_numpy(img: "PIL.Image.Image"):
    """Convert PIL Image to numpy array (RGB)."""
    import numpy as np
    return np.array(img.convert("RGB"))


def analyze_layout(
    doc, page_num: int, dpi: int = 300, page_image: "PIL.Image.Image" = None
) -> List[Dict[str, Any]]:
    """Analyze page layout using PaddleOCR PPStructure.

    Returns a list of detected layout regions with type and bbox.
    Returns empty list if layout engine is unavailable.
    """
    engine = _get_paddle_layout_engine()
    if engine is None:
        return []
    if page_image is None:
        page_image = _render_page_to_image(doc, page_num, dpi)
    img_np = _image_to_numpy(page_image)

    result = engine(img_np)

    regions = []
    for item in result:
        bbox = item.get("bbox", [])
        if len(bbox) == 4:
            # bbox can be [x1, y1, x2, y2] or [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            if isinstance(bbox[0], (list, tuple)):
                # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
            else:
                # [x1, y1, x2, y2]
                xs = [bbox[0], bbox[2]]
                ys = [bbox[1], bbox[3]]
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
    doc, page_num: int, dpi: int = 300, page_image: "PIL.Image.Image" = None
) -> List[Dict[str, Any]]:
    """Run PaddleOCR text recognition on a single PDF page.

    Returns a list of text regions with bbox, text, and confidence.
    """
    engine = _get_paddle_ocr_engine()
    if page_image is None:
        page_image = _render_page_to_image(doc, page_num, dpi)
    img_np = _image_to_numpy(page_image)

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
    doc, page_num: int, dpi: int = 300, lang: str = "jpn+eng",
    page_image: "PIL.Image.Image" = None
) -> List[Dict[str, Any]]:
    """Run Tesseract OCR as fallback for low-confidence regions.

    Returns a list of text regions with bbox, text, and confidence.
    """
    if not _check_tesseract():
        return []

    import pytesseract
    from PIL import Image

    if page_image is None:
        page_image = _render_page_to_image(doc, page_num, dpi)
    img = page_image

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
    doc, page_num: int, dpi: int = 300, progress_callback=None
) -> Dict[str, Any]:
    """Run the full OCR pipeline on a single PDF page.

    Steps:
    1. Layout analysis (PaddleOCR PPStructure)
    2. Text recognition (PaddleOCR)
    3. Tesseract fallback for low-confidence regions

    Args:
        progress_callback: Optional callable(phase, current, total, message) for progress updates.
    """
    if progress_callback:
        progress_callback("layout_analysis", 0, 3, "レイアウト解析中...")

    # Render page image once and reuse across all steps
    page_image = _render_page_to_image(doc, page_num, dpi)

    # Step 1: Layout analysis
    layout_regions = analyze_layout(doc, page_num, dpi, page_image=page_image)

    if progress_callback:
        progress_callback("text_recognition", 1, 3, "文字認識中...")

    # Step 2: PaddleOCR text recognition
    text_regions = recognize_text_paddleocr(doc, page_num, dpi, page_image=page_image)

    # Convert pixel bboxes to PDF point coordinates [x, y, width, height]
    page = doc[page_num]
    scale = 72.0 / dpi
    for region in text_regions:
        bbox_px = region.get("bbox_px", [])
        if len(bbox_px) == 4:
            x, y, w, h = bbox_px
            region["bbox_pt"] = [
                round(x * scale, 2),
                round(y * scale, 2),
                round(w * scale, 2),
                round(h * scale, 2),
            ]

    if progress_callback:
        progress_callback("tesseract_check", 2, 3, "低信頼度領域を確認中...")

    # Step 3: Check for low-confidence regions and fall back to Tesseract
    low_conf_regions = [
        r for r in text_regions
        if r["confidence"] < 0.5
    ]

    tesseract_regions = []
    if low_conf_regions:
        if progress_callback:
            progress_callback("tesseract_fallback", 2, 3, "Tesseractフォールバック実行中...")
        tesseract_regions = recognize_text_tesseract(doc, page_num, dpi, page_image=page_image)
        # Merge: replace low-confidence PaddleOCR results with Tesseract results
        # where Tesseract has higher confidence for overlapping regions
        text_regions = _merge_ocr_results(text_regions, tesseract_regions)

    if progress_callback:
        progress_callback("ocr_complete", 3, 3, "OCR完了")

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
    progress_callback=None,
    pdf_path: str = "",
) -> Dict[str, Any]:
    """Run the full OCR pipeline on a page from base64-encoded PDF data or file path.

    This is the entry point called from the JSON-RPC handler.
    """
    import fitz

    if pdf_path and os.path.isfile(pdf_path):
        doc = fitz.open(pdf_path)
    else:
        pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        return run_ocr_pipeline(doc, page_num, dpi, progress_callback=progress_callback)
    finally:
        doc.close()


def run_layout_analysis_base64(
    pdf_data_b64: str,
    page_num: int,
    dpi: int = 300,
    password: str = "",
    pdf_path: str = "",
) -> Dict[str, Any]:
    """Run layout analysis only on a page from base64-encoded PDF data or file path.

    This is the entry point called from the JSON-RPC handler.
    """
    import fitz

    if pdf_path and os.path.isfile(pdf_path):
        doc = fitz.open(pdf_path)
    else:
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

    Uses page.get_text("dict") to get text with spans,
    then groups them into text regions (lines) with bounding boxes.

    Confidence is fixed at 1.0 for digital text extraction path.

    Returns a dict with text_regions, extraction_path, and page info.
    """
    page = doc[page_num]

    # Apply rotation correction to page rect
    rect = page.rect
    page_width_pt = round(rect.width, 2)
    page_height_pt = round(rect.height, 2)

    text_dict = page.get_text("dict")
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
    progress_callback=None,
    pdf_path: str = "",
) -> Dict[str, Any]:
    """Unified text extraction: tries digital path first, falls back to OCR.

    Returns a dict with extraction_path ("digital" or "ocr"), text_regions,
    and metadata about the extraction process.
    """
    import fitz

    if pdf_path and os.path.isfile(pdf_path):
        doc = fitz.open(pdf_path)
    else:
        pdf_bytes = __import__("base64").b64decode(pdf_data_b64)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    try:
        page = doc[page_num]
        rotation_deg = page.rotation

        if progress_callback:
            progress_callback("checking_text_layer", 0, 2, "テキストレイヤー確認中...")

        # Step 1: Check for text layer
        has_text = check_text_layer(doc, page_num)

        if has_text:
            if progress_callback:
                progress_callback("digital_extraction", 1, 2, "デジタルテキスト抽出中...")
            # Digital extraction path
            result = extract_text_digital(doc, page_num, rotation_deg)
            return result
        else:
            if progress_callback:
                progress_callback("ocr_fallback", 1, 2, "OCR処理開始...")
            # OCR fallback path
            ocr_result = run_ocr_pipeline(doc, page_num, dpi, progress_callback=progress_callback)
            ocr_result["extraction_path"] = "ocr"
            ocr_result["has_text_layer"] = False
            if progress_callback:
                progress_callback("extraction_complete", 2, 2, "テキスト抽出完了")
            return ocr_result
    finally:
        doc.close()
