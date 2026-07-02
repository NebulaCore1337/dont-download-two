#!/usr/bin/env python3
"""HTTP-сервер с API для дашборда."""
import http.server
import json
import os
import sys
from pathlib import Path

PORT = 8080
DIR = Path(__file__).parent
CONFIG_FILE = DIR / "config.json"

os.chdir(DIR)


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text("utf-8"))
    return {}


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/config":
            self._json_response(load_config())
        elif self.path == "/api/log":
            log_file = DIR / "auto_reply_log.json"
            if log_file.exists():
                try:
                    logs = json.loads(log_file.read_text("utf-8"))
                    self._json_response(logs[-50:])
                except Exception:
                    self._json_response([])
            else:
                self._json_response([])
        elif self.path == "/api/memory":
            mem_dir = DIR / "memory"
            stats = {"total": 0, "users": []}
            if mem_dir.exists():
                for f in mem_dir.glob("*.json"):
                    try:
                        entries = json.loads(f.read_text("utf-8"))
                        stats["total"] += len(entries)
                        stats["users"].append({"key": f.stem, "count": len(entries)})
                    except Exception:
                        pass
            self._json_response(stats)
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/config":
            cfg = load_config()
            cfg.update(body)
            save_config(cfg)
            self._json_response({"ok": True})
        elif self.path == "/api/config/reset":
            save_config(json.loads((DIR / "config.json").read_text("utf-8")))
            self._json_response({"ok": True})
        elif self.path == "/api/mute":
            cfg = load_config()
            cfg["group_muted"] = body.get("muted", False)
            save_config(cfg)
            self._json_response({"ok": True, "muted": cfg["group_muted"]})
        elif self.path == "/api/mode":
            cfg = load_config()
            cfg["mode"] = body.get("mode")
            save_config(cfg)
            self._json_response({"ok": True, "mode": cfg["mode"]})
        elif self.path == "/api/contact":
            cfg = load_config()
            contacts = cfg.get("ai_contacts", {})
            key = body.get("key")
            if body.get("delete") and key:
                contacts.pop(key, None)
            elif key:
                contacts[key] = {
                    "name": body.get("name", ""),
                    "relation": body.get("relation", ""),
                    "notes": body.get("notes", ""),
                }
            cfg["ai_contacts"] = contacts
            save_config(cfg)
            self._json_response({"ok": True})
        else:
            self.send_error(404)

    def _json_response(self, data):
        out = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(out))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(out)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


httpd = http.server.HTTPServer(("127.0.0.1", PORT), DashboardHandler)
print(f"🌐 Дашборд: http://localhost:{PORT}/dashboard.html")
httpd.serve_forever()
