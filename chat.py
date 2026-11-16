"""
Vercel Python Serverless Function (/api/chat) for Companion Simulator.
Reads GEMINI_API_KEY or OPENAI_API_KEY from Vercel Environment Variables.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import girlfriend_sim as sim


class handler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw)
            user_msg = str(body.get("user_message", "")).strip()
            chat_history = body.get("chat_history", [])
            saved_memories = body.get("saved_memories", {})
            state = body.get("state") or sim.create_new_state(interactive=False)

            reply, delta, new_mood = sim.get_companion_reply(
                user_msg,
                chat_history,
                saved_memories,
                state=state,
                return_metadata=True,
            )
            payload = {
                "reply": reply,
                "delta": delta,
                "mood": new_mood,
                "memories": saved_memories,
                "connection": sim.get_connection_status(),
            }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            err = json.dumps({"error": type(exc).__name__}).encode("utf-8")
            self.send_response(500)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(err)
