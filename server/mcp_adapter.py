"""Local stdio MCP tools; the model provider is independent of this relay."""
import base64
import json
import os
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP, Image

mcp = FastMCP("Flipper Phone Relay")


async def request(path, payload=None):
    url = os.environ.get("FLIPPER_RELAY_URL", "http://127.0.0.1:9434").rstrip("/")
    token = os.environ["FLIPPER_AGENT_TOKEN"]
    async with httpx.AsyncClient(timeout=130, trust_env=False) as client:
        headers = {"Authorization": "Bearer " + token}
        response = await client.get(url + path, headers=headers) if payload is None else await client.post(url + path, json=payload, headers=headers)
        if response.is_error:
            raise RuntimeError(f"Relay {response.status_code}: {response.text}")
        return response


async def command(operation, **kwargs):
    return (await request("/command", {"operation": operation, **kwargs})).json()


@mcp.tool()
async def flipper_status() -> dict:
    """Check whether the phone is connected to the Flipper and whether it uses BLE or USB."""
    return (await request("/status")).json()


@mcp.tool()
async def flipper_device_info() -> dict:
    """Read Flipper hardware/firmware information."""
    return await command("device_info")


@mcp.tool()
async def flipper_power_info() -> dict:
    """Read battery and power information."""
    return await command("power_info")


@mcp.tool()
async def flipper_list_files(path: str = "/ext") -> dict:
    """List a directory on the Flipper; /ext is the SD card."""
    return await command("list_files", path=path)


@mcp.tool()
async def flipper_read_file(path: str) -> dict:
    """Read a Flipper file as base64; UTF-8 text is also returned when decodable. Maximum response 2 MiB."""
    result = await command("read_file", path=path)
    try:
        result["text"] = base64.b64decode(result["data_base64"]).decode("utf-8")
    except UnicodeDecodeError:
        pass
    return result


@mcp.tool()
async def flipper_write_text(path: str, text: str) -> dict:
    """Create or overwrite a UTF-8 file on the Flipper (up to 1 MiB). A timeout can leave a partial file; inspect before retrying."""
    return await command("write_file", path=path, data_base64=base64.b64encode(text.encode()).decode())


@mcp.tool()
async def flipper_write_file(path: str, data_base64: str) -> dict:
    """Create or overwrite a binary file from base64 (up to 1 MiB). A timeout can leave a partial file."""
    return await command("write_file", path=path, data_base64=data_base64)


@mcp.tool()
async def flipper_mkdir(path: str) -> dict:
    """Create a Flipper directory."""
    return await command("mkdir", path=path)


@mcp.tool()
async def flipper_delete_file(path: str) -> dict:
    """Delete the specified file or empty directory. This is not recursive."""
    return await command("delete_file", path=path)


@mcp.tool()
async def flipper_screen() -> Image:
    """Get the Flipper's screen as a PNG image. Requires an agent/model that can inspect tool images."""
    return Image(data=(await request("/screen.png")).content, format="png")


@mcp.tool()
async def flipper_button(key: Literal["UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK"], long_press: bool = False) -> dict:
    """Press a Flipper physical navigation button, including press/release event sequencing."""
    return await command("button", key=key, long_press=long_press)


@mcp.tool()
async def flipper_start_app(name: str, args: str = "") -> dict:
    """Start a firmware app by its exact name/path and arguments. RPC app behavior depends on firmware and app support."""
    return await command("start_app", name=name, args=args)


@mcp.tool()
async def flipper_exit_app() -> dict:
    """Ask the currently running RPC-capable app to exit."""
    return await command("exit_app")


@mcp.tool()
async def flipper_load_file(path: str) -> dict:
    """Ask the running RPC-capable app to load a file; may trigger the app's associated operation."""
    return await command("load_file", path=path)


@mcp.tool()
async def flipper_app_button(args: str = "", index: int = 0) -> dict:
    """Send a press-release command to an RPC-capable app. Firmware/app support is required."""
    return await command("app_button", args=args, index=index)


@mcp.tool()
async def flipper_alert() -> dict:
    """Play the Flipper's audiovisual alert to identify the connected device."""
    return await command("alert")


if __name__ == "__main__":
    config = os.environ.get("FLIPPER_RELAY_CONFIG")
    if config:
        with open(config) as f:
            settings = json.load(f)
        os.environ["FLIPPER_AGENT_TOKEN"] = settings["agent_token"]
        host = settings["host"]
        os.environ["FLIPPER_RELAY_URL"] = f"http://{'[' + host + ']' if ':' in host else host}:{settings['port']}"
    mcp.run(transport="stdio")
