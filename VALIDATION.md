# Validation — 2026-09-10

## Completed

- Android debug APK assembled with Gradle 8.9, Android Gradle Plugin 8.7.3, JDK 17.0.20.1, and compile/target SDK 35.
- Final targets `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug` completed successfully after a clean compilation.
- Android unit tests: 2 passed, 0 failures. These test endpoint validation, including permitted Tailscale addresses, TLS URLs, and rejection of cleartext non-tailnet URLs and embedded credentials.
- APK signature verified with Android `apksigner`: valid v2 signature, one signer. This is a debug-signed test APK, not a production release-signing setup.
- APK package: `com.cfr.flipperrelay`; version `0.1.0` (code 1); minimum Android API 31 (Android 12).
- Python tests: 14 passed. Coverage includes fragmented/coalesced protobuf streams, malformed lengths, separate phone/agent authentication, mocked BLE/USB WebSocket-to-HTTP roundtrips, multipart and empty file writes, timeout/disconnect behavior without replay, button sequencing, screenshot bit packing/orientation, and malformed base64.
- A real stdio MCP client initialized the adapter and discovered 16 tools.
- A real MCP `flipper_status` call reached the running HTTP server and returned the expected disconnected state.
- Generated server configuration uses distinct random credentials and file permissions `0600`.
- Shell scripts passed `bash -n`.

The Python tests emit a dependency deprecation warning for Starlette's AnyIO BlockingPortal alias; it does not fail the tests.

## Physical validation on Fred — 2026-09-10

A Pixel 10 Pro connected over Tailscale to the existing systemd user service on TCP **9434**. The saved host and both credentials were preserved during migration from occupied port 8787; configuration mode remained `0600`. The installed APK was configured without reinstalling it. Its phone token was checked against the existing server token without printing either credential.

### BLE: actual Flipper RPC responses verified

Device: Flipper Zero **Kuyo**, official firmware **1.4.3**, commit `8622f1a2`, protobuf **0.25**. Initial battery reading: **64%**, discharging. The device was already discoverable/bonded; fresh pairing was not tested.

| Check | Observed result |
|---|---|
| Stdio MCP status | `connected: true`, `transport: BLE` |
| Device and power information | Actual firmware multipart responses returned hardware/firmware and battery values |
| Identification alert | Firmware returned successful matching RPC response, command ID 3; sound/light was not independently observed by the remote operator |
| Screen capture | Two real 128×64 PNG frames decoded successfully; one is retained in `validation/2026-09-10/ble-screen.png` |
| Short BACK press | Firmware acknowledged the input sequence; screenshots showed the same menu, so a visible navigation change is not established |
| Disposable file | Wrote 64 bytes to a unique `/ext/frelay-validation-…txt`, read back identical UTF-8 content, then received successful deletion response |
| Phone screen off | Android reported `mWakefulness=Dozing` with the relay partial wake lock held; device-info and power-info requests succeeded approximately 49 seconds apart while screen-off |
| Interrupted request | Stopping the phone app during one device-info request returned HTTP 503: `Phone disconnected; pending commands were not retried`; status became disconnected |
| Reconnect | After app restart/reconnection, status and new device/power requests succeeded over BLE; the interrupted request was not retried by the test client |

The hardware observations above are distinct from transport-write acknowledgments. Existing automated tests cover clearing pending requests and no replay across reconnects. The physical interruption used app termination, not a radio-range failure or Flipper power cycle. Long-duration Android idle/doze behavior remains untested.

### Harness integration and fallback

- Haxor's existing profile received the generated `flipper` MCP entry and was restarted. Its native Hermes MCP registry discovered all 16 Flipper tools (plus Hermes resource/prompt utility tools), and its status dispatch reached the live BLE relay.
- OMP's native configuration loader identified `~/.omp/agent/mcp.json` as the source. Its MCP manager connected, discovered 16 tools, and successfully called live BLE status.
- A subsequent Haxor Telegram turn guessed an unrelated service instead of using Flipper tools. Added the explicit `flipper-relay` skill to Haxor and OMP, plus direct skill-routing instructions in Haxor's `AGENTS.md`. Haxor's skill discovery and `skill_view` found the new skill. A subsequent model-driven Telegram turn has not yet been verified.
- The skill's standard-library HTTP fallback was run against the real relay for status, device info and power info. Three additional automated cases verify GET/POST payloads, saved-token authentication, failure exit status, secret suppression, and exactly one request on HTTP failure.
- Existing local edits in `server/install-service.py` and `server/mcp_adapter.py` were preserved during the main-branch fast-forward. They are not included in this validation/skill publication.

### Still requires physical validation

USB-C enumeration, Android permission, CDC ACM CLI-to-RPC handshake, and the same device/screen/input/file checks have **not** yet been verified. USB cable removal/reinsertion, fresh BLE bonding, and prolonged screen-off operation remain open. Neither the successful BLE run nor mocked USB tests prove USB hardware compatibility.

## Repository delivery

The standalone Android relay and Python MCP server are published in `crogers2287/frelay`. Development used the upstream Android repository and pinned protocol schemas documented in README.md. The GitHub Actions workflow builds the debug APK and runs Android and Python tests. The published port-migration commit `07be6b27c3a5a016e0497abbe1260e96e20325cd` passed [GitHub Actions run 34530823099](https://github.com/crogers2287/frelay/actions/runs/34530823099). The initial publication run also completed successfully. These CI results do not establish hardware compatibility.
