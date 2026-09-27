# Verified frelay controls

Source: `crogers2287/frelay`, commit `2885494b11ec93560e713afb3eac2a16958bbffd`, inspected 2026-09-27 UTC. Repository inspection, not a live inspection of Fred.

- [Existing skill](https://github.com/crogers2287/frelay/blob/2885494b11ec93560e713afb3eac2a16958bbffd/skills/flipper-relay/SKILL.md)
- [Adapter](https://github.com/crogers2287/frelay/blob/2885494b11ec93560e713afb3eac2a16958bbffd/server/mcp_adapter.py)
- [Server](https://github.com/crogers2287/frelay/blob/2885494b11ec93560e713afb3eac2a16958bbffd/server/relay.py)

## Tool signatures

| Tool | Arguments | Use |
|---|---|---|
| flipper_status | none | Readiness and transport |
| flipper_device_info | none | Hardware/firmware identity |
| flipper_power_info | none | Battery/power |
| flipper_list_files | path="/ext" | List directory |
| flipper_read_file | path | Base64 bytes; UTF-8 when decodable |
| flipper_write_text | path, text | Create/overwrite UTF-8 |
| flipper_write_file | path, data_base64 | Create/overwrite binary |
| flipper_mkdir | path | Create directory |
| flipper_delete_file | path | Delete file/empty directory |
| flipper_screen | none | PNG image |
| flipper_button | key, long_press=false | UP, DOWN, LEFT, RIGHT, OK, BACK |
| flipper_start_app | name, args="" | Exact app name/path |
| flipper_exit_app | none | Exit RPC-capable app |
| flipper_load_file | path | Load into running RPC app; may trigger action |
| flipper_app_button | args="", index=0 | App-specific press/release |
| flipper_alert | none | Audiovisual identification |

Use adapter press/release sequencing; do not add extra events. Resolve app names/arguments from installed documentation and observed files.

## Deployment and diagnosis

Verify the prior checkout `~/frelay` before using it.

- Service: `systemctl --user status flipper-phone-relay --no-pager`.
- Logs: `journalctl --user -u flipper-phone-relay -n 30 --no-pager`; redact any secrets.
- Config: `~/.config/flipper-phone-relay/config.json` containing host, port, phone_token, agent_token. Read only necessary fields programmatically; do not dump it.
- Intended port: **9434**. **8787 belongs to another service; do not alter it.** Diagnose saved-config mismatches before changes.
- Obtain Fred's current Tailscale IPv4 with `tailscale ip -4`, not a remembered address.
- Phone: WebSocket `/phone`. Agent: authenticated HTTP `GET /status`, `POST /command`, `GET /screen.png`. Distinct Bearer tokens in headers, never URLs.
- Prefer `FLIPPER_RELAY_CONFIG` for the stdio MCP adapter. Its source also accepts `FLIPPER_RELAY_URL` and `FLIPPER_AGENT_TOKEN` when config is absent.
- `manage.py mcp-config` emits interpreter/adapter/config paths without tokens. `show`, `init`, and `set-port` print the phone token; do not run those into agent-visible logs for routine diagnosis.
- If the service failed, diagnose before an appropriate `systemctl --user restart flipper-phone-relay`. Do not start a competing server. Preserve credentials.

| Observation | Next step |
|---|---|
| No Flipper tools | Inspect MCP entry or read-only probe; not proof the server is down |
| Connection refused/timeout | Inspect service, bind address, tailnet reachability, saved port |
| HTTP 401 | Inspect agent credential configuration; do not regenerate tokens |
| connected=false | Check phone/Flipper readiness |
| HTTP 409 | Inspect actual firmware RPC error and app support |
| HTTP 400/422 | Compare arguments with current schema |
| HTTP 503/interruption | Execution may be unknown; inspect state, no automatic replay |

## Phone transport

Keep phone and Fred on the authorized tailnet. The phone connects outbound. In the app: Stop relay → choose BLE or USB → Find devices → select Flipper → Start relay. Confirm transport through status.

BLE needs Nearby Devices permission/pairing confirmation. USB needs USB-host support, a data-capable cable, and Android USB permission. Reconnection may require selection/permission again. Close competing active Flipper connections. Only one phone session controls the relay. USB does not silently replace BLE.

Android permits `ws://` only for literal Tailscale addresses; DNS names require `wss://` and a valid certificate. Preserve authentication/private binding; do not expose the relay publicly to solve reachability. Phone permission prompts require the user when no authorized phone control surface exists.
