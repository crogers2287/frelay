"""Generate configuration, run the relay, and print client setup without shell placeholders."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

DEFAULT = Path.home() / ".config" / "flipper-phone-relay" / "config.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["init", "run", "show", "mcp-config"])
    p.add_argument("--config", type=Path, default=DEFAULT)
    p.add_argument("--host")
    p.add_argument("--port", type=int, default=8787)
    args = p.parse_args()
    if args.action == "init" and not args.config.exists():
        host = args.host
        if not host:
            try:
                host = subprocess.check_output(["tailscale", "ip", "-4"], text=True, timeout=10).strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                p.error("Tailscale is not connected. Connect it first, or pass --host with this server's Tailscale IP.")
        ip = ipaddress.ip_address(host)
        if not (ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10") or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")):
            p.error("Bind to a Tailscale IP or loopback address")
        if not 1 <= args.port <= 65535:
            p.error("Port must be 1..65535")
        settings = {"host": host, "port": args.port, "phone_token": secrets.token_urlsafe(32), "agent_token": secrets.token_urlsafe(32)}
        args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f, indent=2)
    if not args.config.exists():
        p.error("Run manage.py init first")
    with args.config.open() as f:
        settings = json.load(f)
    if args.action in ("init", "show"):
        host = settings["host"]
        print("Phone URL: ws://" + ("[" + host + "]" if ":" in host else host) + ":" + str(settings["port"]) + "/phone")
        print("Phone token: " + settings["phone_token"])
        print("Use BLE or USB in the Android app, find the Flipper, then Start relay.")
    elif args.action == "mcp-config":
        print(json.dumps({"mcpServers": {"flipper": {"command": sys.executable, "args": [str(Path(__file__).with_name("mcp_adapter.py").resolve())],
                         "env": {"FLIPPER_RELAY_CONFIG": str(args.config.resolve())}}}}, indent=2))
    elif args.action == "run":
        import uvicorn
        from relay import create_app
        app = create_app(settings["phone_token"], settings["agent_token"])
        uvicorn.run(app, host=settings["host"], port=settings["port"], ws_max_size=65536,
                    ws_ping_interval=20, ws_ping_timeout=20, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
