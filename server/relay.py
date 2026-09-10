"""Single-phone, single-session Flipper RPC relay. No commands survive reconnects."""
import asyncio
import base64
import hmac
import io
import json
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import DecodeError
from PIL import Image
from pydantic import BaseModel, Field, ConfigDict

import flipper_pb2 as pb
from framing import Decoder, frame

MAX_REPLY_BYTES = 2 * 1024 * 1024


class LinkError(Exception):
    pass


class RpcError(Exception):
    pass


class Session:
    def __init__(self, websocket):
        self.ws = websocket
        self.ready = False
        self.transport = None
        self.closed = False
        self.decoder = Decoder()
        self.pending = {}
        self.next_id = 1
        self.lock = asyncio.Lock()
        self.screen = None
        self.screen_event = asyncio.Event()
        self.written = asyncio.Queue(maxsize=1)

    def abort(self, reason):
        self.closed = True
        self.ready = False
        for queue in self.pending.values():
            # Drain a full queue so failure always wakes a waiting consumer.
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(LinkError(reason))
        self.screen_event.set()
        while not self.written.empty():
            self.written.get_nowait()
        self.written.put_nowait(LinkError(reason))

    async def invalidate(self, reason):
        self.abort(reason)
        try:
            await self.ws.close(code=1011, reason=reason[:100])
        except (RuntimeError, OSError):
            pass

    def receive(self, data):
        for raw in self.decoder.feed(data):
            message = pb.Main.FromString(raw)
            if message.WhichOneof("content") == "gui_screen_frame":
                self.screen = message.gui_screen_frame
                self.screen_event.set()
            queue = self.pending.get(message.command_id)
            if queue is not None:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull as e:
                    raise LinkError("Too many RPC response fragments") from e

    async def exchange(self, name, args=None, timeout=20, write_chunks=None):
        if self.closed or not self.ready:
            raise LinkError("Phone/Flipper is not connected")
        command_id = self.next_id
        self.next_id = self.next_id % 0xFFFFFFFF + 1
        queue = asyncio.Queue(maxsize=2048)
        self.pending[command_id] = queue
        try:
            async with asyncio.timeout(timeout):
                chunks = write_chunks if write_chunks is not None else [args or {}]
                for i, params in enumerate(chunks):
                    request = pb.Main(command_id=command_id, has_next=i < len(chunks) - 1)
                    ParseDict(params, getattr(request, name))
                    getattr(request, name).SetInParent()
                    await self.ws.send_bytes(frame(request.SerializeToString()))
                    ack = await self.written.get()
                    if isinstance(ack, Exception):
                        raise ack
                replies, size = [], 0
                while True:
                    reply = await queue.get()
                    if isinstance(reply, Exception):
                        raise reply
                    if reply.command_status != pb.OK:
                        raise RpcError(pb.CommandStatus.Name(reply.command_status))
                    size += reply.ByteSize()
                    if size > MAX_REPLY_BYTES:
                        raise LinkError("RPC response exceeds 2 MiB limit")
                    replies.append(reply)
                    if not reply.has_next:
                        return replies
        except (TimeoutError, asyncio.CancelledError):
            await self.invalidate("RPC interrupted; outcome unknown; command was not retried")
            raise
        except LinkError:
            await self.invalidate("RPC connection failed; command was not retried")
            raise
        finally:
            self.pending.pop(command_id, None)

    async def call(self, name, args=None, timeout=20, write_chunks=None):
        async with self.lock:
            return await self.exchange(name, args, timeout, write_chunks)

    async def screenshot(self):
        async with self.lock:
            self.screen = None
            self.screen_event.clear()
            await self.exchange("gui_start_screen_stream_request")
            try:
                await asyncio.wait_for(self.screen_event.wait(), 10)
                if self.closed or self.screen is None:
                    raise LinkError("Screen stream disconnected")
                return self.screen
            finally:
                if not self.closed:
                    await self.exchange("gui_stop_screen_stream_request")


def screen_png(screen):
    data = screen.data
    if len(data) != 1024:
        raise RpcError("Unexpected screen frame length")
    image = Image.new("1", (128, 64), 1)
    pixels = image.load()
    for y in range(64):
        for x in range(128):
            pixels[x, y] = 0 if data[(y // 8) * 128 + x] & (1 << (y % 8)) else 1
    # Android upstream rotates vertical frames clockwise; PIL positive angles are counterclockwise.
    rotations = {0: 0, 1: 180, 2: 270, 3: 90}
    image = image.rotate(rotations.get(screen.orientation, 0), expand=True)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["ping", "device_info", "power_info", "protocol_version", "list_files", "read_file", "write_file", "mkdir", "delete_file", "start_app", "exit_app", "load_file", "app_button", "button", "alert"]
    path: str = Field(default="/ext", max_length=512)
    data_base64: str = Field(default="", max_length=1400000)
    name: str = Field(default="", max_length=256)
    args: str = Field(default="", max_length=512)
    index: int = Field(default=0, ge=0, le=2147483647)
    key: Literal["UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK"] = "OK"
    long_press: bool = False


async def execute(session, cmd):
    simple = {"ping": "system_ping_request", "device_info": "system_device_info_request",
              "power_info": "system_power_info_request", "protocol_version": "system_protobuf_version_request",
              "exit_app": "app_exit_request", "alert": "system_play_audiovisual_alert_request"}
    paths = {"list_files": "storage_list_request", "read_file": "storage_read_request",
             "mkdir": "storage_mkdir_request", "delete_file": "storage_delete_request", "load_file": "app_load_file_request"}
    if cmd.operation in paths or cmd.operation == "write_file":
        if not cmd.path.startswith("/") or "\x00" in cmd.path:
            raise ValueError("Use an absolute Flipper path")
    if cmd.operation in simple:
        replies = await session.call(simple[cmd.operation])
    elif cmd.operation in paths:
        replies = await session.call(paths[cmd.operation], {"path": cmd.path})
    elif cmd.operation == "write_file":
        try:
            data = base64.b64decode(cmd.data_base64, validate=True)
        except Exception as e:
            raise ValueError("Invalid base64 file content") from e
        if len(data) > 1024 * 1024:
            raise ValueError("Files are limited to 1 MiB per write")
        chunks = [{"path": cmd.path, "file": {"data": base64.b64encode(data[i:i+512]).decode()}}
                  for i in range(0, max(1, len(data)), 512)]
        replies = await session.call("storage_write_request", timeout=120, write_chunks=chunks)
    elif cmd.operation == "start_app":
        if not cmd.name:
            raise ValueError("Application name required")
        replies = await session.call("app_start_request", {"name": cmd.name, "args": cmd.args})
    elif cmd.operation == "app_button":
        replies = await session.call("app_button_press_release_request", {"args": cmd.args, "index": cmd.index})
    elif cmd.operation == "button":
        async with session.lock:
            await session.exchange("gui_send_input_event_request", {"key": cmd.key, "type": "PRESS"})
            try:
                if cmd.long_press:
                    await asyncio.sleep(0.7)
                    await session.exchange("gui_send_input_event_request", {"key": cmd.key, "type": "LONG"})
            finally:
                if not session.closed:
                    await session.exchange("gui_send_input_event_request", {"key": cmd.key, "type": "RELEASE"})
            if cmd.long_press:
                return {"ok": True}
            replies = await session.exchange("gui_send_input_event_request", {"key": cmd.key, "type": "SHORT"})
    else:
        raise ValueError("Unsupported operation")
    if cmd.operation == "read_file":
        data = b"".join(r.storage_read_response.file.data for r in replies)
        return {"path": cmd.path, "size": len(data), "data_base64": base64.b64encode(data).decode()}
    if cmd.operation in ("device_info", "power_info"):
        field = "system_device_info_response" if cmd.operation == "device_info" else "system_power_info_response"
        return {getattr(r, field).key: getattr(r, field).value for r in replies if r.HasField(field)}
    return {"ok": True, "responses": [MessageToDict(r, preserving_proto_field_name=True) for r in replies]}


def create_app(phone_token, agent_token):
    if min(len(phone_token), len(agent_token)) < 32 or hmac.compare_digest(phone_token, agent_token):
        raise ValueError("Configure distinct phone and agent tokens of at least 32 characters")
    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.session:
            await app.state.session.invalidate("Server stopping")
    app = FastAPI(title="Flipper Phone Relay", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.session = None

    def authorize(header):
        if not hmac.compare_digest(header or "", "Bearer " + agent_token):
            raise HTTPException(401, "Agent token required")

    def session():
        s = app.state.session
        if s is None or not s.ready or s.closed:
            raise HTTPException(503, "Phone/Flipper is not connected")
        return s

    @app.websocket("/phone")
    async def phone(ws: WebSocket):
        if not hmac.compare_digest(ws.headers.get("authorization", ""), "Bearer " + phone_token):
            await ws.close(code=1008)
            return
        if app.state.session is not None:
            await ws.close(code=1008, reason="A phone session is already connected")
            return
        s = Session(ws)
        app.state.session = s  # Reserve before the first await.
        try:
            await ws.accept()
            while True:
                # The phone can spend up to 60 seconds pairing before ready.
                message = await asyncio.wait_for(ws.receive(), 90) if not s.ready else await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    s.receive(message["bytes"])
                elif message.get("text") is not None:
                    if len(message["text"]) > 1024:
                        raise ValueError("Status too large")
                    info = json.loads(message["text"])
                    if not isinstance(info, dict):
                        raise ValueError("Status must be an object")
                    if s.ready and info.get("type") == "written":
                        if s.written.full():
                            raise ValueError("Unexpected write acknowledgement")
                        s.written.put_nowait(True)
                        continue
                    if s.ready or info.get("type") != "ready" or info.get("protocol") != 1 or info.get("transport") not in ("BLE", "USB"):
                        raise ValueError("Invalid relay status")
                    s.transport = info["transport"]
                    s.ready = True
        except (WebSocketDisconnect, RuntimeError, ValueError, LinkError, TimeoutError, DecodeError):
            pass
        finally:
            s.abort("Phone disconnected; pending commands were not retried")
            if app.state.session is s:
                app.state.session = None
            try:
                await ws.close()
            except (RuntimeError, OSError):
                pass

    @app.get("/status")
    async def status(authorization: str | None = Header(default=None)):
        authorize(authorization)
        s = app.state.session
        return {"connected": bool(s and s.ready and not s.closed), "transport": s.transport if s else None}

    @app.post("/command")
    async def command(cmd: Command, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return await execute(session(), cmd)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except RpcError as e:
            raise HTTPException(409, str(e)) from e
        except (LinkError, TimeoutError) as e:
            raise HTTPException(503, str(e) or "RPC timeout; outcome unknown; not retried") from e

    @app.get("/screen.png")
    async def screenshot(authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return Response(screen_png(await session().screenshot()), media_type="image/png", headers={"Cache-Control": "no-store"})
        except (LinkError, RpcError, TimeoutError) as e:
            raise HTTPException(503, str(e) or "Screen timeout") from e

    return app


def from_env():
    return create_app(os.environ["FLIPPER_PHONE_TOKEN"], os.environ["FLIPPER_AGENT_TOKEN"])
