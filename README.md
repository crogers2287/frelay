# Flipper Phone Relay — BLE and USB-C

An Android relay and Python MCP adapter for controlling your Flipper Zero from a local-model agent through your phone and Tailscale.

The phone opens an outbound WebSocket to the server over Tailscale. The phone forwards Flipper protobuf RPC bytes using either its Bluetooth LE radio or Android USB-host CDC ACM. The server exposes the same 16 MCP tools for both transports.

## What is included

- A standalone **Flipper Relay** Android app, built in `android/`. It installs alongside the official app under `com.cfr.flipperrelay`; it does not modify the official app's installed data.
- BLE pairing, Flipper serial UUIDs, MTU-sized writes, buffer-credit flow control, and reconnects.
- USB-C host access with Android permission prompts, CDC configuration, and CLI-to-RPC handshake. No root, USB debugging, or Wi-Fi dev board required.
- Foreground relay service with a notification and Stop action. Android or the network may still interrupt it; it reconnects but never replays a pending command.
- Authenticated server, separate phone and agent credentials, bounded protobuf framing, multipart replies and writes, screen PNGs, and stdio MCP tools.
- Source, pinned Python dependencies, automated tests, and a GitHub Actions build workflow.

## Requirements

- Android 12 or later. USB needs USB-host support and a data-capable USB-C cable.
- Flipper Zero in normal firmware mode, with BLE enabled for the wireless path or USB CDC available for the wired path. DFU/bootloader and USB HID modes are not the relay's serial transport.
- Phone and server connected to the same Tailscale network; permit the phone to reach server TCP port 8787 in your tailnet policy.
- Python 3.12 on the server, with `venv` support. The setup script detects the server's Tailscale IPv4 address.
- A local-model agent that supports MCP. The model itself need not implement networking. Screen inspection additionally requires image-capable tool handling/model vision.

## Server setup

Clone this repository and enter the server directory:

```bash
git clone https://github.com/crogers2287/frelay.git
cd frelay/server
```

Then run:

```bash
bash setup.sh
.venv/bin/python manage.py run
```

Setup creates unique credentials in `~/.config/flipper-phone-relay/config.json` with owner-only file permissions. It prints the actual phone URL, phone token, and a ready-to-copy MCP configuration using absolute paths. The agent token remains in the configuration file instead of the printed MCP entry. Existing configuration is preserved on subsequent setup runs.

To display the phone configuration again:

```bash
.venv/bin/python manage.py show
```

To print your agent's MCP entry again:

```bash
.venv/bin/python manage.py mcp-config
```

Register that entry in your agent's MCP configuration. The emitted `mcpServers` form is common; an agent that uses a different configuration format still uses the same `command`, `args`, and environment values. Run that MCP process on the server containing the generated configuration file. Point the agent at your local inference endpoint independently.

For a background systemd user service, stop the foreground server and run:

```bash
.venv/bin/python install-service.py
```

The service runs while the user's systemd manager is active. Boot-time operation without a login also requires that user's lingering to be enabled. The service restarts if Tailscale's address is not available yet. Logs: `journalctl --user -u flipper-phone-relay`.

## Phone setup

1. Install a debug APK built locally or downloaded from a successful [Build phone relay workflow run](https://github.com/crogers2287/frelay/actions/workflows/build.yml) (artifact `flipper-phone-relay-apk`). It is a signed debug build for testing.
2. Connect Tailscale on the phone.
3. Open **Flipper Relay**, paste the printed **Phone URL** and **Phone token**.
4. Select **BLE** or **USB**.
5. Tap **Find devices**, select the Flipper, and tap **Start relay**.
6. For BLE, allow Nearby Devices permissions and confirm pairing on the phone/Flipper. For USB, plug in the data cable first and approve the USB permission prompt.
7. Confirm **Connected via BLE** or **Connected via USB**. The agent's first checks are `flipper_status` followed by `flipper_device_info`.

Close other active Flipper connections before starting this relay. Only one relay phone session can control the server at a time. To change transport, tap Stop, select the new transport, Find devices, and Start. Changing transport does not require changing the agent's MCP configuration. Plugging in USB does not silently preempt a BLE session.

The phone keeps the relay active after you leave its screen and holds a partial wake lock while it runs. Its notification includes Stop. If Android stops it, open the app and Start again. A removed/reinserted USB device may require another permission grant and selection. Flipper apps that change the USB interface (for example, into a HID profile) interrupt the USB relay; BLE avoids sharing that USB interface.

## Agent tools

| Tool | Function |
|---|---|
| `flipper_status` | Relay readiness and BLE/USB transport |
| `flipper_device_info` | Hardware and firmware information |
| `flipper_power_info` | Battery/power information |
| `flipper_list_files` | List a directory, default `/ext` |
| `flipper_read_file` | Read bytes as base64 and optionally decoded UTF-8 |
| `flipper_write_text` | Create/overwrite UTF-8 file |
| `flipper_write_file` | Create/overwrite binary file from base64 |
| `flipper_mkdir` | Create directory |
| `flipper_delete_file` | Delete file or empty directory, nonrecursive |
| `flipper_screen` | Capture a PNG screen image |
| `flipper_button` | Short/long physical navigation button events |
| `flipper_start_app` | Start app by exact name/path and arguments |
| `flipper_exit_app` | Exit the running RPC-capable app |
| `flipper_load_file` | Load a file into the running RPC-capable app |
| `flipper_app_button` | App-specific button action |
| `flipper_alert` | Audiovisual identification alert |

File writes are limited to 1 MiB and responses to 2 MiB. A timeout or disconnect leaves the outcome unknown and may leave a partial file. Inspect device state before deciding to retry. Not every Flipper app supports RPC; a relay does not add unsupported firmware operations. There are no dedicated NFC/RFID/Sub-GHz capture or decode tools in this release. App-specific operations return actual firmware errors rather than simulated success.

## Transport protocol

- Endpoint: `GET /phone`, WebSocket, `Authorization: Bearer <phone token>`.
- Phone opens BLE/USB, then sends `{"type":"ready","protocol":1,"transport":"BLE"}` or `"USB"`.
- Server binary frames contain varint-delimited Flipper `PB.Main` requests.
- Phone chunks each request to the transport, then sends `{"type":"written"}`. This is only a transport-write acknowledgement, not confirmation of device execution.
- Phone forwards received transport bytes in binary WebSocket frames. Packet boundaries may split protobuf messages arbitrarily.
- Server waits for actual matching RPC responses and aggregates `has_next` sequences. Command IDs are unique within the session.
- Each side discards state and queued commands on disconnect. A replacement connection starts a fresh Flipper RPC session.
- Agent HTTP endpoints: authenticated `GET /status`, `POST /command`, `GET /screen.png`.

`ws://` on Android is allowed only for literal Tailscale addresses (`100.64.0.0/10` or Tailscale's IPv6 prefix). DNS addresses require `wss://` and a valid certificate. The provided server binds directly to its Tailscale address; it is not an exit node or subnet router. TLS termination is optional and external to this package. Tokens are never put in URLs.

## Build from source

The relay has a separate Gradle build so it does not need the official app's full UI/analytics/catalog dependency graph. Its BLE constants, byte ordering, and USB handshake follow the upstream implementation; the transport classes are purpose-built Android host implementations.

With JDK 17 and Android SDK 35 installed:

```bash
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`.

Python checks:

```bash
cd server
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The protobuf Python modules are committed, so setup does not need a compiler. To regenerate them after updating `proto/`:

```bash
.venv/bin/python -m grpc_tools.protoc -I proto --python_out=. proto/*.proto
```

## Provenance and verification

Upstream Android repository: https://github.com/flipperdevices/Flipper-Android-App

Base commit: `a399cabd975ba8460ae21b0466289c4cb8a7d66d`.

Protocol schema source: https://github.com/flipperdevices/flipperzero-protobuf

Pinned protobuf submodule commit: `ee5b6a22fd6aaf9075a2b7bd373309592e6627c5`.

See `VALIDATION.md` for build/test evidence and remaining physical-device checks. This repository publishes the standalone relay extracted from development against the upstream Android repository; it is not the full official Android application or a GitHub fork of it.

Upstream MIT license is included in `LICENSE`. New relay code is also provided under MIT.
