import asyncio
import base64
import io
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import flipper_pb2 as pb
import gui_pb2
from framing import Decoder, frame
from relay import Command, LinkError, RpcError, Session, create_app, execute, screen_png

PHONE = "p" * 40
AGENT = "a" * 40
AUTH = {"Authorization": "Bearer " + AGENT}


def test_framing_arbitrary_packet_boundaries():
    payloads = [bytes([n % 256]) * n for n in (1, 127, 128, 1024, 65536)]
    stream = b"".join(map(frame, payloads))
    decoder, actual = Decoder(), []
    random.seed(42)
    while stream:
        size = random.randint(1, 700)
        actual.extend(decoder.feed(stream[:size]))
        stream = stream[size:]
    assert actual == payloads
    assert decoder.buffer == b""


@pytest.mark.parametrize("bad", [b"\x00", b"\xff" * 5, b"\x81\x80\x04"])
def test_bad_frame_is_rejected(bad):
    with pytest.raises(ValueError):
        Decoder().feed(bad)


def test_auth_and_no_phone():
    with TestClient(create_app(PHONE, AGENT)) as client:
        assert client.get("/status").status_code == 401
        assert client.get("/status", headers={"Authorization": "Bearer " + PHONE}).status_code == 401
        assert client.get("/status", headers=AUTH).json()["connected"] is False
        assert client.post("/command", headers=AUTH, json={"operation": "ping"}).status_code == 503
        with pytest.raises(Exception):
            with client.websocket_connect("/phone", headers=AUTH):
                pass


@pytest.mark.parametrize("transport", ["BLE", "USB"])
def test_websocket_phone_to_http_agent_roundtrip(transport):
    with TestClient(create_app(PHONE, AGENT)) as client:
        with client.websocket_connect("/phone", headers={"Authorization": "Bearer " + PHONE}) as phone:
            phone.send_json({"type": "ready", "protocol": 1, "transport": transport})
            # Barrier: the socket's ready message must be processed before the request.
            for _ in range(100):
                state = client.get("/status", headers=AUTH).json()
                if state["connected"]:
                    break
            assert state == {"connected": True, "transport": transport}
            with ThreadPoolExecutor() as pool:
                request = pool.submit(client.post, "/command", headers=AUTH, json={"operation": "device_info"})
                wire = phone.receive_bytes()
                message = pb.Main.FromString(Decoder().feed(wire)[0])
                assert message.WhichOneof("content") == "system_device_info_request"
                phone.send_json({"type": "written"})
                for i, (key, value) in enumerate([("name", "TestFlipper"), ("firmware", "test")]):
                    reply = pb.Main(command_id=message.command_id, has_next=i == 0)
                    reply.system_device_info_response.key = key
                    reply.system_device_info_response.value = value
                    packed = frame(reply.SerializeToString())
                    phone.send_bytes(packed[:2])
                    phone.send_bytes(packed[2:])
                response = request.result(timeout=5)
                assert response.status_code == 200
                assert response.json() == {"name": "TestFlipper", "firmware": "test"}


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.session = None
        self.closed = False
        self.reply = True

    async def send_bytes(self, data):
        req = pb.Main.FromString(Decoder().feed(data)[0])
        self.sent.append(req)
        self.session.written.put_nowait(True)
        if self.reply and not req.has_next:
            response = pb.Main(command_id=req.command_id)
            response.empty.SetInParent()
            self.session.receive(frame(response.SerializeToString()))

    async def close(self, **kwargs):
        self.closed = True


def session():
    socket = FakeSocket()
    s = Session(socket)
    socket.session = s
    s.ready = True
    return s, socket


@pytest.mark.asyncio
async def test_write_file_chunks_share_id_and_end_flag():
    s, socket = session()
    content = bytes(range(256)) * 9
    result = await execute(s, Command(operation="write_file", path="/ext/test.bin", data_base64=base64.b64encode(content).decode()))
    assert result["ok"]
    assert len(socket.sent) == 5
    assert len({r.command_id for r in socket.sent}) == 1
    assert [r.has_next for r in socket.sent] == [True, True, True, True, False]
    assert b"".join(r.storage_write_request.file.data for r in socket.sent) == content


@pytest.mark.asyncio
async def test_empty_file_still_sends_one_terminal_chunk():
    s, socket = session()
    await execute(s, Command(operation="write_file", path="/ext/empty", data_base64=""))
    assert len(socket.sent) == 1 and not socket.sent[0].has_next


@pytest.mark.asyncio
async def test_timeout_invalidates_session_and_does_not_replay():
    s, socket = session()
    socket.reply = False
    with pytest.raises(TimeoutError):
        await s.call("system_ping_request", timeout=0.01)
    assert socket.closed and s.closed and len(socket.sent) == 1
    with pytest.raises(LinkError):
        await s.call("system_ping_request")
    assert len(socket.sent) == 1


@pytest.mark.asyncio
async def test_disconnect_fails_waiter():
    s, socket = session()
    socket.reply = False
    task = asyncio.create_task(s.call("system_ping_request"))
    await asyncio.sleep(0)
    s.abort("disconnected")
    with pytest.raises(LinkError):
        await asyncio.wait_for(task, 1)
    assert not s.pending


@pytest.mark.asyncio
async def test_short_and_long_button_event_order():
    s, socket = session()
    await execute(s, Command(operation="button", key="BACK"))
    assert [r.gui_send_input_event_request.type for r in socket.sent] == [gui_pb2.PRESS, gui_pb2.RELEASE, gui_pb2.SHORT]
    socket.sent.clear()
    await execute(s, Command(operation="button", key="OK", long_press=True))
    assert [r.gui_send_input_event_request.type for r in socket.sent] == [gui_pb2.PRESS, gui_pb2.LONG, gui_pb2.RELEASE]


def test_screen_uses_vertical_bit_packing():
    data = bytearray(1024)
    data[128 + 3] = 1 << 2
    image = Image.open(io.BytesIO(screen_png(gui_pb2.ScreenFrame(data=bytes(data)))))
    assert image.size == (128, 64)
    assert image.getpixel((3, 10)) == 0
    assert image.getpixel((3, 11)) != 0
    vertical = Image.open(io.BytesIO(screen_png(gui_pb2.ScreenFrame(data=bytes(data), orientation=gui_pb2.VERTICAL))))
    assert vertical.size == (64, 128)
    assert vertical.getpixel((53, 3)) == 0


@pytest.mark.asyncio
async def test_invalid_base64_does_not_reach_device():
    s, socket = session()
    with pytest.raises(ValueError):
        await execute(s, Command(operation="write_file", path="/ext/a", data_base64="!!"))
    assert not socket.sent
