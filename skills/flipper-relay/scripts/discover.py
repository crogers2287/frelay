"""List candidate frelay paths on this host without opening credentials."""
import json
from pathlib import Path
import socket


def discover(home):
    candidates = [home / p for p in (
        "frelay/skills/flipper-relay/SKILL.md",
        ".hermes/skills/flipper-relay/SKILL.md",
        ".omp/agent/skills/flipper-relay/SKILL.md",
        ".codex/skills/flipper-relay/SKILL.md",
        ".claude/skills/flipper-relay/SKILL.md",
    )]
    profiles = home / ".hermes/profiles"
    if profiles.is_dir():
        candidates.extend(profiles.glob("*/skills/flipper-relay/SKILL.md"))
    config = home / ".config/flipper-phone-relay/config.json"
    source = home / "frelay/server/mcp_adapter.py"
    return {
        "execution_host": socket.gethostname(),
        "scope": "current host only; no remote inspection performed",
        "existing_skills": sorted({str(p) for p in candidates if p.is_file()}),
        "adapter_path": str(source) if source.is_file() else None,
        "config_path": str(config) if config.is_file() else None,
        "credentials_read": False,
    }


if __name__ == "__main__":
    print(json.dumps(discover(Path.home()), indent=2))
