"""
RedactSafe Python Worker
Stdin/stdout based JSON-RPC communication protocol.

Message format (each line is a complete JSON message):
  Request:  {"jsonrpc": "2.0", "id": <int>, "method": "<method>", "params": {...}}
  Response: {"jsonrpc": "2.0", "id": <int>, "result": {...}}          (success)
            {"jsonrpc": "2.0", "id": <int>, "error": {"code": <int>, "message": "..."}}  (error)

Progress notifications are sent to stderr as JSON lines:
  {"type": "progress", "request_id": <int>, "phase": "...", "current": <int>, "total": <int>, "message": "..."}
"""

import sys
import json
import hashlib
import base64
import io
import os
import secrets
import traceback
import tempfile


# ============================================================
# Progress Notification (via stderr)
# ============================================================

def send_progress(request_id: int, phase: str, current: int, total: int, message: str = ""):
    """Send a progress notification to stderr as a JSON line.

    The Rust side reads stderr and forwards these as Tauri events.
    Silently ignores write errors (stderr may be unavailable in some Windows setups).
    """
    try:
        notification = {
            "type": "progress",
            "request_id": request_id,
            "phase": phase,
            "current": current,
            "total": total,
            "message": message,
        }
        sys.stderr.write(json.dumps(notification, ensure_ascii=True) + "\n")
        sys.stderr.flush()
    except Exception:
        pass  # Progress is non-critical


# ============================================================
# Secure File Deletion
# ============================================================

# Track temp files for cleanup on worker shutdown
_managed_temp_files = []


def secure_delete_file(filepath):
    """Securely delete a file by overwriting with zeros/random data before unlinking.

    This prevents data recovery from disk sectors that held the file contents.
    """
    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            os.unlink(filepath)
            return

        # Pass 1: Overwrite with zeros
        with open(filepath, "wb") as f:
            f.write(b"\x00" * file_size)
            f.flush()
            os.fsync(f.fileno())

        # Pass 2: Overwrite with random data
        with open(filepath, "wb") as f:
            f.write(os.urandom(min(file_size, 1024 * 1024)))  # Up to 1MB of random data
            f.flush()
            os.fsync(f.fileno())

        # Pass 3: Overwrite with zeros again
        with open(filepath, "wb") as f:
            f.write(b"\x00" * file_size)
            f.flush()
            os.fsync(f.fileno())

        os.unlink(filepath)
    except OSError:
        # If secure deletion fails, at least try normal deletion
        try:
            os.unlink(filepath)
        except OSError:
            pass


def create_managed_temp_file(suffix=""):
    """Create a managed temp file that will be securely deleted on worker shutdown.

    Returns:
        Tuple of (file_descriptor, file_path)
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    _managed_temp_files.append(path)
    return fd, path


def cleanup_temp_files():
    """Securely delete all managed temp files (called on worker shutdown)."""
    for path in _managed_temp_files[:]:
        secure_delete_file(path)
        if path in _managed_temp_files:
            _managed_temp_files.remove(path)


from coord_utils import (
    pdf_point_to_pixel,
    pixel_to_pdf_point,
    bbox_pdf_point_to_pixel,
    bbox_pixel_to_pdf_point,
    rotate_bbox,
)
from ocr_pipeline import (
    run_ocr_pipeline_base64,
    run_layout_analysis_base64,
    extract_text_digital_base64,
    run_text_extraction,
)
from bbox_normalizer import normalize_ocr_results
from pii_detector import (
    detect_pii,
    detect_pii_base64,
    load_rules,
    load_custom_rules,
    merge_rules,
    validate_rules,
    check_regex_safety,
    load_rules_from_string,
)
from pdf_sanitizer import (
    sanitize_pdf,
    verify_safe_pdf,
    verify_safe_pdf_base64,
)


def _validate_page_num(page_num, min_val=0, max_val=None):
    """Validate page_num parameter. Raises ValueError if invalid."""
    if not isinstance(page_num, (int, float)) or page_num < min_val:
        raise ValueError("Invalid page number")
    if max_val is not None and page_num > max_val:
        raise ValueError("Invalid page number")


def _open_pdf(params: dict, allow_encrypted_detection: bool = False):
    """Open a PDF from base64-encoded data or file path. Returns (doc, pdf_bytes).

    Args:
        params: Dict with 'pdf_data' (base64) or 'pdf_path' (file path) and 'password' keys.
        allow_encrypted_detection: If True, return doc even when password
            is needed but not provided (for analyze_pdf to detect encryption).
    """
    import fitz

    pdf_path = params.get("pdf_path", "")
    pdf_data = params.get("pdf_data", "")
    password = params.get("password", "")

    if pdf_path and os.path.isfile(pdf_path):
        doc = fitz.open(pdf_path)
        pdf_bytes = open(pdf_path, "rb").read()
    else:
        pdf_bytes = base64.b64decode(pdf_data)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted and not doc.needs_pass:
        pass  # no password needed (owner password set but not required)
    elif doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            if allow_encrypted_detection:
                # Return the doc without authentication so caller can detect encryption
                return doc, pdf_bytes
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")
    return doc, pdf_bytes


def handle_analyze_pdf(params: dict) -> dict:
    """Analyze PDF metadata: encryption, signatures, page count, etc."""
    import fitz

    doc, pdf_bytes = _open_pdf(params, allow_encrypted_detection=True)

    try:
        is_encrypted = doc.is_encrypted
        needs_pass = doc.needs_pass
        page_count = len(doc) if not needs_pass else 0

        # Check for digital signatures (skip if encrypted)
        has_signatures = False
        signature_names = []
        if not needs_pass:
            for page_num in range(page_count):
                page = doc[page_num]
                for widget in page.widgets():
                    if widget.field_type_string == "Signature":
                        has_signatures = True
                        signature_names.append(widget.field_name or f"sig_page{page_num + 1}")
                # Also check for signature annotations
                for annot in page.annots() or []:
                    if annot.type[0] == fitz.PDF_ANNOT_WIDGET:
                        # Already checked via widgets
                        pass

            # Additional check: look for signature in document catalog
            try:
                catalog = doc.pdf_catalog()
                if catalog is not None:
                    acro_form = catalog.get("AcroForm")
                    if acro_form is not None:
                        sig_fields = acro_form.get("Fields", [])
                        for field_ref in sig_fields:
                            field = doc.xref_object(field_ref)
                            if "Sig" in field:
                                has_signatures = True
            except Exception:
                pass

        # Compute SHA-256 hash of source file
        sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # Get metadata (may be None for encrypted PDFs)
        metadata = doc.metadata or {}
        title = metadata.get("title", "") or ""
        author = metadata.get("author", "") or ""
        creator = metadata.get("creator", "") or ""

        # Get page dimensions (skip if encrypted)
        page_info = []
        if not needs_pass:
            for i in range(page_count):
                p = doc[i]
                page_info.append({
                    "page": i + 1,
                    "width_pt": round(p.rect.width, 2),
                    "height_pt": round(p.rect.height, 2),
                    "rotation_deg": p.rotation,
                })

        return {
            "is_encrypted": is_encrypted,
            "needs_pass": needs_pass,
            "has_signatures": has_signatures,
            "signature_names": signature_names,
            "page_count": page_count,
            "sha256": sha256_hash,
            "metadata": {
                "title": title,
                "author": author,
                "creator": creator,
            },
            "pages": page_info,
        }
    finally:
        doc.close()


def handle_decrypt_pdf(params: dict) -> dict:
    """Attempt to decrypt a PDF with a password. Returns analysis result or error."""
    import fitz

    doc, pdf_bytes = _open_pdf(params)

    try:
        if not doc.is_encrypted:
            return {
                "success": True,
                "is_encrypted": False,
                "needs_pass": False,
                "page_count": len(doc),
                "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            }

        # Already authenticated in _open_pdf
        page_count = len(doc)
        sha256_hash = hashlib.sha256(pdf_bytes).hexdigest()

        page_info = []
        for i in range(page_count):
            p = doc[i]
            page_info.append({
                "page": i + 1,
                "width_pt": round(p.rect.width, 2),
                "height_pt": round(p.rect.height, 2),
                "rotation_deg": p.rotation,
            })

        return {
            "success": True,
            "is_encrypted": True,
            "needs_pass": False,
            "page_count": page_count,
            "sha256": sha256_hash,
            "pages": page_info,
        }
    finally:
        doc.close()


def send_response(msg_id: int, result: object = None, error: dict = None):
    """Send a JSON-RPC response to stdout."""
    response = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_ping(params: dict) -> dict:
    """Handle ping command - returns pong with echo of the input message."""
    message = params.get("message", "")
    return {"pong": True, "message": message}


def handle_get_version(params: dict) -> dict:
    """Return worker version and available methods."""
    return {
        "version": "1.0.0",
        "methods": list(HANDLERS.keys()),
    }


def handle_run_ocr(params: dict, request_id: int = 0) -> dict:
    """Run OCR pipeline on a single page of a PDF."""
    pdf_path = params.get("pdf_path", "")
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    dpi = params.get("dpi", 300)
    password = params.get("password", "")

    _validate_page_num(page_num)

    if not pdf_path and not pdf_data_b64:
        raise ValueError("pdf_path or pdf_data is required")

    def progress_cb(phase, current, total, message=""):
        send_progress(request_id, phase, current, total, message)

    return run_ocr_pipeline_base64(
        pdf_data_b64, page_num, dpi, password, progress_callback=progress_cb,
        pdf_path=pdf_path,
    )


def handle_run_layout_analysis(params: dict) -> dict:
    """Run layout analysis on a single page of a PDF."""
    pdf_path = params.get("pdf_path", "")
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    dpi = params.get("dpi", 300)
    password = params.get("password", "")

    _validate_page_num(page_num)

    if not pdf_path and not pdf_data_b64:
        raise ValueError("pdf_path or pdf_data is required")

    return run_layout_analysis_base64(
        pdf_data_b64, page_num, dpi, password, pdf_path=pdf_path
    )


def handle_extract_text_digital(params: dict) -> dict:
    """Extract text from a digital PDF page using PyMuPDF text layer."""
    pdf_path = params.get("pdf_path", "")
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    password = params.get("password", "")

    _validate_page_num(page_num)

    if not pdf_path and not pdf_data_b64:
        raise ValueError("pdf_path or pdf_data is required")

    # extract_text_digital_base64 doesn't support pdf_path yet, convert if needed
    if pdf_path and not pdf_data_b64:
        import base64 as b64mod
        with open(pdf_path, "rb") as f:
            pdf_data_b64 = b64mod.b64encode(f.read()).decode("ascii")

    return extract_text_digital_base64(
        pdf_data_b64, page_num, password
    )


def handle_run_text_extraction(params: dict, request_id: int = 0) -> dict:
    """Unified text extraction: digital path first, OCR fallback."""
    pdf_path = params.get("pdf_path", "")
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    dpi = params.get("dpi", 300)
    password = params.get("password", "")

    _validate_page_num(page_num)

    if not pdf_path and not pdf_data_b64:
        raise ValueError("pdf_path or pdf_data is required")

    def progress_cb(phase, current, total, message=""):
        send_progress(request_id, phase, current, total, message)

    return run_text_extraction(
        pdf_data_b64, page_num, dpi, password, progress_callback=progress_cb,
        pdf_path=pdf_path,
    )


def handle_pdf_point_to_pixel(params: dict) -> dict:
    """Convert PDF point coordinates to pixel coordinates."""
    x = params["x_pt"]
    y = params["y_pt"]
    dpi = params.get("dpi", 300.0)
    x_px, y_px = pdf_point_to_pixel(x, y, dpi)
    return {"x_px": x_px, "y_px": y_px}


def handle_pixel_to_pdf_point(params: dict) -> dict:
    """Convert pixel coordinates to PDF point coordinates."""
    x = params["x_px"]
    y = params["y_px"]
    dpi = params.get("dpi", 300.0)
    x_pt, y_pt = pixel_to_pdf_point(x, y, dpi)
    return {"x_pt": x_pt, "y_pt": y_pt}


def handle_bbox_pdf_to_pixel(params: dict) -> dict:
    """Convert a bounding box from PDF points to pixels."""
    bbox = params["bbox"]
    dpi = params.get("dpi", 300.0)
    result = bbox_pdf_point_to_pixel(bbox, dpi)
    return {"bbox_px": result}


def handle_bbox_pixel_to_pdf(params: dict) -> dict:
    """Convert a bounding box from pixels to PDF points."""
    bbox = params["bbox"]
    dpi = params.get("dpi", 300.0)
    result = bbox_pixel_to_pdf_point(bbox, dpi)
    return {"bbox_pt": result}


def handle_rotate_bbox(params: dict) -> dict:
    """Correct a bounding box for page rotation."""
    bbox = params["bbox"]
    rotation_deg = params["rotation_deg"]
    page_width_pt = params["page_width_pt"]
    page_height_pt = params["page_height_pt"]
    result = rotate_bbox(bbox, rotation_deg, page_width_pt, page_height_pt)
    return {"bbox": result}


def handle_normalize_bboxes(params: dict) -> dict:
    """Normalize OCR bounding boxes: convert to PDF points, merge lines, correct rotation."""
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    regions = params.get("regions", [])
    dpi = params.get("dpi", 300.0)
    rotation_deg = params.get("rotation_deg", 0)
    password = params.get("password", "")
    merge_lines = params.get("merge_lines", True)

    _validate_page_num(page_num)

    if not pdf_data_b64:
        raise ValueError("pdf_data is required")
    if not regions:
        raise ValueError("regions is required")

    return normalize_ocr_results(
        pdf_data_b64, page_num, regions, dpi, rotation_deg, password, merge_lines
    )


def handle_detect_pii(params: dict) -> dict:
    """Detect PII in text regions using regex-based rules + MeCab name detection."""
    text_regions = params.get("text_regions", [])
    enabled_types = params.get("enabled_types", None)
    rules_path = params.get("rules_path", None)
    enable_name_detection = params.get("enable_name_detection", True)
    custom_rules_dir = params.get("custom_rules_dir", None)

    if not text_regions:
        raise ValueError("text_regions is required")

    detections = detect_pii(
        text_regions,
        rules_path=rules_path,
        enabled_types=enabled_types,
        enable_name_detection=enable_name_detection,
        custom_rules_dir=custom_rules_dir,
    )
    return {
        "detections": detections,
        "region_count": len(text_regions),
        "detection_count": len(detections),
    }


def handle_detect_pii_pdf(params: dict, request_id: int = 0) -> dict:
    """Detect PII from a PDF page (combines text extraction + detection)."""
    pdf_path = params.get("pdf_path", "")
    pdf_data_b64 = params.get("pdf_data", "")
    page_num = params.get("page_num", 0)
    enabled_types = params.get("enabled_types", None)
    rules_path = params.get("rules_path", None)
    password = params.get("password", "")
    enable_name_detection = params.get("enable_name_detection", True)
    custom_rules_dir = params.get("custom_rules_dir", None)

    _validate_page_num(page_num)

    if not pdf_path and not pdf_data_b64:
        raise ValueError("pdf_path or pdf_data is required")

    def progress_cb(phase, current, total, message=""):
        send_progress(request_id, phase, current, total, message)

    return detect_pii_base64(
        pdf_data_b64,
        page_num,
        rules_path=rules_path,
        enabled_types=enabled_types,
        password=password,
        enable_name_detection=enable_name_detection,
        custom_rules_dir=custom_rules_dir,
        progress_callback=progress_cb,
        pdf_path=pdf_path,
    )


def handle_load_detection_rules(params: dict) -> dict:
    """Load detection rules from YAML file."""
    rules_path = params.get("rules_path", None)
    rules = load_rules(rules_path)
    return {
        "rules": rules,
        "rule_count": len(rules),
    }


def handle_load_custom_rules(params: dict) -> dict:
    """Load custom rules from the custom rules directory."""
    rules_dir = params.get("rules_dir", None)
    rules, errors = load_custom_rules(rules_dir)
    return {
        "rules": rules,
        "rule_count": len(rules),
        "errors": errors,
    }


def handle_load_all_rules(params: dict) -> dict:
    """Load and merge bundled + custom rules."""
    rules_path = params.get("rules_path", None)
    custom_rules_dir = params.get("custom_rules_dir", None)
    bundled_rules = load_rules(rules_path)
    custom_rules, errors = load_custom_rules(custom_rules_dir)
    merged = merge_rules(bundled_rules, custom_rules)
    return {
        "rules": merged,
        "rule_count": len(merged),
        "bundled_count": len(bundled_rules),
        "custom_count": len(custom_rules),
        "errors": errors,
    }


def handle_validate_rules(params: dict) -> dict:
    """Validate detection rules against the schema."""
    import json as _json

    rules_content = params.get("rules_content", "")
    format_hint = params.get("format", None)

    if not rules_content:
        raise ValueError("rules_content is required")

    rules = load_rules_from_string(rules_content, format_hint=format_hint)
    is_valid, errors = validate_rules(rules)
    return {
        "is_valid": is_valid,
        "rules": rules,
        "rule_count": len(rules),
        "errors": errors,
    }


def handle_check_regex_safety(params: dict) -> dict:
    """Check a regex pattern for catastrophic backtracking risks."""
    pattern = params.get("pattern", "")
    if not pattern:
        raise ValueError("pattern is required")

    is_safe, warning = check_regex_safety(pattern)
    return {
        "is_safe": is_safe,
        "warning": warning,
    }


def handle_finalize_masking(params: dict, request_id: int = 0) -> dict:
    """Finalize masking: rasterize PDF pages at 300dpi, burn black rectangles, regenerate PDF.

    Args:
        params: {
            pdf_data: base64-encoded source PDF,
            pages: [{page_num, width_pt, height_pt, rotation_deg, regions: [{bbox, enabled}]}],
            dpi: rasterization DPI (default 300),
            margin_pt: bbox margin in PDF points (default 3),
            password: optional PDF password
        }
        request_id: for progress reporting

    Returns:
        {pdf_data: base64-encoded finalized PDF, pages_processed: int, regions_masked: int}
    """
    import fitz
    from PIL import Image, ImageDraw

    pdf_data_b64 = params.get("pdf_data", "")
    pages_info = params.get("pages", [])
    dpi = params.get("dpi", 300)
    margin_pt = params.get("margin_pt", 3)
    password = params.get("password", "")

    if not pdf_data_b64:
        raise ValueError("pdf_data is required")
    if not pages_info:
        raise ValueError("pages is required")

    pdf_bytes = base64.b64decode(pdf_data_b64)
    src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if src_doc.is_encrypted and src_doc.needs_pass:
        if not src_doc.authenticate(password):
            src_doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")

    total_pages = len(pages_info)
    total_regions_masked = 0

    def _transform_bbox_for_rotation(bbox, rotation_deg, page_w_pt, page_h_pt):
        """Transform bbox from unrotated PDF point space to rotated visual space.

        When PyMuPDF renders a rotated page via get_pixmap, the output image
        is in the rotated visual coordinate space. Our stored bboxes are in
        the unrotated MediaBox space, so we need to transform them.
        """
        if rotation_deg == 0:
            return bbox

        x, y, w, h = bbox

        if rotation_deg == 90:
            # 90° CW: original → rotated
            return [page_h_pt - y - h, x, h, w]
        elif rotation_deg == 180:
            return [page_w_pt - x - w, page_h_pt - y - h, w, h]
        elif rotation_deg == 270:
            return [y, page_w_pt - x - w, h, w]
        return bbox

    try:
        # Create new output PDF
        out_doc = fitz.open()

        for page_info in pages_info:
            page_num = page_info.get("page_num", 0)  # 0-indexed
            width_pt = page_info.get("width_pt", 595.28)
            height_pt = page_info.get("height_pt", 841.89)
            rotation_deg = page_info.get("rotation_deg", 0)
            regions = page_info.get("regions", [])

            phase_msg = f"ページ {page_num + 1}/{total_pages} を処理中..."
            send_progress(request_id, "rasterizing", page_num + 1, total_pages, phase_msg)

            # Step 1: Rasterize page at specified DPI
            page = src_doc[page_num]
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data)).convert("RGB")

            send_progress(request_id, "burning_rectangles", page_num + 1, total_pages,
                          f"ページ {page_num + 1}/{total_pages} の黒塗り焼き込み中...")

            # Step 2: Draw black rectangles for enabled regions
            draw = ImageDraw.Draw(img)
            page_regions_masked = 0

            for region in regions:
                if not region.get("enabled", False):
                    continue

                bbox = region.get("bbox", [0, 0, 0, 0])
                # bbox is [x, y, width, height] in unrotated PDF points
                x_pt, y_pt, w_pt, h_pt = bbox

                # Transform bbox to rotated visual space if needed
                x_pt, y_pt, w_pt, h_pt = _transform_bbox_for_rotation(
                    [x_pt, y_pt, w_pt, h_pt], rotation_deg, width_pt, height_pt
                )

                # Apply margin (clamp to non-negative)
                mx = max(0, x_pt - margin_pt)
                my = max(0, y_pt - margin_pt)
                mw = w_pt + 2 * margin_pt
                mh = h_pt + 2 * margin_pt

                # Convert from PDF points to pixels
                scale = dpi / 72.0
                x_px = mx * scale
                y_px = my * scale
                w_px = mw * scale
                h_px = mh * scale

                # Draw filled black rectangle
                draw.rectangle(
                    [x_px, y_px, x_px + w_px, y_px + h_px],
                    fill=(0, 0, 0)
                )
                page_regions_masked += 1

            total_regions_masked += page_regions_masked

            send_progress(request_id, "adding_page", page_num + 1, total_pages,
                          f"ページ {page_num + 1}/{total_pages} をPDFに追加中...")

            # Step 3: Convert image back to PDF page
            # Get page dimensions in points for the output page
            page_w_pt = width_pt
            page_h_pt = height_pt

            # Handle rotation: if the page is rotated, swap dimensions
            if rotation_deg in (90, 270):
                page_w_pt, page_h_pt = height_pt, width_pt

            # Convert image to PNG bytes for insertion
            img_bytes_io = io.BytesIO()
            img.save(img_bytes_io, format="PNG")
            img_bytes = img_bytes_io.getvalue()

            # Create a new page with the correct dimensions
            out_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)

            # Insert the image, scaled to fill the page
            img_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            out_page.insert_image(img_rect, stream=img_bytes)

            # Explicitly free memory
            del img
            del draw
            img_bytes_io.close()
            del img_bytes
            pix = None  # Help GC

        # Step 4: Sanitize hidden data
        send_progress(request_id, "sanitizing", total_pages, total_pages, "hidden dataを除去中...")
        sanitize_result = sanitize_pdf(out_doc, set_perms=False)

        # Step 5: Save output PDF to bytes (with permissions)
        send_progress(request_id, "saving", total_pages, total_pages, "安全PDFを生成中...")
        import tempfile
        import os

        # Save to temp file first (needed for encryption/permissions)
        tmp_fd, tmp_path = create_managed_temp_file(suffix=".pdf")
        os.close(tmp_fd)
        try:
            # Set copy-prevention permissions via encryption
            # Owner password is generated at runtime and held only in memory
            owner_pw = secrets.token_urlsafe(32)
            perm_flags = (
                fitz.PDF_PERM_PRINT          # Allow printing (image-based only)
                | fitz.PDF_PERM_ACCESSIBILITY  # Allow accessibility
            )
            out_doc.save(
                tmp_path,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=owner_pw,
                user_pw="",
                permissions=perm_flags,
                garbage=4,
                deflate=True,
            )
            out_doc.close()
            out_doc = None
            # Explicitly delete password from memory
            del owner_pw

            # Read back the saved file
            with open(tmp_path, "rb") as f:
                out_bytes = f.read()
        finally:
            secure_delete_file(tmp_path)
            if tmp_path in _managed_temp_files:
                _managed_temp_files.remove(tmp_path)

        # Step 6: Verify the output PDF is safe
        send_progress(request_id, "verifying", total_pages, total_pages, "安全PDFを検証中...")
        verify_doc = fitz.open(stream=out_bytes, filetype="pdf")
        try:
            verification = verify_safe_pdf(verify_doc)
        finally:
            verify_doc.close()

        # Step 7: If verification fails, discard the output and raise error
        if not verification["valid"]:
            # Collect all issues for the error message
            all_issues = []
            for check_name in ["text_check", "hidden_data_check", "metadata_check", "object_scan"]:
                check = verification.get(check_name, {})
                if not check.get("passed", True):
                    for issue in check.get("issues", []):
                        all_issues.append(f"[{issue.get('type', '?')}] {issue.get('detail', '?')}")

            error_detail = "; ".join(all_issues[:10])  # Limit to first 10 issues
            raise ValueError(f"VERIFICATION_FAILED: {error_detail}")

        result_pdf_b64 = base64.b64encode(out_bytes).decode("ascii")

        return {
            "pdf_data": result_pdf_b64,
            "pages_processed": total_pages,
            "regions_masked": total_regions_masked,
            "sanitization": sanitize_result,
            "verification": verification,
        }
    finally:
        src_doc.close()


def handle_detect_names(params: dict) -> dict:
    """Detect person names in text regions using MeCab morphological analysis."""
    from name_detector import detect_names

    text_regions = params.get("text_regions", [])
    enabled_types = params.get("enabled_types", None)

    if not text_regions:
        raise ValueError("text_regions is required")

    detections = detect_names(text_regions, enabled_types=enabled_types)
    return {
        "detections": detections,
        "detection_count": len(detections),
    }


def handle_verify_safe_pdf(params: dict) -> dict:
    """Verify that a finalized PDF is safe (no text, no hidden data).

    Args:
        params: {pdf_data: base64-encoded PDF data}

    Returns:
        Verification results dictionary with valid, text_check, hidden_data_check, etc.
    """
    pdf_data_b64 = params.get("pdf_data", "")
    if not pdf_data_b64:
        raise ValueError("pdf_data is required")

    return verify_safe_pdf_base64(pdf_data_b64)


# Method dispatch table
HANDLERS = {
    "ping": handle_ping,
    "get_version": handle_get_version,
    "pdf_point_to_pixel": handle_pdf_point_to_pixel,
    "pixel_to_pdf_point": handle_pixel_to_pdf_point,
    "bbox_pdf_to_pixel": handle_bbox_pdf_to_pixel,
    "bbox_pixel_to_pdf": handle_bbox_pixel_to_pdf,
    "rotate_bbox": handle_rotate_bbox,
    "analyze_pdf": handle_analyze_pdf,
    "decrypt_pdf": handle_decrypt_pdf,
    "run_ocr": handle_run_ocr,
    "run_layout_analysis": handle_run_layout_analysis,
    "extract_text_digital": handle_extract_text_digital,
    "run_text_extraction": handle_run_text_extraction,
    "normalize_bboxes": handle_normalize_bboxes,
    "detect_pii": handle_detect_pii,
    "detect_pii_pdf": handle_detect_pii_pdf,
    "load_detection_rules": handle_load_detection_rules,
    "load_custom_rules": handle_load_custom_rules,
    "load_all_rules": handle_load_all_rules,
    "validate_rules": handle_validate_rules,
    "check_regex_safety": handle_check_regex_safety,
    "detect_names": handle_detect_names,
    "finalize_masking": handle_finalize_masking,
    "verify_safe_pdf": handle_verify_safe_pdf,
}


def process_message(line: str):
    """Parse and dispatch a single JSON-RPC message."""
    try:
        request = json.loads(line.strip())
    except json.JSONDecodeError as e:
        send_response(0, error={
            "code": -32700,
            "message": f"Parse error: {e}",
        })
        return

    msg_id = request.get("id", 0)
    method = request.get("method", "")
    params = request.get("params", {})

    if method not in HANDLERS:
        send_response(msg_id, error={
            "code": -32601,
            "message": f"Method not found: {method}",
        })
        return

    try:
        # Handlers that support progress reporting accept request_id
        import inspect
        sig = inspect.signature(HANDLERS[method])
        if "request_id" in sig.parameters:
            result = HANDLERS[method](params, request_id=msg_id)
        else:
            result = HANDLERS[method](params)
        send_response(msg_id, result=result)
    except Exception as e:
        # Log traceback to stderr for debugging, but don't expose it to the client
        sys.stderr.write(f"Handler error for {method}: {traceback.format_exc()}")
        sys.stderr.flush()
        send_response(msg_id, error={
            "code": -32603,
            "message": "Internal error",
        })


def main():
    """Main loop: read JSON-RPC messages from stdin, write responses to stdout."""
    # Signal ready state
    try:
        sys.stderr.write("RedactSafe Python Worker started\n")
        sys.stderr.flush()
    except Exception:
        pass

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            process_message(line)
    finally:
        # Clean up all managed temp files on shutdown
        cleanup_temp_files()


if __name__ == "__main__":
    main()
