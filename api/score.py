"""POST /api/score — Vercel Python function (stdlib handler, no framework)."""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import extract  # noqa: E402
from scoring import decide, skipped_decision  # noqa: E402

MAX_BYTES, MAX_TURNS = 50_000, 100


def _bad(detail: str):
    return None, 400, {"error": "invalid_input", "detail": detail}


def validate(raw: bytes) -> tuple[dict | None, int, dict | None]:
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, 400, {"error": "invalid_json"}
    if not isinstance(body, dict):
        return None, 400, {"error": "invalid_input", "detail": "body must be a JSON object"}
    if not isinstance(body.get("lead_id"), str) or not body["lead_id"].strip():
        return _bad("lead_id")
    conv = body.get("conversation")
    if not isinstance(conv, list) or not conv or not all(isinstance(t, dict) and isinstance(t.get("text"), str) for t in conv):
        return _bad("conversation")
    if len(conv) > MAX_TURNS:
        return None, 413, {"error": "payload_too_large"}
    return body, 200, None


def handle(raw: bytes) -> tuple[int, dict, dict]:
    start = time.monotonic()
    body, status, err = validate(raw)
    if err:
        return status, err, {}
    try:
        conv = body["conversation"]
        if not any(t.get("role") == "lead" and t["text"].strip() for t in conv):
            decision, mode = skipped_decision(), "skipped"
        else:
            facts, mode = extract(conv)
            decision = decide(facts, fallback=(mode == "fallback"))
        out = {"lead_id": body["lead_id"], **decision}
    except Exception as e:
        print(json.dumps({"event": "internal_error", "error": type(e).__name__}))
        return 500, {"error": "internal_error"}, {}
    print(json.dumps({"lead_id": body["lead_id"][:64], "mode": mode, "tier": out["tier"],
                      "ms": round((time.monotonic() - start) * 1000)}))
    return 200, out, {"X-Scoring-Mode": mode}


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict, headers: dict | None = None):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length > MAX_BYTES:
            return self._send(413, {"error": "payload_too_large"})
        if length <= 0:
            return self._send(400, {"error": "invalid_json"})
        self._send(*handle(self.rfile.read(length)))

    def _not_allowed(self):
        self._send(405, {"error": "method_not_allowed"}, {"Allow": "POST"})

    do_GET = do_PUT = do_DELETE = do_PATCH = _not_allowed
