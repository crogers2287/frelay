"""One read-only relay request using saved credentials, with no retries."""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("status", "device_info", "power_info"), default="status", nargs="?")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/flipper-phone-relay/config.json")
    args = parser.parse_args()
    try:
        settings = json.loads(args.config.read_text())
        host = settings["host"]
        if ":" in host:
            host = "[" + host + "]"
        url = f"http://{host}:{settings['port']}"
        payload = None if args.operation == "status" else json.dumps({"operation": args.operation}).encode()
        request = Request(url + ("/status" if payload is None else "/command"), data=payload,
                          headers={"Authorization": "Bearer " + settings["agent_token"], "Content-Type": "application/json"})
        with build_opener(ProxyHandler({})).open(request, timeout=25) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as exc:
        print(f"Relay HTTP {exc.code}: request failed; not retried. Inspect connection state before another request.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, URLError) as exc:
        print(f"Relay check failed ({type(exc).__name__}); not retried. Check saved configuration and service state.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
