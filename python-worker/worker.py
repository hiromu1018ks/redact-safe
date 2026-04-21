"""
RedactSafe Python Worker
Stdin/stdout based JSON-RPC communication protocol.

Message format (each line is a complete JSON message):
  Request:  {"jsonrpc": "2.0", "id": <int>, "method": "<method>", "params": {...}}
  Response: {"jsonrpc": "2.0", "id": <int>, "result": {...}}          (success)
            {"jsonrpc": "2.0", "id": <int>, "error": {"code": <int>, "message": "..."}}  (error)
"""

import sys
import json
import hashlib
import base64
import traceback
from coord_utils import (
    pdf_point_to_pixel,
    pixel_to_pdf_point,
    bbox_pdf_point_to_pixel,
    bbox_pixel_to_pdf_point,
    rotate_bbox,
)


def _open_pdf(params: dict):
    """Open a PDF from base64-encoded data. Returns (doc, pdf_bytes)."""
    import fitz

    pdf_data = params.get("pdf_data", "")
    password = params.get("password", "")
    pdf_bytes = base64.b64decode(pdf_data)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted and not doc.needs_pass:
        pass  # no password needed (owner password set but not required)
    elif doc.is_encrypted and doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("PDF_PASSWORD_INCORRECT")
    return doc, pdf_bytes


def handle_analyze_pdf(params: dict) -> dict:
    """Analyze PDF metadata: encryption, signatures, page count, etc."""
    import fitz

    doc, pdf_bytes = _open_pdf(params)

    try:
        is_encrypted = doc.is_encrypted
        needs_pass = doc.needs_pass
        page_count = len(doc)

        # Check for digital signatures
        has_signatures = False
        signature_names = []
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

        # Get metadata
        metadata = doc.metadata
        title = metadata.get("title", "") or ""
        author = metadata.get("author", "") or ""
        creator = metadata.get("creator", "") or ""

        # Get page dimensions for first page
        first_page = doc[0]
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
        "version": "0.3.0",
        "methods": list(HANDLERS.keys()),
    }


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
        result = HANDLERS[method](params)
        send_response(msg_id, result=result)
    except Exception as e:
        send_response(msg_id, error={
            "code": -32603,
            "message": f"Internal error: {e}",
            "data": traceback.format_exc(),
        })


def main():
    """Main loop: read JSON-RPC messages from stdin, write responses to stdout."""
    # Signal ready state
    sys.stderr.write("RedactSafe Python Worker started\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        process_message(line)


if __name__ == "__main__":
    main()
