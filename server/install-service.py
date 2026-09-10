"""Install an optional systemd user service using this checkout and venv."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
config = Path.home() / ".config/flipper-phone-relay/config.json"
if not config.exists():
    raise SystemExit("Run setup.sh first")


def quote(value):
    # systemd consumes percent specifiers even within quoted arguments.
    return json.dumps(str(value).replace("%", "%%"))


unit = "\n".join([
    "[Unit]", "Description=Flipper phone BLE/USB relay", "After=network-online.target", "",
    "[Service]", "Type=simple", "WorkingDirectory=" + quote(root),
    "ExecStart=" + " ".join(map(quote, [sys.executable, root / "manage.py", "run", "--config", config])),
    "Restart=on-failure", "RestartSec=5", "NoNewPrivileges=true", "UMask=0077", "",
    "[Install]", "WantedBy=default.target", "",
])
destination = Path.home() / ".config/systemd/user/flipper-phone-relay.service"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(unit)
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
subprocess.run(["systemctl", "--user", "enable", "--now", destination.name], check=True)
print("Installed and started " + destination.name)
print("Status: systemctl --user status flipper-phone-relay")
print("For startup without login, enable lingering for this Linux user through loginctl.")
