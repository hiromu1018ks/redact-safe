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
        "version": "0.1.0",
        "methods": list(HANDLERS.keys()),
    }


# Method dispatch table
HANDLERS = {
    "ping": handle_ping,
    "get_version": handle_get_version,
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
