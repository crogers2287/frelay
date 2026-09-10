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

## Not physically verified

No Android phone or Flipper was attached to this build environment. BLE bonding, GATT flow-control behavior against firmware, USB-C enumeration and permission prompts, the USB CLI-to-RPC handshake, device screen/button operation, and screen-off operation through an actual Tailscale connection require a physical-device test. Passing mocked protocol tests is not proof of hardware compatibility.

First physical checks, separately for BLE and USB:

1. Start the server and phone relay; verify `flipper_status` reports the selected transport.
2. Read device and power information, then trigger the identification alert.
3. Capture the screen and perform one navigation button press.
4. Write and read a disposable test text file on the SD card.
5. Turn the phone screen off and repeat a device-info request.
6. Disconnect/reconnect the transport and verify in-flight commands fail and are not automatically repeated.

## Repository delivery

The standalone Android relay and Python MCP server are published in `crogers2287/frelay`. Development used the upstream Android repository and pinned protocol schemas documented in README.md. The GitHub Actions workflow builds the debug APK and runs Android and Python tests. Local validation above predates publication; workflow results are available in the repository's Actions tab.
