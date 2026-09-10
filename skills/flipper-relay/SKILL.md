---
name: flipper-relay
description: Control the user's Flipper Zero through the frelay Android phone relay over BLE or USB-C. Use for Flipper connection/status, device or battery info, screen capture, buttons, files, or troubleshooting this phone relay.
---

# Flipper phone relay

This installation is frelay on Fred (`~/frelay`). The Android phone opens an outbound WebSocket over Tailscale. It forwards Flipper protobuf RPC over the explicitly selected BLE or USB transport. Both use the same 16 MCP tools.

## Start here

1. Discover the Flipper tools with `tool_search` if they are not already visible. Search for `flipper_status` or `flipper`. Hermes names them `mcp__flipper__flipper_status`, etc.; other MCP clients may use another prefix. These are MCP tools, not shell commands.
2. Call `flipper_status`. If connected, call `flipper_device_info` and `flipper_power_info`. Report actual results and transport. Status alone confirms relay readiness, not device execution.
3. If tools are absent from this turn, use the terminal fallback below immediately. Do not invent a relay service, install another relay, or infer the relay is down from missing tools.

## Terminal fallback on Fred

These read-only checks use the saved agent credential without printing it and never retry. They work even if the current agent did not load MCP. Run the script beside this skill, using its actual installed path:

```bash
python3 ~/.hermes/profiles/haxor/skills/flipper-relay/scripts/probe.py status
python3 ~/.hermes/profiles/haxor/skills/flipper-relay/scripts/probe.py device_info
python3 ~/.hermes/profiles/haxor/skills/flipper-relay/scripts/probe.py power_info
```

For OMP, the same script is at `~/.omp/agent/skills/flipper-relay/scripts/probe.py`. The repository copy is `~/frelay/skills/flipper-relay/scripts/probe.py`. A failed request exits nonzero. Fix the cause before deciding on a new request; a fallback is not permission to replay a failed MCP operation.

For other operations, use the MCP tools. Inspect `~/frelay/server/mcp_adapter.py` for exact arguments. If the checkout is elsewhere, inspect the configured `flipper` MCP entry for the interpreter and adapter paths.

## Connection troubleshooting

- The exact service is **`systemctl --user status flipper-phone-relay`**. Read logs with `journalctl --user -u flipper-phone-relay -n 30 --no-pager`.
- Configuration: `~/.config/flipper-phone-relay/config.json`; port **9434**. Port 8787 belongs to another service. Do not stop or alter it.
- If the frelay service is down, inspect its error, then restart this user service when appropriate: `systemctl --user restart flipper-phone-relay`. Do not launch a competing server. No sudo is needed.
- The phone URL is `ws://<actual Fred Tailscale IPv4>:9434/phone`. Obtain the actual address using `tailscale ip -4`; never invent an address. Phone and Fred must use the same tailnet.
- Phone and agent tokens are separate. Preserve both. `manage.py show` prints the phone token, so run it only when the user needs that credential locally, never in a public log.
- `manage.py set-port --port 9434` preserves credentials but prints the phone token. Restart the relay service and any existing adapter processes after changing ports.
- `connected: false` means no ready phone/Flipper session; it does not mean the server is down. Check the phone app's displayed error, transport, device selection, permissions and competing Flipper connections.
- To switch transport: Stop relay, select BLE or USB, Find devices, select Flipper, Start relay. USB requires a data-capable USB-C cable and Android USB permission. The existing APK accepts 9434 without reinstalling.

## Tools and limits

Device: `flipper_status`, `flipper_device_info`, `flipper_power_info`, `flipper_alert`.
Screen/input: `flipper_screen`, `flipper_button` (UP, DOWN, LEFT, RIGHT, OK, BACK; optional long press).
Files: `flipper_list_files`, `flipper_read_file`, `flipper_write_text`, `flipper_write_file`, `flipper_mkdir`, `flipper_delete_file`.
Apps: `flipper_start_app`, `flipper_exit_app`, `flipper_load_file`, `flipper_app_button`; firmware/app RPC support is required.

- Only matching successful Flipper RPC responses establish device execution. A phone `written` acknowledgment does not.
- After a timeout or disconnect, outcome is unknown. Never automatically replay the operation, including through a fallback. Inspect state and obtain a deliberate retry decision first. A partial file may exist.
- Test files belong under `/ext` with a unique disposable name; read back and compare before deleting only that test file.
- Screen tools return PNG images. Use the agent's configured vision tool if the model cannot view images; do not invent screen contents.
- There are no dedicated NFC/RFID/Sub-GHz capture or decode tools. USB modes replacing serial can interrupt the relay.
- For proven hardware results and remaining limits, read `~/frelay/VALIDATION.md`; do not turn a mocked test or an earlier session's result into a claim about current hardware state.
