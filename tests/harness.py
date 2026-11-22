"""
e2e テストの実行環境: popIn Aladdin を模した fake のデバイスと、それに接続した API サーバー。

fake のデバイスは README「プロトコルの詳細」の制御面 (UPnP の HTTP と SOAP、TCP のフレーム、
UDP のキー入力・JSON コマンド・発見) を localhost の空きポートで受け付け、受け取った操作を記録する。
API サーバーは実機に対するのと同じ経路で動く。
"""

import json
import os
import re
import secrets
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple, Self, override
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)

API_HOST = "http://127.0.0.1"
# デバイスへの各リクエストのタイムアウト (秒)。応答の無いデバイスを待つテストの所要時間になる。
API_TIMEOUT = 1.0
UDN = "uuid:5F164D4F-0000-0000-0000-54F15F164D4F-dmr"
_SERVICE_TYPES = {
    "AVTransport": "urn:schemas-upnp-org:service:AVTransport:1",
    "RenderingControl": "urn:schemas-upnp-org:service:RenderingControl:1",
    "ConnectionManager": "urn:schemas-upnp-org:service:ConnectionManager:1",
}
DEVICE_FIELDS = {
    "friendlyName": "Aladdin 2",
    "manufacturer": "Plutinosoft LLC",
    "modelName": "AV Renderer Device",
    "modelDescription": "AV Renderer Device",
}
_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
_FRAME_HEADER = struct.Struct("<IBB")
# README「独自プロトコル」の発見の要求。
_DISCOVERY_REQUEST = (b"aladdin" + bytes([0x14])).ljust(1024, b"\0")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# TCP のフレーム種別と JSON 種別 (README「独自プロトコル」)。
HEARTBEAT = (0, 0)
VERSION = (3, 0)
REMOTE_CONTROL = (1, 7)
VOICE = (1, 9)
IME = (1, 10)
DEEPLINK = (1, 15)
APP_INFO = (1, 16)
ALBUM = (1, 2)

# UDP の JSON コマンドの controlCmd の (mode, type) (README「独自プロトコル」)。
SCREENSHOT = (9, 1)
FREE_MEMORY = (9, 2)
DEVICE_INFO = (32, 0)
POWER_OFF = (6, 0)


class HttpReply(NamedTuple):
    """デバイスが返す HTTP 応答そのもの。"""

    status: int
    body: bytes
    content_type: str = 'text/xml; charset="utf-8"'


def soap_fault(*, error_code: str, description: str) -> HttpReply:
    """UPnP の SOAP fault (UPnPError を detail に持つ HTTP 500)。"""
    body = (
        f'<s:Envelope xmlns:s="{_SOAP_ENV}"><s:Body><s:Fault>'
        "<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring>"
        '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
        f"<errorCode>{escape(error_code)}</errorCode>"
        f"<errorDescription>{escape(description)}</errorDescription>"
        "</UPnPError></detail></s:Fault></s:Body></s:Envelope>"
    )
    return HttpReply(500, body.encode())


def discovery_reply(device: JsonValue, *, kind: int = 17) -> bytes:
    """発見の応答 (`aladdin` + 種別 + 長さ + JSON)。長さは種別 17 で 1 byte、19 / 21 で big-endian 4 byte。"""
    body = json.dumps({"success": True, "data": device}).encode()
    length = bytes([len(body)]) if kind == 17 else len(body).to_bytes(4, "big")
    return b"aladdin" + bytes([kind]) + length + body


class CloseConnection:
    """TCP の要求に応答を返さずに接続を閉じる。"""


CLOSE_CONNECTION = CloseConnection()
# TCP の要求への応答: 要求と同じ種別のフレームで返す JSON の値・payload の bytes そのもの・要求の
# payload から応答を作る関数、別の種別で返す `Frame`、応答を返さずに接続を閉じる `CLOSE_CONNECTION`、
# 応答しない None のどれか。
type TcpReply = (
    JsonValue
    | bytes
    | Callable[[JsonValue], JsonValue]
    | Frame
    | CloseConnection
    | None
)

_DEFAULT_SOAP_OUTPUTS: dict[str, dict[str, str]] = {
    "GetTransportInfo": {
        "CurrentTransportState": "PLAYING",
        "CurrentTransportStatus": "OK",
        "CurrentSpeed": "1",
    },
    "GetPositionInfo": {
        "Track": "1",
        "TrackDuration": "0:03:32",
        "TrackMetaData": "",
        "TrackURI": "http://192.0.2.50/video.mp4",
        "RelTime": "0:00:30",
        "AbsTime": "NOT_IMPLEMENTED",
        "RelCount": "2147483647",
        "AbsCount": "2147483647",
    },
    "GetMediaInfo": {
        "NrTracks": "1",
        "MediaDuration": "0:03:32",
        "CurrentURI": "http://192.0.2.50/video.mp4",
        "CurrentURIMetaData": "",
        "NextURI": "",
        "NextURIMetaData": "",
        "PlayMedium": "NETWORK",
        "RecordMedium": "NOT_IMPLEMENTED",
        "WriteStatus": "NOT_IMPLEMENTED",
    },
    "GetVolume": {"CurrentVolume": "35"},
    "GetMute": {"CurrentMute": "0"},
    "GetProtocolInfo": {
        "Source": "",
        "Sink": "http-get:*:video/mp4:*,http-get:*:audio/mpeg:*",
    },
}

_DEFAULT_VERSION_REPLY: dict[str, JsonValue] = {
    "code": 10,
    "type": "JSON",
    "model": "Aladdin 2",
    "device_name": "Living room",
    "pid": "PID-0001",
    "aladdinId": "aladdin-0001",
    "platform": "Android",
    "osVersion": "9",
    "sdkInt": 28,
    "lang": "ja",
    "country": "JP",
    "totalSpace": 8_000_000_000,
    "freeSpace": 2_000_000_000,
    "serverAccess": True,
    "featureAccess": {"focus": 1, "input": 1, "memory_release": 0},
    "capability": {"screenshot": 1, "app_list": None},
}

DEFAULT_ALBUM_REPLY: dict[str, JsonValue] = {
    "count": 1,
    "list": [
        {"name": "photo.jpg", "size": 1024, "type": 1},
        {"name": "photo_thumb.jpg", "size": 128, "type": 2},
    ],
    "freeSpace": 1_000_000,
    "totalSpace": 4_000_000,
    "lightVersion": "1.2.3",
}

_DEFAULT_COMMAND_REPLIES: dict[tuple[int, int], list[JsonValue | bytes]] = {
    SCREENSHOT: [{"action": 30235, "imagePath": "http://%s:7434/screenshot.png"}],
    DEVICE_INFO: [
        {
            "action": 30410,
            "deviceName": "Aladdin 2",
            "deviceMode": "normal",
            "deviceApp": "YouTube",
            "packageApp": "com.google.android.youtube.tv",
            "runtime": 3600,
            "deviceRom": 32,
            "mst": "0",
            "tips": "",
        }
    ],
}


@dataclass(frozen=True)
class SoapCall:
    """デバイスが受理した SOAP アクション。"""

    service: str
    action: str
    args: dict[str, str]


@dataclass(frozen=True)
class Frame:
    """TCP で届いたフレーム。payload は JSON を解析した値 (payload が無ければ None)。"""

    kind: int
    json_type: int
    payload: JsonValue
    # 届いた payload の bytes そのもの。payload が無いフレームと JSON の null を区別する。
    body: bytes = field(default=b"", compare=False, repr=False)
    # 届いた TCP 接続の番号 (接続を受け付けた順)。
    connection: int = field(default=0, compare=False, repr=False)


# 記録が届き切ったことを確かめるために、fake が自分に送る印。
_MARKER_PREFIX = "marker:"
# 印を送る TCP のフレーム種別。README のどの種別とも重ならない。
_MARKER_FRAME = (255, 255)


# API は操作ごとに TCP の接続を開き、送り終えると fake の処理を待たずに次を開く。listen の backlog が
# socketserver の既定の 5 だと、Linux は溢れた接続の SYN を捨て、再送までの 1 秒で API がタイムアウトする。
_LISTEN_BACKLOG = 128


class _HTTPServer(ThreadingHTTPServer):
    request_queue_size = _LISTEN_BACKLOG


class _TCPServer(socketserver.TCPServer):
    request_queue_size = _LISTEN_BACKLOG


class DiscoveryRequest(NamedTuple):
    """発見のポートに届いたデータグラムと、その IP header の宛先 address。"""

    data: bytes
    destination: str


class _DestinationUDPServer(socketserver.UDPServer):
    """直前に受けたデータグラムの宛先 address (IP_PKTINFO) を `destination` に置く。"""

    destination = ""

    @override
    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_PKTINFO, 1)
        super().server_bind()

    @override
    def get_request(self) -> tuple[tuple[bytes, socket.socket], Any]:
        # UDPServer は受けたデータグラムを同じ thread で 1 つずつ handler に渡すので、
        # handler は直前に置いた destination を読める。
        data, ancdata, _, address = self.socket.recvmsg(
            self.max_packet_size, socket.CMSG_SPACE(12)
        )
        [(_, _, info)] = ancdata
        # struct in_pktinfo の ipi_addr。Linux と macOS で同じ位置にある。
        self.destination = socket.inet_ntoa(info[8:12])
        return (data, self.socket), address


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("0.0.0.0", 0))  # noqa: S104 - API サーバーが bind するのと同じ全 interface で空きを探す
        return probe.getsockname()[1]


class FakeAladdin:
    """
    1 台の popIn Aladdin を模したサーバー群。

    UPnP は device description と、そこで宣言した controlURL の SOAP を受け付ける。TCP は README の
    フレームを読んで記録し、`respond_tcp` で登録した応答を返す。JSON コマンドの応答は、実機と同じく
    API サーバーの応答受信ポート (`reply_port`) へ送る。発見の要求には、要求の宛先 address を記録して
    127.0.0.1 から応答する。どの制御面でも、届いたが README の形式として解釈できないものは記録し、
    記録を読むときに失敗にする (送られなかったものと区別するため)。
    """

    def __init__(
        self,
        *,
        description_path: str = "/",
        relative_control_urls: bool = False,
        services: Collection[str] = tuple(_SERVICE_TYPES),
    ) -> None:
        # 記録を足したら notify_all し、記録を待つ側を起こす。
        self._lock = threading.Condition()
        self.description_path = description_path
        self._declared_control_urls = {
            name: f"{name}/control.xml"
            if relative_control_urls
            else f"/{name}/{UDN}/control.xml"
            for name in services
        }
        self._services_by_path = {
            urlsplit(urljoin(description_path, url)).path: name
            for name, url in self._declared_control_urls.items()
        }
        self._loopback = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._loopback.bind(("127.0.0.1", 0))
        self._init_state()
        self._servers: list[socketserver.BaseServer] = [
            _HTTPServer(("127.0.0.1", 0), self._http_handler()),
            _TCPServer(("127.0.0.1", 0), self._tcp_handler()),
            socketserver.UDPServer(("127.0.0.1", 0), self._key_handler()),
            socketserver.UDPServer(("127.0.0.1", 0), self._command_handler()),
            # 発見の要求は 255.255.255.255 へのブロードキャストで届くので、全 interface で受ける。
            _DestinationUDPServer(("0.0.0.0", 0), self._discovery_handler()),  # noqa: S104
        ]
        self.upnp_port, self.tcp_port, self.key_port, self.command_port = (
            _port(server) for server in self._servers[:4]
        )
        self.discovery_port = _port(self._servers[4])
        # fake の待ち受けと重ならないよう、それらを bind した後に選ぶ。
        self.reply_port = _free_udp_port()

    def _init_state(self) -> None:
        self.reachable = True
        self.description_reply: HttpReply | None = None
        self.soap_outputs = {k: dict(v) for k, v in _DEFAULT_SOAP_OUTPUTS.items()}
        self.soap_replies: dict[str, HttpReply] = {}
        self.soap_delays: dict[str, float] = {}
        # set されるまで、そのアクションの応答を保留する。
        self.soap_gates: dict[str, threading.Event] = {}
        self._tcp_replies: dict[tuple[int, int], TcpReply] = {
            HEARTBEAT: b"",
            VERSION: _DEFAULT_VERSION_REPLY,
            ALBUM: DEFAULT_ALBUM_REPLY,
            APP_INFO: self._app_info_reply,
        }
        self.installed_apps: dict[str, tuple[int, str]] = {}
        self.command_replies: dict[tuple[int, int], list[JsonValue | bytes]] = {
            k: list(v) for k, v in _DEFAULT_COMMAND_REPLIES.items()
        }
        self.discovery_replies: list[bytes] = []
        # 発見の要求を受けてから応答を送るまでの秒数。
        self.discovery_reply_delay = 0.0
        self._description_requests = 0
        self._soap_calls: list[SoapCall] = []
        self._frames: list[Frame] = []
        self._connections = 0
        # 届いたがプロトコルとして解釈できなかったもの (`<制御面>: <内容>`)。
        self._rejected: list[str] = []
        self._keys: list[tuple[float, str]] = []
        self._commands: list[JsonValue] = []
        self._discovery_requests: list[DiscoveryRequest] = []

    def __enter__(self) -> Self:
        for server in self._servers:
            # shutdown() は serve_forever が次に poll するまで待つ。既定の 0.5 秒だと、5 つのサーバーの
            # 停止だけで 2 秒近くかかる。
            threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
            ).start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        self._loopback.close()

    def reset(self) -> None:
        """登録した応答と記録を初期状態に戻す。device description の内容は変えない。"""
        with self._lock:
            self._init_state()

    def api_env(self) -> dict[str, str]:
        """この fake に接続する API サーバーの環境変数。"""
        return {
            "POPIN_ALADDIN_HOST": API_HOST,
            "UPNP_PORT": str(self.upnp_port),
            "DESCRIPTION_PATH": self.description_path,
            "CONTROL_TCP_PORT": str(self.tcp_port),
            "CONTROL_UDP_PORT": str(self.key_port),
            "CONTROL_CMD_UDP_PORT": str(self.command_port),
            "CONTROL_REPLY_UDP_PORT": str(self.reply_port),
            "DISCOVERY_UDP_PORT": str(self.discovery_port),
            "TIMEOUT": str(API_TIMEOUT),
        }

    def respond_tcp(self, frame_type: tuple[int, int], *, reply: TcpReply) -> None:
        """TCP の (フレーム種別, JSON 種別) の要求に返す応答を登録する。"""
        with self._lock:
            self._tcp_replies[frame_type] = reply

    @property
    def description_requests(self) -> int:
        with self._lock:
            return self._description_requests

    @property
    def soap_calls(self) -> list[SoapCall]:
        """受理した SOAP アクション (到着順)。"""
        self._assert_nothing_rejected()
        with self._lock:
            return list(self._soap_calls)

    @property
    def actions(self) -> list[str]:
        return [call.action for call in self.soap_calls]

    # TCP と UDP は API の応答と同期せずに届く。fake は TCP の接続と UDP のデータグラムを
    # それぞれ到着順に 1 つずつ処理するので、API の応答の後に fake が自分へ送った印が記録されれば、
    # API が先に送ったものは記録済みになる。received_* はそこまでの記録を、印を除いて返す。

    def received_frames(self) -> list[Frame]:
        """API がここまでに送った TCP のフレーム。"""
        return self._settled(
            lambda: self._frames,
            send_marker=self._send_frame_marker,
            is_marker=lambda frame, token: frame.payload == token,
        )

    def received_keys(self) -> list[str]:
        """API がここまでに送ったキー入力のデータグラム。"""
        return [key for _, key in self.received_timed_keys()]

    def received_timed_keys(self) -> list[tuple[float, str]]:
        """API がここまでに送ったキー入力のデータグラムと、fake が記録した時刻 (time.monotonic)。"""
        return self._settled(
            lambda: self._keys,
            send_marker=lambda token: self._send_datagram(token, port=self.key_port),
            is_marker=lambda key, token: key[1] == token,
        )

    def received_commands(self) -> list[JsonValue]:
        """API がここまでに送った JSON コマンド (JSON を解析した値)。"""
        return self._settled(
            lambda: self._commands,
            send_marker=lambda token: self._send_datagram(
                token, port=self.command_port
            ),
            is_marker=lambda command, token: command == token,
        )

    def wait_for_keys(self, *, count: int) -> None:
        """キー入力のデータグラムが count 個届くまで待つ。"""
        self._wait_for(lambda: list(self._keys), count=count)

    def wait_for_soap_calls(self, *, count: int) -> None:
        """SOAP アクションが count 個届くまで待つ。"""
        self._wait_for(lambda: list(self._soap_calls), count=count)

    def received_discovery_requests(self) -> list[DiscoveryRequest]:
        """API がここまでに送った発見の要求。"""
        return self._settled(
            lambda: self._discovery_requests,
            send_marker=lambda token: self._send_datagram(
                token, port=self.discovery_port
            ),
            is_marker=lambda request, token: request.data == token.encode(),
        )

    def _wait_for(self, records: Callable[[], list[object]], *, count: int) -> None:
        with self._lock:
            arrived = self._lock.wait_for(lambda: len(records()) >= count, timeout=5)
        assert arrived, f"{count} records did not arrive"

    def _settled[T](
        self,
        records: Callable[[], list[T]],
        *,
        send_marker: Callable[[str], None],
        is_marker: Callable[[T, str], bool],
    ) -> list[T]:
        token = f"{_MARKER_PREFIX}{secrets.token_hex(8)}"
        send_marker(token)

        def marked() -> list[int]:
            return [i for i, record in enumerate(records()) if is_marker(record, token)]

        with self._lock:
            assert self._lock.wait_for(marked, timeout=5), "the marker did not arrive"
            [index] = marked()
            current = records()[:index]
            del records()[index]
        self._assert_nothing_rejected()
        return current

    def _reject(self, channel: str, *, data: bytes) -> None:
        with self._lock:
            self._rejected.append(f"{channel}: {data!r}")
            self._lock.notify_all()

    def _assert_nothing_rejected(self) -> None:
        # 届いたが解釈できなかったものを、送られなかったものと区別して失敗にする。
        with self._lock:
            rejected = list(self._rejected)
        assert not rejected, f"the device received malformed data: {rejected}"

    def _send_datagram(self, text: str, *, port: int) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(text.encode(), ("127.0.0.1", port))

    def _send_frame_marker(self, token: str) -> None:
        body = json.dumps(token).encode()
        with socket.create_connection(("127.0.0.1", self.tcp_port), timeout=5) as sock:
            sock.sendall(_FRAME_HEADER.pack(len(body), *_MARKER_FRAME) + body)

    def _description_xml(self) -> bytes:
        services = "".join(
            "<service>"
            f"<serviceType>{_SERVICE_TYPES[name]}</serviceType>"
            f"<serviceId>urn:upnp-org:serviceId:{name}</serviceId>"
            f"<controlURL>{url}</controlURL>"
            "</service>"
            for name, url in self._declared_control_urls.items()
        )
        fields = "".join(f"<{k}>{v}</{k}>" for k, v in DEVICE_FIELDS.items())
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion>"
            "<device>"
            "<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>"
            f"{fields}<UDN>{UDN}</UDN><serviceList>{services}</serviceList>"
            "</device></root>"
        ).encode()

    def _soap(
        self, *, path: str, soap_action: str, body: bytes
    ) -> tuple[HttpReply, str | None]:
        """SOAP の要求を記録し、(応答, 受理したアクション) を返す。"""
        invalid = (soap_fault(error_code="401", description="Invalid Action"), None)
        service = self._services_by_path.get(path)
        if service is None:
            self._reject(f"SOAP to {path}", data=body)
            return HttpReply(404, b""), None
        service_type = _SERVICE_TYPES[service]
        declared_type, _, action = soap_action.strip('"').partition("#")
        try:
            envelope = ET.fromstring(body)
        except ET.ParseError:
            self._reject("SOAP", data=body)
            return invalid
        request_body = envelope.find(f"{{{_SOAP_ENV}}}Body")
        if (
            declared_type != service_type
            or envelope.tag != f"{{{_SOAP_ENV}}}Envelope"
            or request_body is None
            or [child.tag for child in request_body] != [f"{{{service_type}}}{action}"]
            or (request_body[0].text or "").strip()
        ):
            self._reject(f"SOAP {soap_action}", data=body)
            return invalid
        arguments = list(request_body[0])
        tags = [arg.tag for arg in arguments]
        # 引数は名前の重ならない、子要素を持たない要素。
        if len(set(tags)) != len(tags) or any(
            len(arg) or (arg.tail or "").strip() for arg in arguments
        ):
            self._reject(f"SOAP {soap_action}", data=body)
            return invalid
        args = {arg.tag: arg.text or "" for arg in arguments}
        with self._lock:
            self._soap_calls.append(SoapCall(service, action, args))
            self._lock.notify_all()
            if (reply := self.soap_replies.get(action)) is not None:
                return reply, action
            outputs = self.soap_outputs.get(action, {})
        out = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in outputs.items())
        response = (
            f'<s:Envelope xmlns:s="{_SOAP_ENV}" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action}Response xmlns:u="{service_type}">{out}</u:{action}Response>'
            "</s:Body></s:Envelope>"
        )
        return HttpReply(200, response.encode()), action

    def _hold_reply(self, action: str) -> None:
        """登録した遅延と gate の分だけ、アクションの応答を待たせる。"""
        with self._lock:
            delay = self.soap_delays.get(action, 0.0)
            gate = self.soap_gates.get(action)
        time.sleep(delay)
        if gate is not None:
            gate.wait(timeout=5)

    def _http_handler(self) -> type[BaseHTTPRequestHandler]:
        device = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if urlsplit(self.path).path != device.description_path:
                    self._reply(HttpReply(404, b""))
                    return
                with device._lock:
                    device._description_requests += 1
                    reply = device.description_reply
                self._reply(reply or HttpReply(200, device._description_xml()))

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if not device.reachable:
                    # 応答を返さずに切断し、途中で通信が切れたデバイスを模す。
                    self.close_connection = True
                    return
                if not self.headers.get("Content-Type", "").startswith("text/xml"):
                    device._reject("SOAP without text/xml", data=body)
                    self._reply(HttpReply(415, b""))
                    return
                reply, action = device._soap(
                    path=urlsplit(self.path).path,
                    soap_action=self.headers.get("SOAPACTION", ""),
                    body=body,
                )
                if action is not None:
                    device._hold_reply(action)
                self._reply(reply)

            def _reply(self, reply: HttpReply) -> None:
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            @override
            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler

    def _app_info_reply(self, request: JsonValue) -> JsonValue:
        assert isinstance(request, dict)
        package = request["pkgName"]
        assert isinstance(package, str)
        version_code, version_name = self.installed_apps.get(package, (0, ""))
        return {
            "pkgName": package,
            "isInstalled": package in self.installed_apps,
            "versionCode": version_code,
            "versionName": version_name,
        }

    def _tcp_reply(self, frame: Frame) -> bytes | CloseConnection | None:
        """フレームを記録し、返すフレームの bytes (CLOSE_CONNECTION か、返さないなら None) を返す。"""
        with self._lock:
            self._frames.append(frame)
            self._lock.notify_all()
            reply = self._tcp_replies.get((frame.kind, frame.json_type))
        if reply is None or isinstance(reply, CloseConnection):
            return reply
        if isinstance(reply, Frame):
            body = json.dumps(reply.payload).encode()
            return _FRAME_HEADER.pack(len(body), reply.kind, reply.json_type) + body
        if callable(reply):
            reply = reply(frame.payload)
        body = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
        return _FRAME_HEADER.pack(len(body), frame.kind, frame.json_type) + body

    def _tcp_handler(self) -> type[socketserver.BaseRequestHandler]:
        device = self

        class Handler(socketserver.StreamRequestHandler):
            timeout = 5

            @override
            def handle(self) -> None:
                with device._lock:
                    device._connections += 1
                    connection = device._connections
                try:
                    while header := self.rfile.read(_FRAME_HEADER.size):
                        # ヘッダや宣言した長さに満たない bytes は、実機も読み切れない。
                        if len(header) < _FRAME_HEADER.size:
                            device._reject("TCP", data=header)
                            return
                        length, kind, json_type = _FRAME_HEADER.unpack(header)
                        body = self.rfile.read(length)
                        if len(body) < length:
                            device._reject("TCP", data=header + body)
                            return
                        try:
                            payload = json.loads(body) if body else None
                        except ValueError:
                            device._reject("TCP", data=header + body)
                            return
                        reply = device._tcp_reply(
                            Frame(
                                kind,
                                json_type,
                                payload,
                                body=body,
                                connection=connection,
                            )
                        )
                        if isinstance(reply, CloseConnection):
                            return
                        if reply is not None:
                            self.wfile.write(reply)
                except OSError:
                    return

        return Handler

    def _key_handler(self) -> type[socketserver.BaseRequestHandler]:
        device = self

        class Handler(socketserver.BaseRequestHandler):
            @override
            def handle(self) -> None:
                data, _ = self.request
                try:
                    key = data.decode("ascii")
                except UnicodeDecodeError:
                    device._reject("key", data=data)
                    return
                with device._lock:
                    device._keys.append((time.monotonic(), key))
                    device._lock.notify_all()

        return Handler

    def _command_handler(self) -> type[socketserver.BaseRequestHandler]:
        device = self

        class Handler(socketserver.BaseRequestHandler):
            @override
            def handle(self) -> None:
                data, sock = self.request
                if data.startswith(_MARKER_PREFIX.encode()):
                    with device._lock:
                        device._commands.append(data.decode())
                        device._lock.notify_all()
                    return
                try:
                    command: JsonValue = json.loads(data)
                except ValueError:
                    device._reject("command", data=data)
                    return
                match command:
                    case {
                        "controlCmd": {
                            "mode": int() as mode,
                            "type": int() as command_type,
                        }
                    }:
                        pass
                    case _:
                        device._reject("command", data=data)
                        return
                with device._lock:
                    device._commands.append(command)
                    device._lock.notify_all()
                    replies = device.command_replies.get((mode, command_type), [])
                for reply in replies:
                    # 実機は送信元ポートではなく、応答受信用の固定ポートへ返す。
                    payload = (
                        reply
                        if isinstance(reply, bytes)
                        else json.dumps(reply).encode()
                    )
                    sock.sendto(payload, ("127.0.0.1", device.reply_port))

        return Handler

    def _discovery_handler(self) -> type[socketserver.BaseRequestHandler]:
        device = self

        class Handler(socketserver.BaseRequestHandler):
            @override
            def handle(self) -> None:
                data, _ = self.request
                assert isinstance(self.server, _DestinationUDPServer)
                request = DiscoveryRequest(data, destination=self.server.destination)
                with device._lock:
                    device._discovery_requests.append(request)
                    device._lock.notify_all()
                    replies = list(device.discovery_replies)
                    delay = device.discovery_reply_delay
                # 待ち受けは LAN にも開いているので、発見の要求の形をしたものにだけ応答する。
                if data != _DISCOVERY_REQUEST:
                    return
                time.sleep(delay)
                # 要求はブロードキャストなので LAN の address から届くが、fake のデバイスは
                # 127.0.0.1 にいるので、応答は loopback から送る。
                for reply in replies:
                    device._loopback.sendto(
                        reply, ("127.0.0.1", self.client_address[1])
                    )

        return Handler


def _port(server: socketserver.BaseServer) -> int:
    assert isinstance(server, socketserver.TCPServer | socketserver.UDPServer)
    return server.server_address[1]


@dataclass(frozen=True)
class Stack:
    """fake のデバイスと、それに接続した API サーバー。"""

    device: FakeAladdin
    api: httpx.Client


API_COMMAND = [
    sys.executable,
    "-m",
    "uvicorn",
    "popin_aladdin_api.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "0",
    "--no-access-log",
]
_STARTED_RE = re.compile(r"Uvicorn running on (http://\S+)")


def _isolated_env(settings: Mapping[str, str]) -> dict[str, str]:
    """
    API サーバーに渡す環境変数。実行環境からは coverage の計測に使う変数だけを引き継ぐ。

    settings は名前の大小文字を区別せずに読み、mise の [env] は実機の POPIN_ALADDIN_HOST を渡すので、
    実行環境の変数が残ると実機に接続しうる。
    """
    env = {k: v for k, v in os.environ.items() if k.startswith("COVERAGE_")}
    return env | dict(settings)


@contextmanager
def run_api(settings: Mapping[str, str], *, log_path: Path) -> Generator[httpx.Client]:
    """
    `uvicorn popin_aladdin_api.main:app` を subprocess として起動する。

    settings は API サーバーの環境変数で、通常は `FakeAladdin.api_env` の値。
    """
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - 引数は固定値と sys.executable だけ
            API_COMMAND,
            cwd=_PROJECT_ROOT,
            env=_isolated_env(settings),
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
    try:
        url = _wait_until_started(process, log_path=log_path)
    except BaseException:
        # 起動の失敗に加え、待機中の中断 (Ctrl-C 等) でもサーバーを残さない。
        process.kill()
        process.wait()
        raise
    try:
        # 実行環境の HTTP_PROXY などを使わず、loopback の API サーバーへ直接つなぐ。
        with httpx.Client(base_url=url, trust_env=False, timeout=30) as api:
            yield api
    finally:
        _stop(process, log_path=log_path)


@contextmanager
def serve_stack(
    log_path: Path, *, device: FakeAladdin | None = None
) -> Generator[Stack]:
    """fake のデバイス (省略時は既定の設定) と、それに接続した API サーバーを 1 組起動する。"""
    with (
        device or FakeAladdin() as fake,
        run_api(fake.api_env(), log_path=log_path) as api,
    ):
        yield Stack(fake, api)


def _stop(process: subprocess.Popen[bytes], *, log_path: Path) -> None:
    """SIGTERM で終了させ、lifespan の終了処理と coverage の保存を通す。途中で落ちていたら失敗にする。"""
    if process.poll() is not None:
        raise RuntimeError(
            f"API server exited during the tests:\n{log_path.read_text(encoding='utf-8')}"
        )
    process.terminate()
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        returncode = None
    # uvicorn は終了処理の後に SIGTERM を投げ直して終わる。
    if returncode not in {0, -signal.SIGTERM}:
        raise RuntimeError(
            f"API server did not stop cleanly ({returncode}):\n"
            f"{log_path.read_text(encoding='utf-8')}"
        )


def _wait_until_started(process: subprocess.Popen[bytes], *, log_path: Path) -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        output = log_path.read_text(encoding="utf-8")
        if match := _STARTED_RE.search(output):
            return match.group(1)
        if process.poll() is not None:
            raise RuntimeError(f"API server exited during startup:\n{output}")
        time.sleep(0.01)
    raise RuntimeError(
        f"API server did not start in time:\n{log_path.read_text(encoding='utf-8')}"
    )
