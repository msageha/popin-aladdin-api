"""popIn Aladdin 独自 (MAXHUB 由来) の制御プロトコルを叩く async クライアント。

公式アプリのライト操作・リモコン入力はこの経路を使う。認証・ハンドシェイク・暗号化は無い。

* TCP 30913: 6 バイトヘッダ ``struct '<IBB'`` (payload 長, op1, op2) + JSON payload。
  ライト・文字入力・音声に使う。ping (op 0/0, payload ``1``) には 6 バイトの null 応答が返る。
* UDP 16735: ASCII データグラム。方向キーは ``KEYSSTATUS:<key>+<1|0>`` (押下 / 離上)、
  ハードキーは ``KEYPRESSES:<key>``、保守コマンドは JSON (action 20000 + controlCmd)。

定数は https://github.com/kmaehashi/popin-aladdin-light (MIT) の解析に基づく。
並行呼び出しは直列化しないので、呼び出し側で制御する。
"""

import asyncio
import json
import struct
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from .errors import AladdinConnectionError, AladdinError
from .models import LightButton, ProjectorKey

REMOTE_TCP_PORT = 30913
REMOTE_UDP_PORT = 16735

LIGHT_ACTION_CODES: dict[LightButton, int] = {
    LightButton.SWITCH: 31,
    LightButton.BRIGHTER: 32,
    LightButton.DARKER: 33,
    LightButton.COOLER: 34,
    LightButton.WARMER: 35,
    LightButton.FULL: 36,
    LightButton.NIGHT: 37,
    LightButton.ON: 38,
    LightButton.OFF: 39,
    LightButton.ECO: 40,
    LightButton.SLEEP: 41,
}

DPAD_KEY_CODES: dict[ProjectorKey, int] = {
    ProjectorKey.HOME: 35,
    ProjectorKey.UP: 36,
    ProjectorKey.RIGHT: 37,
    ProjectorKey.DOWN: 38,
    ProjectorKey.OK: 49,
    ProjectorKey.LEFT: 50,
}

HARDWARE_KEY_CODES: dict[ProjectorKey, int] = {
    ProjectorKey.BACK: 48,
    ProjectorKey.VOL_UP: 115,
    ProjectorKey.VOL_DOWN: 114,
    ProjectorKey.POWER: 116,
    ProjectorKey.MENU: 139,
}

FRAME_HEADER = struct.Struct("<IBB")


def build_frame(op1: int, op2: int, payload: object) -> bytes:
    body = json.dumps(payload).encode()
    return FRAME_HEADER.pack(len(body), op1, op2) + body


class _DatagramErrors(asyncio.DatagramProtocol):
    """sendto の失敗は例外ではなく error_received に届くので、ここで保持して呼び出し元に返す。"""

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.closed = asyncio.Event()

    def error_received(self, exc: Exception) -> None:
        self.error = exc

    def connection_lost(self, exc: Exception | None) -> None:
        self.closed.set()


class RemoteClient:
    def __init__(
        self,
        host: str,
        *,
        tcp_port: int = REMOTE_TCP_PORT,
        udp_port: int = REMOTE_UDP_PORT,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.timeout = timeout

    async def ping(self) -> None:
        """TCP の疎通確認。期待する null 応答が返らなければ AladdinError。"""
        reply = await self._send_tcp(
            build_frame(0, 0, 1), reply_length=FRAME_HEADER.size
        )
        if FRAME_HEADER.unpack(reply) != (0, 0, 0):
            raise AladdinError(f"unexpected ping reply: {reply.hex()}")

    async def light(self, button: LightButton) -> None:
        await self._send_tcp(build_frame(1, 7, {"action": LIGHT_ACTION_CODES[button]}))

    async def type_text(self, text: str) -> None:
        """フォーカス中のオンスクリーン入力欄に文字を入力する。"""
        await self._send_tcp(build_frame(1, 10, {"text": text}))

    async def voice_command(self, text: str) -> None:
        """音声アシスタントへの発話をテキストとして注入する。"""
        await self._send_tcp(build_frame(1, 9, {"text": text, "success": True}))

    async def press_key(self, key: ProjectorKey, *, hold: float = 0.1) -> None:
        """リモコンキーを 1 回押す。方向キーは押下 → hold 秒 → 離上、ハードキーは単発。"""
        async with self._udp() as udp:
            if key in HARDWARE_KEY_CODES:
                udp.sendto(f"KEYPRESSES:{HARDWARE_KEY_CODES[key]}".encode())
                return
            code = DPAD_KEY_CODES[key]
            udp.sendto(f"KEYSSTATUS:{code}+1".encode())
            try:
                await asyncio.sleep(hold)
            finally:
                # デバイスが期待する離上列: 全方向キーを離上してから、押したキーをもう一度離上する。
                # hold 中にキャンセルされても押しっぱなしにしないため finally で送る。
                for other in DPAD_KEY_CODES.values():
                    udp.sendto(f"KEYSSTATUS:{other}+0".encode())
                udp.sendto(f"KEYSSTATUS:{code}+0".encode())

    async def free_memory(self) -> None:
        """バックグラウンドアプリのメモリを解放させる (controlCmd mode 9 / type 2)。"""
        await self._send_control_command(type_=2)

    async def capture(self) -> None:
        """デバイスの capture コマンドを送る (controlCmd mode 9 / type 1)。"""
        await self._send_control_command(type_=1)

    async def _send_control_command(self, *, type_: int) -> None:
        # 保守コマンドは JSON over UDP。version / appid / packageName は公式アプリが送る値。
        payload = {
            "version": "2.4.26",
            "appid": "1482854652",
            "packageName": "cc.popIn.aladdin",
            "msgid": "0",
            "action": 20000,
            "controlCmd": {"mode": 9, "type": type_, "time": 0},
        }
        async with self._udp() as udp:
            udp.sendto(json.dumps(payload).encode())

    async def _send_tcp(self, frame: bytes, *, reply_length: int = 0) -> bytes:
        """接続を 1 つ開いてフレームを 1 つ送り、``reply_length`` バイトの応答を読んで閉じる。"""
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(self.host, self.tcp_port)
                try:
                    writer.write(frame)
                    await writer.drain()
                    reply = await reader.readexactly(reply_length)
                    writer.close()
                    await writer.wait_closed()
                except BaseException:
                    # timeout / cancel 後に close() で未送信 buffer の排出を待つと無期限に
                    # 止まりうるので、失敗時は即座に捨てる。
                    writer.transport.abort()
                    raise
                return reply
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            raise AladdinConnectionError(
                f"cannot reach popIn Aladdin control port "
                f"{self.host}:{self.tcp_port}: {err}"
            ) from err

    @asynccontextmanager
    async def _udp(self) -> AsyncGenerator[asyncio.DatagramTransport]:
        loop = asyncio.get_running_loop()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                _DatagramErrors, remote_addr=(self.host, self.udp_port)
            )
            try:
                yield transport
            finally:
                transport.close()
            # close() は未送信 buffer の排出を待たないので、connection_lost まで待ってから
            # 送信エラーを判定する。待機が中断されたら排出も止め、失敗を返した後に
            # コマンドが遅れて届かないようにする。
            try:
                async with asyncio.timeout(self.timeout):
                    await protocol.closed.wait()
            except BaseException:
                transport.abort()
                raise
            if protocol.error is not None:
                raise protocol.error
        except (OSError, TimeoutError) as err:
            raise AladdinConnectionError(
                f"cannot send to popIn Aladdin control port "
                f"{self.host}:{self.udp_port}: {err}"
            ) from err
