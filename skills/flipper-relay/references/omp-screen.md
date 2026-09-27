# Screen perception for OMP and Flash-Next

## Install on Fred

Run the bundled `scripts/install_omp.py` with Python 3 from the actual skill source directory. It copies this complete skill into `~/.omp/agent/skills/flipper-relay`, backing up an existing installation first. It changes no MCP configuration, tokens, service, model, or port. When installing from frelay's repository copy:

```bash
python3 ~/frelay/skills/flipper-relay/scripts/install_omp.py
```

Verify the source checkout location first. After installation, have OMP read `~/.omp/agent/skills/flipper-relay/SKILL.md` in the active session. Do not assume an already-running model has loaded a changed file.

Requirements: Linux Python 3.10+, Pillow, and optional Tesseract executable. Fred's relay Python environment already declares Pillow in the inspected repository; check the selected interpreter rather than assuming `python3` has it. Use that environment's interpreter if available. Tesseract provides OCR without any model/API configuration; missing Tesseract is reported explicitly. Install only missing dependencies in the intended environment when authorized. Do not reinstall frelay.

## Commands

```bash
python3 ~/.omp/agent/skills/flipper-relay/scripts/screen.py observe
python3 ~/.omp/agent/skills/flipper-relay/scripts/screen.py observe --vision
python3 ~/.omp/agent/skills/flipper-relay/scripts/screen.py --help
python3 ~/.omp/agent/skills/flipper-relay/scripts/screen.py step --help
```

Global `--config` and `--cache` precede the subcommand. Default config honors `FLIPPER_RELAY_CONFIG`, otherwise uses `~/.config/flipper-phone-relay/config.json`. Default private cache is `${XDG_CACHE_HOME:-~/.cache}/flipper-relay-screen`. PNGs and JSON stay there; they may contain sensitive screen content. They are not uploaded unless `--vision` is explicitly enabled. Clean only this helper's old observations when no active task depends on them.

For a step, pass the exact `observation_id` from the latest response to `--from`, along with a key: UP, DOWN, LEFT, RIGHT, OK, BACK. Optional `--long` sends a long press. No automatic button retries occur. Cache observations are single-use, and observations older than 60 seconds are refused. If OCR/vision processing made an observation old, observe again. Concurrent invocations using the same cache are refused by a local lock; this does not lock other MCP clients or the physical device.

The script outputs JSON and exits nonzero for errors, unknown button outcome, stale-screen refusal, or failed post-action capture. A successful observation can still contain unavailable OCR or failed vision; inspect those fields, not just exit status.

## Vision for a text-only controller

First check whether OMP already exposes an image-capable analysis tool. Feed that tool the exact `enlarged_png` from the latest observation and request: screen type, exact visible text, highlighted selection, dialog text, and ambiguities. The interpretation must reference that observation ID. OMP displaying a screenshot is not proof it forwarded image content to Flash-Next.

If using the bundled sidecar client, configure these variables in the same execution environment as the helper:

| Variable | Meaning |
|---|---|
| FLIPPER_VISION_BASE_URL | Authorized OpenAI-compatible API base, including `/v1` if required; helper appends `/chat/completions` |
| FLIPPER_VISION_MODEL | Exact served image-capable model identifier, verified from existing configuration |
| FLIPPER_VISION_API_KEY | Optional endpoint credential; omit for a configured no-auth local server |

Read the actual local serving/OMP configuration for existing endpoints and model names. Do not invent them, copy historical model names, change Flash-Next as the controller, or forward screenshots to an unrelated provider. The helper supports JSON text in Chat Completions responses and an `image_url` data-URI request. It does not assume every API or model supports that format. No native Anthropic API support is bundled.

Use an existing local vision model where configured. A remote model is usable only when the user has authorized that destination for screen images. Relay credentials never go to the vision endpoint. The vision model receives only the enlarged PNG and a fixed perception prompt; it has no tools and cannot issue commands. Invalid JSON, absent confidence, unreadable text, and uncertain selection do not authorize action. Confidence is self-reported and uncalibrated.

## Interpret observations

- `ocr.lines`: OCR claims with native-screen bounding boxes and Tesseract scores. Both normal and inverted passes run on nearest-neighbor 6x images. Duplicate/conflicting lines can occur. Tiny pixel fonts, icons, truncation and dialogs remain difficult.
- `highlight_candidates`: geometric dark bands, not confirmed menu focus. Never infer a selected label just because its y-coordinate overlaps a dark band.
- Top-level `selected_text` intentionally remains null. The optional `vision.selected_text` is an attributed model claim, not firmware telemetry.
- `screen_sha256`: decoded pixels plus dimensions. Compare captures; equal means equal pixels, not equal hidden device state.
- `screen_changed`: pixel difference from the pre-action observation, not proof of task success.
- `action:rpc_acknowledged`: relay returned a successful firmware RPC response. Verify intended effect independently.
- `action:outcome_unknown`: do not replay; reconnect/check state first.

For a menu, focus is usable only when the actual highlight is readable from an inspected image or sufficiently clear vision evidence without unresolved contradictions. For a dialog, determine what OK/BACK would do before pressing. For a keyboard, do not confuse selected key with entered text. Prefer direct file operations to typing filenames with dozens of buttons.

## PromptZero findings and boundaries

Inspected upstream `xunholy/promptzero` at `1746581c7dbe2e0c3af0057c87e65debc00532f6` on 2026-09-27 UTC:

- [State prompt](https://github.com/xunholy/promptzero/blob/1746581c7dbe2e0c3af0057c87e65debc00532f6/internal/agent/state_prompt.go) provides fresh structured device grounding. Apply this principle by retaining the latest observation, not accumulating screenshots as if all were current.
- [Vision tool](https://github.com/xunholy/promptzero/blob/1746581c7dbe2e0c3af0057c87e65debc00532f6/internal/tools/vision.go) marks `analyze_image` as `AgentOnly:true`. Its [analyzer](https://github.com/xunholy/promptzero/blob/1746581c7dbe2e0c3af0057c87e65debc00532f6/internal/vision/vision.go) uses Anthropic vision. Do not assume `promptzero --mcp` exposes that tool to OMP.
- [Transports](https://github.com/xunholy/promptzero/blob/1746581c7dbe2e0c3af0057c87e65debc00532f6/docs/reference/transports.md) document HTTP UART send/receive, which differs from frelay's authenticated protobuf command API. Pointing PromptZero at port 9434 does not create compatibility.
- [Screen input](https://github.com/xunholy/promptzero/blob/1746581c7dbe2e0c3af0057c87e65debc00532f6/internal/web/api_screen.go) explicitly sends press/short/release. The inspected frelay baseline sends press/release/short. Both include SHORT, but the order differs. If screenshots are readable and acknowledged taps consistently have no effect, compare the deployed firmware/relay behavior with qFlipper and investigate event ordering. This is a diagnostic lead, not a verified cause; do not patch a live relay speculatively or compensate with repeated presses.

These helpers are an original frelay-specific implementation informed by these architectural observations. They do not install PromptZero or import its broad tool catalog.
