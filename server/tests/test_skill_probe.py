"""Exercise the installed skill's one-shot HTTP fallback without hardware."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

PROBE = Path(__file__).resolve().parents[2] / "skills/flipper-relay/scripts/probe.py"


@pytest.mark.parametrize("operation,status", [("status", 200), ("device_info", 200), ("power_info", 503)])
def test_probe_single_authenticated_request(tmp_path, operation, status):
    requests = []
    token = "private-agent-token-do-not-print"

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append((self.command, self.path, self.headers.get("Authorization"), body))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"connected": False} if status == 200 else {"detail": token}).encode())

        do_GET = respond
        do_POST = respond

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"host": "127.0.0.1", "port": server.server_port, "agent_token": token}))
    try:
        result = subprocess.run([sys.executable, str(PROBE), operation, "--config", str(config)],
                                capture_output=True, text=True, timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(requests) == 1  # Even a server failure must never replay the request.
    method, path, auth, body = requests[0]
    assert auth == "Bearer " + token
    assert token not in result.stdout + result.stderr
    if operation == "status":
        assert (method, path, body) == ("GET", "/status", b"")
    else:
        assert (method, path) == ("POST", "/command")
        assert json.loads(body) == {"operation": operation}
    assert result.returncode == (0 if status == 200 else 1)
    if status == 200:
        assert json.loads(result.stdout) == {"connected": False}
    else:
        assert result.stdout == ""
        assert "not retried" in result.stderr
