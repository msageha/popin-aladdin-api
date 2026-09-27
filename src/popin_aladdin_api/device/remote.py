"""popIn Aladdin の独自制御プロトコルを叩く async クライアント。

公式アプリ Aladdin X (``cc.popin.aladdin.assistant`` 3.6.25) の静的解析に基づく。制御面は 3 つある。

* TCP 30913 (popIn 独自): 6 バイトヘッダ ``struct '<IBB'`` (payload 長, フレーム種別, JSON 種別) + JSON。
  種別 0 は heartbeat (同じ 0/0 の空フレームが返る)、1 は操作 (JSON 種別で内容が決まる)、
  3 は Version ハンドシェイク (クライアント ID を送るとデバイスの機種・機能一覧が返る)。
  ライト・文字入力・音声・deeplink・アプリ照会・アルバム照会に使う。
* UDP 16735 (XGIMI GMSDK のキー入力): ASCII ``KEYSSTATUS:<key>+<1|0>`` (押下 / 離上)、``KEYPRESSES:<key>`` (単発)。
* UDP 16750 (XGIMI GMSDK の JSON コマンド): ``{"action": 20000, "msgid": "2", "controlCmd": {...}}``。
  応答はクライアント側 UDP 16751 に JSON で届く。スクリーンショット・メモリ解放・実行時情報・電源断に使う。
* UDP 8100 (ブロードキャスト): デバイス発見。

PIN やトークンによる認証は無い。公式アプリは接続時に Version ハンドシェイクを送るが、
ライト・キー入力はそれ無しでも効く (kmaehashi/popin-aladdin-light の実測)。照会系は
アプリと同じ順序 (Version → 照会) で送る。並行呼び出しは直列化しないので、呼び出し側で制御する。
"""

import asyncio
import json
import socket
import struct
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel, ValidationError

from .errors import AladdinConnectionError, AladdinError
from .models import (
    AlbumFile,
    DiscoveredDevice,
    LightButton,
    ProjectorKey,
    RemoteAlbum,
    RemoteAppInfo,
    RemoteDeviceInfo,
    RemoteVersion,
)

REMOTE_TCP_PORT = 30913
REMOTE_UDP_PORT = 16735
REMOTE_CMD_UDP_PORT = 16750
REMOTE_REPLY_UDP_PORT = 16751
DISCOVERY_UDP_PORT = 8100

# TCP のフレーム種別と、種別 1 の JSON 種別 (公式アプリの BaseProtocol.getJsonType())
FRAME_HEARTBEAT = 0
FRAME_COMMAND = 1
FRAME_VERSION = 3
JSON_ALBUM = 2
JSON_REMOTE_CONTROL = 7
JSON_VOICE = 9
JSON_IME = 10
JSON_DEEPLINK = 15
JSON_APP_INFO = 16

# UDP JSON コマンドの action と、応答の action
ACTION_CONTROL = 20000
REPLY_SCREENSHOT = 30235
REPLY_DEVICE_INFO = 30410

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

# 押下と離上を続けて送るキー。公式アプリのフォーカス調整ボタン 1 回分。
FOCUS_KEY_CODES: dict[ProjectorKey, int] = {
    ProjectorKey.FOCUS_PLUS: 253,
    ProjectorKey.FOCUS_MINUS: 254,
}

HARDWARE_KEY_CODES: dict[ProjectorKey, int] = {
    ProjectorKey.BACK: 48,
    ProjectorKey.VOL_UP: 115,
    ProjectorKey.VOL_DOWN: 114,
    ProjectorKey.POWER: 116,
    ProjectorKey.MENU: 139,
    ProjectorKey.MENU_LONG: 251,
    ProjectorKey.SETTINGS: 300,
    ProjectorKey.NETFLIX: 301,
    ProjectorKey.YOUTUBE: 302,
    ProjectorKey.PRIME_VIDEO: 303,
    ProjectorKey.CUSTOM: 304,
    ProjectorKey.CUSTOM_LONG: 305,
}

# 公式アプリの HOME 長押し: 押下を 30 回送り、1 秒後に離上する。
HOME_LONG_PRESS_REPEAT = 30
HOME_LONG_PRESS_HOLD = 1.0

FRAME_HEADER = struct.Struct("<IBB")


def build_frame(kind: int, json_type: int, payload: object) -> bytes:
    body = json.dumps(payload).encode()
    return FRAME_HEADER.pack(len(body), kind, json_type) + body


class _Datagrams(asyncio.DatagramProtocol):
    """受信データグラムを送信元 IP と共に溜め、sendto の失敗 (例外ではなく error_received に届く) と close 完了を保持する。"""

    def __init__(self) -> None:
        self.received: asyncio.Queue[tuple[bytes, str]] = asyncio.Queue()
        self.error: Exception | None = None
        self.closed = asyncio.Event()

    def datagram_received(self, data: bytes, addr: Any) -> None:
        self.received.put_nowait((data, addr[0]))

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
        cmd_udp_port: int = REMOTE_CMD_UDP_PORT,
        reply_udp_port: int = REMOTE_REPLY_UDP_PORT,
        discovery_udp_port: int = DISCOVERY_UDP_PORT,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.cmd_udp_port = cmd_udp_port
        self.reply_udp_port = reply_udp_port
        self.discovery_udp_port = discovery_udp_port
        self.timeout = timeout
        # 公式アプリは端末ごとの UUID を Version ハンドシェイクで送る。ここではプロセスごとに変える。
        self.client_id = str(uuid.uuid4())

    async def ping(self) -> None:
        """TCP の疎通確認。heartbeat 応答が返らなければ AladdinConnectionError。"""
        await self._send_tcp(
            [build_frame(FRAME_HEARTBEAT, 0, 1)], reply=(FRAME_HEARTBEAT, None)
        )

    async def light(self, button: LightButton) -> None:
        await self._send_tcp(
            [
                build_frame(
                    FRAME_COMMAND,
                    JSON_REMOTE_CONTROL,
                    {"action": LIGHT_ACTION_CODES[button]},
                )
            ]
        )

    async def type_text(self, text: str) -> None:
        """フォーカス中のオンスクリーン入力欄に文字を入力する。"""
        await self._send_tcp([build_frame(FRAME_COMMAND, JSON_IME, {"text": text})])

    async def voice_command(self, text: str) -> None:
        """音声アシスタントへの発話をテキストとして注入する。"""
        await self._send_tcp(
            [build_frame(FRAME_COMMAND, JSON_VOICE, {"text": text, "success": True})]
        )

    async def open_deeplink(self, url: str) -> None:
        """deeplink (アプリの URL scheme や intent) をデバイスで開く。公式アプリのアプリ起動ボタンと同じ。"""
        await self._send_tcp(
            [build_frame(FRAME_COMMAND, JSON_DEEPLINK, {"deepLink": url})]
        )

    async def version(self) -> RemoteVersion:
        """Version ハンドシェイクでデバイスの機種・OS・ストレージ・機能一覧を得る。"""
        payload = await self._send_tcp(
            [self._version_frame()], reply=(FRAME_VERSION, None)
        )
        return _model(
            RemoteVersion,
            code=payload.get("code"),
            model=payload.get("model"),
            device_name=payload.get("device_name"),
            pid=payload.get("pid"),
            aladdin_id=payload.get("aladdinId"),
            platform=payload.get("platform"),
            os_version=payload.get("osVersion"),
            sdk_int=payload.get("sdkInt"),
            lang=payload.get("lang"),
            country=payload.get("country"),
            total_space=payload.get("totalSpace"),
            free_space=payload.get("freeSpace"),
            server_access=payload.get("serverAccess"),
            feature_access=payload.get("featureAccess"),
            capability=payload.get("capability"),
        )

    async def album(self) -> RemoteAlbum:
        """フォトメモリー (デバイス内アルバム) の枚数・容量・ライトのファームウェア版を得る。"""
        # 公式アプリが送る Album は Gson 既定値のままなので、同じ数値フィールドを付ける。
        request = {
            "actionCode": 0,
            "count": 0,
            "freeSpace": 0,
            "size": 0.0,
            "totalSpace": 0,
        }
        payload = await self._send_tcp(
            [self._version_frame(), build_frame(FRAME_COMMAND, JSON_ALBUM, request)],
            reply=(FRAME_COMMAND, JSON_ALBUM),
        )
        files = payload.get("list") or []
        if not isinstance(files, list):
            raise AladdinError(f"album list is not a list: {files!r}")
        return _model(
            RemoteAlbum,
            count=payload.get("count"),
            total_space=payload.get("totalSpace"),
            free_space=payload.get("freeSpace"),
            light_version=payload.get("lightVersion"),
            files=[
                _model(
                    AlbumFile,
                    name=item.get("name"),
                    size=item.get("size"),
                    type=item.get("type"),
                )
                for item in files
                if isinstance(item, dict)
            ],
        )

    async def app_info(self, package: str) -> RemoteAppInfo:
        """``package`` がデバイスにインストールされているかと、その版を得る。"""
        request = {"pkgName": package, "isInstalled": False, "versionCode": 0}
        payload = await self._send_tcp(
            [
                self._version_frame(),
                build_frame(FRAME_COMMAND, JSON_APP_INFO, request),
            ],
            reply=(FRAME_COMMAND, JSON_APP_INFO),
        )
        return _model(
            RemoteAppInfo,
            package=payload.get("pkgName"),
            installed=payload.get("isInstalled"),
            version_code=payload.get("versionCode"),
            version_name=payload.get("versionName"),
        )

    def _version_frame(self) -> bytes:
        # 公式アプリの Version を Gson が直列化した形。code 10 はアプリが名乗るプロトコル版。
        return build_frame(
            FRAME_VERSION,
            0,
            {
                "code": 10,
                "type": "JSON",
                "deviceId": self.client_id,
                "sdkInt": 0,
                "serverAccess": False,
                "freeSpace": 0,
                "totalSpace": 0,
            },
        )

    async def press_key(self, key: ProjectorKey, *, hold: float = 0.1) -> None:
        """リモコンキーを 1 回押す。

        方向キーは押下 → hold 秒 → 離上、フォーカス調整は押下と離上を連続、HOME 長押しは
        公式アプリと同じ列、ハードキーは単発。
        """
        # 名前で指定された host は IPv6 が先に解決されうるが、キーは IPv4 の LAN 経路にしか届かない。
        device_ip = await self._resolve_host()
        async with self._udp(
            f"key port {self.host}:{self.udp_port}",
            remote_addr=(device_ip, self.udp_port),
        ) as (udp, _):
            if key in HARDWARE_KEY_CODES:
                udp.sendto(f"KEYPRESSES:{HARDWARE_KEY_CODES[key]}".encode())
                return
            if key in FOCUS_KEY_CODES:
                code = FOCUS_KEY_CODES[key]
                udp.sendto(f"KEYSSTATUS:{code}+1".encode())
                udp.sendto(f"KEYSSTATUS:{code}+0".encode())
                return
            if key is ProjectorKey.HOME_LONG:
                code = DPAD_KEY_CODES[ProjectorKey.HOME]
                for _ in range(HOME_LONG_PRESS_REPEAT):
                    udp.sendto(f"KEYSSTATUS:{code}+1".encode())
                try:
                    await asyncio.sleep(HOME_LONG_PRESS_HOLD)
                finally:
                    udp.sendto(f"KEYSSTATUS:{code}+0".encode())
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
        await self._control_command({"mode": 9, "type": 2})

    async def power_off(self) -> None:
        """電源を切る (controlCmd mode 6 / type 0)。公式アプリの電源ボタン長押しと同じ。"""
        await self._control_command({"mode": 6, "type": 0})

    async def screenshot(self) -> str:
        """画面を撮影させ、画像の URL を返す (controlCmd mode 9 / type 1 → action 30235)。"""
        payload = await self._control_command(
            {"mode": 9, "type": 1}, reply_action=REPLY_SCREENSHOT
        )
        image_path = payload.get("imagePath")
        if not isinstance(image_path, str) or not image_path:
            raise AladdinError(f"screenshot reply has no imagePath: {payload!r}")
        # デバイスは自身の IP を入れる位置を Java の %s で返す。
        return image_path.replace("%s", self.host, 1)

    async def device_info(self) -> RemoteDeviceInfo:
        """前面アプリなど実行時の情報を得る (controlCmd mode 32 → action 30410)。"""
        payload = await self._control_command(
            {"mode": 32}, reply_action=REPLY_DEVICE_INFO
        )
        return _model(
            RemoteDeviceInfo,
            device_name=payload.get("deviceName"),
            device_mode=payload.get("deviceMode"),
            foreground_app=payload.get("deviceApp"),
            foreground_package=payload.get("packageApp"),
            runtime=payload.get("runtime"),
            rom=payload.get("deviceRom"),
            mst=payload.get("mst"),
            tips=payload.get("tips"),
        )

    async def discover(self, wait: float) -> list[DiscoveredDevice]:
        """LAN にブロードキャストし、``wait`` 秒の間に応答した Aladdin を返す。設定した host には依存しない。"""
        request = (b"aladdin" + bytes([20])).ljust(1024, b"\0")
        found: dict[str | None, DiscoveredDevice] = {}
        async with self._udp(
            f"discovery port {self.discovery_udp_port}",
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        ) as (udp, protocol):
            udp.sendto(request, ("255.255.255.255", self.discovery_udp_port))
            deadline = time.monotonic() + wait
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    async with asyncio.timeout(remaining):
                        data, _ = await protocol.received.get()
                except TimeoutError:
                    break
                device = _parse_discovery_reply(data)
                if device is not None:
                    found.setdefault(device.ip_address, device)
        return list(found.values())

    async def _control_command(
        self, control_cmd: dict[str, Any], *, reply_action: int | None = None
    ) -> dict[str, Any]:
        """JSON コマンドを UDP で送る。``reply_action`` を指定すると、その action の応答を待って返す。"""
        payload = {
            "action": ACTION_CONTROL,
            "msgid": "2",
            # 公式アプリの ControlCmd を Gson が直列化した形 (int フィールドは常に付く)。
            "controlCmd": {"type": 0, "time": 0, "delayTime": 0, **control_cmd},
        }
        device_ip = await self._resolve_host()
        # 応答は送信元ポートではなく固定の 16751 に届きうるので、そのポートに bind して送る。
        async with self._udp(
            f"command port {self.host}:{self.cmd_udp_port}",
            local_addr=("0.0.0.0", self.reply_udp_port),
        ) as (udp, protocol):
            udp.sendto(json.dumps(payload).encode(), (device_ip, self.cmd_udp_port))
            if reply_action is None:
                return {}
            try:
                async with asyncio.timeout(self.timeout):
                    while True:
                        data, sender = await protocol.received.get()
                        # 公式アプリと同じく、対象デバイス以外から届いた応答は無視する。
                        if sender != device_ip:
                            continue
                        try:
                            reply = json.loads(data)
                        except ValueError:
                            continue
                        if (
                            isinstance(reply, dict)
                            and reply.get("action") == reply_action
                        ):
                            return reply
            except TimeoutError as err:
                raise AladdinConnectionError(
                    f"no reply (action {reply_action}) from popIn Aladdin "
                    f"{self.host}:{self.cmd_udp_port} within {self.timeout}s"
                ) from err

    async def _resolve_host(self) -> str:
        """host を IPv4 アドレスにする。UDP の sendto は名前解決しない (uvloop は ValueError) ので先に解決する。"""
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                self.host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM
            )
        except OSError as err:
            raise AladdinConnectionError(
                f"cannot resolve popIn Aladdin host {self.host!r}: {err}"
            ) from err
        return str(infos[0][4][0])

    async def _send_tcp(
        self, frames: list[bytes], *, reply: tuple[int, int | None] | None = None
    ) -> dict[str, Any]:
        """接続を 1 つ開いて ``frames`` を順に送り、閉じる。

        ``reply`` (フレーム種別, JSON 種別。None は不問) を指定すると、一致するフレームが届くまで
        読み (heartbeat や先行するハンドシェイク応答は読み飛ばす)、その JSON を返す。
        """
        body = b""
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(self.host, self.tcp_port)
                try:
                    for frame in frames:
                        writer.write(frame)
                    await writer.drain()
                    if reply is not None:
                        body = await _read_until(reader, reply)
                    writer.close()
                    await writer.wait_closed()
                except BaseException:
                    # timeout / cancel 後に close() で未送信 buffer の排出を待つと無期限に
                    # 止まりうるので、失敗時は即座に捨てる。
                    writer.transport.abort()
                    raise
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            raise AladdinConnectionError(
                f"cannot reach popIn Aladdin control port "
                f"{self.host}:{self.tcp_port}: {err}"
            ) from err
        if reply is None or not body:
            return {}
        try:
            payload = json.loads(body)
        except ValueError as err:
            raise AladdinError(f"control reply is not JSON: {body[:200]!r}") from err
        if not isinstance(payload, dict):
            raise AladdinError(f"control reply is not an object: {body[:200]!r}")
        return payload

    @asynccontextmanager
    async def _udp(
        self, target: str, **endpoint: Any
    ) -> AsyncGenerator[tuple[asyncio.DatagramTransport, _Datagrams]]:
        loop = asyncio.get_running_loop()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                _Datagrams, **endpoint
            )
        except OSError as err:
            raise AladdinConnectionError(
                f"cannot send to popIn Aladdin {target}: {err}"
            ) from err
        try:
            yield transport, protocol
        finally:
            transport.close()
            # close() は未送信 buffer の排出とソケットの解放を次のループ反復に回すので、
            # 失敗時も connection_lost まで待つ。待たずに戻ると、固定ポート (応答受信) に
            # bind する次のコマンドが Address already in use になり、失敗を返した後に
            # コマンドが遅れて届きうる。待機が中断されたら排出も止める。
            try:
                async with asyncio.timeout(self.timeout):
                    await protocol.closed.wait()
            except TimeoutError as err:
                transport.abort()
                raise AladdinConnectionError(
                    f"cannot send to popIn Aladdin {target}: "
                    f"socket did not close within {self.timeout}s"
                ) from err
            except BaseException:
                transport.abort()
                raise
        if protocol.error is not None:
            raise AladdinConnectionError(
                f"cannot send to popIn Aladdin {target}: {protocol.error}"
            ) from protocol.error


async def _read_until(
    reader: asyncio.StreamReader, reply: tuple[int, int | None]
) -> bytes:
    kind, json_type = reply
    while True:
        length, frame_kind, frame_json_type = FRAME_HEADER.unpack(
            await reader.readexactly(FRAME_HEADER.size)
        )
        body = await reader.readexactly(length)
        if frame_kind == kind and json_type in (None, frame_json_type):
            return body


def _parse_discovery_reply(data: bytes) -> DiscoveredDevice | None:
    """``aladdin`` + 種別 1 バイト + 長さ + JSON ``{"success": .., "data": {...}}`` を解析する。

    長さは種別 17 では 1 バイト、それ以外 (19 / 21) では big-endian 4 バイト。形式や値の型が
    合わないデータグラム (他機器の応答など) は None。
    """
    prefix = b"aladdin"
    if not data.startswith(prefix) or len(data) < len(prefix) + 2:
        return None
    kind = data[len(prefix)]
    if kind == 17:
        start = len(prefix) + 2
        length = data[len(prefix) + 1]
    elif kind in (19, 21):
        start = len(prefix) + 5
        length = int.from_bytes(data[len(prefix) + 1 : start], "big")
    else:
        return None
    try:
        reply = json.loads(data[start : start + length])
    except ValueError:
        return None
    device = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(device, dict):
        return None
    try:
        return DiscoveredDevice(
            ip_address=device.get("ipAddress"),
            model=device.get("model"),
            name=device.get("name"),
            pid=device.get("pid"),
            mac=device.get("mac"),
            version=device.get("version"),
            zipcode=device.get("zipcode"),
            connected=device.get("isConnected"),
        )
    except ValidationError:
        # 1 台の応答が壊れていても他の応答は返す。
        return None


def _model[T: BaseModel](model_type: type[T], /, **fields: Any) -> T:
    """デバイスの応答値をモデルにする。型が合わなければ AladdinError (500 ではなく 502 にする)。"""
    try:
        return model_type(**fields)
    except ValidationError as err:
        raise AladdinError(f"unexpected value in device reply: {err}") from err
