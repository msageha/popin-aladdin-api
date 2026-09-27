import asyncio
import json
import socket

import pytest

from popin_aladdin_api.device.errors import AladdinConnectionError, AladdinError
from popin_aladdin_api.device.models import LightButton, ProjectorKey
from popin_aladdin_api.device.remote import (
    DPAD_KEY_CODES,
    FRAME_HEADER,
    HARDWARE_KEY_CODES,
    LIGHT_ACTION_CODES,
    RemoteClient,
    build_frame,
)

pytestmark = pytest.mark.anyio


class TcpRecorder:
    """受信したフレームを記録し、ping には設定された応答を返す TCP サーバー。"""

    def __init__(self) -> None:
        self.port = 0
        self.frames: list[tuple[int, int, object]] = []
        self.ping_reply = bytes(FRAME_HEADER.size)

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        length, op1, op2 = FRAME_HEADER.unpack(
            await reader.readexactly(FRAME_HEADER.size)
        )
        payload = json.loads(await reader.readexactly(length))
        self.frames.append((op1, op2, payload))
        if (op1, op2) == (0, 0):
            writer.write(self.ping_reply)
            await writer.drain()
        writer.close()


class UdpRecorder(asyncio.DatagramProtocol):
    """受信したデータグラムを記録し、reply が設定されていれば送信元へ返す UDP サーバー。"""

    def __init__(self) -> None:
        self.port = 0
        self.messages: list[str] = []
        self.reply: bytes | None = None
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.messages.append(data.decode())
        if self.reply is not None and self.transport is not None:
            self.transport.sendto(self.reply, addr)


@pytest.fixture
async def tcp():
    recorder = TcpRecorder()
    server = await asyncio.start_server(recorder.handle, "127.0.0.1", 0)
    recorder.port = server.sockets[0].getsockname()[1]
    async with server:
        yield recorder


async def _udp_recorder():
    loop = asyncio.get_running_loop()
    transport, recorder = await loop.create_datagram_endpoint(
        UdpRecorder, local_addr=("127.0.0.1", 0)
    )
    recorder.port = transport.get_extra_info("sockname")[1]
    try:
        yield recorder
    finally:
        transport.close()


udp = pytest.fixture(_udp_recorder, name="udp")
cmd_udp = pytest.fixture(_udp_recorder, name="cmd_udp")


@pytest.fixture
def client(tcp: TcpRecorder, udp: UdpRecorder, cmd_udp: UdpRecorder) -> RemoteClient:
    # 応答待ち受けポートは 0 (空きポート) にし、テストサーバーは送信元へ返す。
    return RemoteClient(
        "127.0.0.1",
        tcp_port=tcp.port,
        udp_port=udp.port,
        cmd_udp_port=cmd_udp.port,
        reply_udp_port=0,
        timeout=2,
    )


async def received[T](items: list[T], count: int) -> list[T]:
    """サーバー側の記録は送信と非同期なので、期待数が揃うまで少し待つ。"""
    for _ in range(100):
        if len(items) >= count:
            break
        await asyncio.sleep(0.01)
    return items


def test_frame_layout_matches_protocol():
    data = build_frame(1, 7, {"action": 38})
    length, op1, op2 = FRAME_HEADER.unpack(data[:6])
    assert (op1, op2) == (1, 7)
    assert length == len(data) - 6
    assert json.loads(data[6:]) == {"action": 38}


async def test_ping_accepts_null_reply(client: RemoteClient, tcp: TcpRecorder):
    await client.ping()
    assert tcp.frames == [(0, 0, 1)]


async def test_ping_rejects_unexpected_reply(client: RemoteClient, tcp: TcpRecorder):
    tcp.ping_reply = FRAME_HEADER.pack(0, 1, 1)
    with pytest.raises(AladdinError):
        await client.ping()


async def test_light_text_voice_frames(client: RemoteClient, tcp: TcpRecorder):
    await client.light(LightButton.ON)
    await client.type_text("hello")
    await client.voice_command("つけて")
    assert await received(tcp.frames, 3) == [
        (1, 7, {"action": LIGHT_ACTION_CODES[LightButton.ON]}),
        (1, 10, {"text": "hello"}),
        (1, 9, {"text": "つけて", "success": True}),
    ]


async def test_dpad_key_press_release_sequence(client: RemoteClient, udp: UdpRecorder):
    await client.press_key(ProjectorKey.DOWN, hold=0)
    code = DPAD_KEY_CODES[ProjectorKey.DOWN]
    messages = await received(udp.messages, len(DPAD_KEY_CODES) + 2)
    assert messages[0] == f"KEYSSTATUS:{code}+1"
    assert set(messages[1:-1]) == {f"KEYSSTATUS:{k}+0" for k in DPAD_KEY_CODES.values()}
    assert messages[-1] == f"KEYSSTATUS:{code}+0"


async def test_hardware_key_single_press(client: RemoteClient, udp: UdpRecorder):
    await client.press_key(ProjectorKey.BACK)
    assert await received(udp.messages, 1) == [
        f"KEYPRESSES:{HARDWARE_KEY_CODES[ProjectorKey.BACK]}"
    ]


async def test_maintenance_commands(client: RemoteClient, cmd_udp: UdpRecorder):
    cmd_udp.reply = json.dumps(
        {"action": 30235, "imagePath": "http://%s:7434/screenshot.png"}
    ).encode()
    await client.free_memory()
    url = await client.screenshot()
    messages = [json.loads(m) for m in await received(cmd_udp.messages, 2)]
    assert all(m["action"] == 20000 for m in messages)
    assert all(m["msgid"] == "2" for m in messages)
    assert [m["controlCmd"] for m in messages] == [
        {"mode": 9, "type": 2, "time": 0, "delayTime": 0},
        {"mode": 9, "type": 1, "time": 0, "delayTime": 0},
    ]
    assert url == "http://127.0.0.1:7434/screenshot.png"


async def test_closed_tcp_port_is_connection_error():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = RemoteClient("127.0.0.1", tcp_port=port, timeout=2)
    with pytest.raises(AladdinConnectionError):
        await client.ping()
