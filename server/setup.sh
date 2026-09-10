#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py init "$@"
.venv/bin/python manage.py mcp-config "$@"
echo 'Start the server with: .venv/bin/python manage.py run'
