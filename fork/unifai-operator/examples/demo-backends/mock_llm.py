"""Tiny OpenAI-compatible fake (chat completions + responses, JSON and SSE) answering a constant text. For tests only."""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TEXT = "pong from the demo mock LLM"
# Tokens the endpoint reports per call (the token ceiling of a turn counts them). Default: a few tokens, as a real tiny answer.
USAGE = int(os.environ.get("MOCK_USAGE_TOKENS", "6"))


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            return self._send(200, {"object": "list", "data": [{"id": "mock-model", "object": "model"}]})
        self._send(200, {"status": "ok"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        model, stream, now = req.get("model", "mock-model"), req.get("stream"), int(time.time())
        if self.path.endswith("/chat/completions"):
            if stream:
                ch = {"id": "c1", "object": "chat.completion.chunk", "created": now, "model": model,
                      "choices": [{"index": 0, "delta": {"role": "assistant", "content": TEXT}, "finish_reason": None}]}
                end = {**ch, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                chunks = [ch, end]
                if (req.get("stream_options") or {}).get("include_usage"):  # asked for when a token ceiling is set
                    chunks.append({**ch, "choices": [], "usage": {"prompt_tokens": USAGE - 5, "completion_tokens": 5, "total_tokens": USAGE}})
                return self._send(200, "".join(f"data: {json.dumps(x)}\n\n" for x in chunks).encode() + b"data: [DONE]\n\n", "text/event-stream")
            return self._send(200, {"id": "c1", "object": "chat.completion", "created": now, "model": model,
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": TEXT}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": USAGE - 5, "completion_tokens": 5, "total_tokens": USAGE}})
        if self.path.endswith("/responses"):
            resp = {"id": "r1", "object": "response", "created_at": now, "model": model, "status": "completed", "output": [{
                "type": "message", "id": "m1", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": TEXT, "annotations": []}]}],
                "usage": {"input_tokens": USAGE - 5, "output_tokens": 5, "total_tokens": USAGE}}
            if stream:
                ev = [("response.created", {"type": "response.created", "response": {**resp, "status": "in_progress", "output": []}}),
                      ("response.completed", {"type": "response.completed", "response": resp})]
                return self._send(200, "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in ev).encode(), "text/event-stream")
            return self._send(200, resp)
        self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
