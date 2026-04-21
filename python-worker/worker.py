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
import traceback
from coord_utils import (
    pdf_point_to_pixel,
    pixel_to_pdf_point,
    bbox_pdf_point_to_pixel,
    bbox_pixel_to_pdf_point,
    rotate_bbox,
)


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
        "version": "0.2.0",
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
