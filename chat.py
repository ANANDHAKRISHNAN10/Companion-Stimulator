"""
Vercel Python Serverless Function (/api/chat) for Companion Simulator.
Enforces strict per-user session isolation so every visitor's chat history
and memories remain 100% private.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import girlfriend_sim as sim

_TMP_DIR = tempfile.gettempdir()


def _configure_isolated_session(session_id, state_dict):
    raw_sid = re.sub(r"[^a-zA-Z0-9_\-]", "", str(session_id or ""))[:64]
    if not raw_sid or len(raw_sid) < 8:
        raw_sid = uuid.uuid4().hex
    sid_hash = hashlib.sha256(raw_sid.encode("utf-8")).hexdigest()[:24]
    sim.MEMORY_DB_FILE = os.path.join(_TMP_DIR, f"companion_memories_{sid_hash}.db")
    sim.SAVE_FILE = os.path.join(_TMP_DIR, f"partner_save_{sid_hash}.json")
    sim.DIARY_FILE = os.path.join(_TMP_DIR, f"relationship_diary_{sid_hash}.md")
    sim.last_topic = state_dict.get("last_topic") if isinstance(state_dict, dict) else None
    sim.recent_topics = list(state_dict.get("recent_topics", [])) if isinstance(state_dict, dict) else []
    return sid_hash


class handler(BaseHTTPRequestHandler):
    def _send_privacy_and_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id")
        self.send_header("Cache-Control", "private, no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_privacy_and_cors_headers()
        self.end_headers()

    def do_GET(self):
        status = sim.get_connection_status()
        data = json.dumps({"status": "ok", "isolation": "strict_per_session", "connection": status}).encode("utf-8")
        self.send_response(200)
        self._send_privacy_and_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw)
            user_msg = str(body.get("user_message", "")).strip()
            chat_history = body.get("chat_history", [])
            saved_memories = body.get("saved_memories", {})
            state = body.get("state") or sim.create_new_state(interactive=False)
            session_id = body.get("session_id") or self.headers.get("X-Session-Id") or state.get("session_id")

            with sim._STATE_LOCK:
                _configure_isolated_session(session_id, state)
                sim.clear_all_saved_memories()
                if isinstance(saved_memories, dict) and saved_memories:
                    sim.sync_dict_to_memory_db(saved_memories)
                reply, delta, new_mood = sim.get_companion_reply(
                    user_msg, chat_history, saved_memories, state=state, return_metadata=True
                )
                conn = sim.get_connection_status()
                try:
                    if os.path.exists(sim.MEMORY_DB_FILE):
                        os.remove(sim.MEMORY_DB_FILE)
                except OSError:
                    pass

            payload = {
                "reply": reply,
                "delta": delta,
                "mood": new_mood,
                "memories": saved_memories,
                "isolation": "private_session",
                "connection": conn,
            }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self._send_privacy_and_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            err = json.dumps({"error": type(exc).__name__}).encode("utf-8")
            self.send_response(500)
            self._send_privacy_and_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(err)
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import girlfriend_sim as sim
sim.MEMORY_DB_FILE = "/tmp/companion_memories.db"
sim.SAVE_FILE = "/tmp/partner_save.json"
sim.DIARY_FILE = "/tmp/relationship_diary.md"


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
