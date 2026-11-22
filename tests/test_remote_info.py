"""
制御ポート (TCP) の照会: POST /api/remote/ping と GET /api/remote/version・album・apps/{package}。
"""

import uuid
from typing import Any

import pytest
from hypothesis import example, given, strategies as st

from tests.harness import (
    ALBUM,
    APP_INFO,
    CLOSE_CONNECTION,
    DEFAULT_ALBUM_REPLY,
    HEARTBEAT,
    REMOTE_CONTROL,
    VERSION,
    Frame,
    JsonValue,
    Stack,
    TcpReply,
)
from tests.strategies import as_json

# デバイスの応答のフィールド名 → API の応答のフィールド名。
_VERSION_FIELDS = {
    "code": "code",
    "model": "model",
    "device_name": "device_name",
    "pid": "pid",
    "aladdinId": "aladdin_id",
    "platform": "platform",
    "osVersion": "os_version",
    "sdkInt": "sdk_int",
    "lang": "lang",
    "country": "country",
    "totalSpace": "total_space",
    "freeSpace": "free_space",
    "serverAccess": "server_access",
    "featureAccess": "feature_access",
    "capability": "capability",
}
# JSON で表せ、応答として返せる文字列 (孤立した surrogate を含まない)。
_text = st.text(alphabet=st.characters(exclude_categories=["Cs"]))
_flags = st.none() | st.dictionaries(_text, st.none() | st.integers(), max_size=3)
_VERSION_VALUES: dict[str, st.SearchStrategy[Any]] = {
    "code": st.none() | st.integers(),
    "model": st.none() | _text,
    "device_name": st.none() | _text,
    "pid": st.none() | _text,
    "aladdinId": st.none() | _text,
    "platform": st.none() | _text,
    "osVersion": st.none() | _text,
    "sdkInt": st.none() | st.integers(),
    "lang": st.none() | _text,
    "country": st.none() | _text,
    "totalSpace": st.none() | st.integers(),
    "freeSpace": st.none() | st.integers(),
    "serverAccess": st.none() | st.booleans(),
    "featureAccess": _flags,
    "capability": _flags,
}
_unknown_fields = st.dictionaries(
    _text.filter(lambda name: name not in _VERSION_FIELDS),
    st.none() | st.booleans() | st.integers() | _text,
    max_size=3,
)


def test_ping_sends_heartbeat_and_succeeds_on_reply(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.post("/api/remote/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    [frame] = stack.device.received_frames()
    assert (frame.kind, frame.json_type) == HEARTBEAT
    # docs/protocol.md: heartbeat の payload は無いか 1。
    assert frame.body == b"" or as_json(frame.payload) == "1"


@pytest.mark.parametrize(
    "reply",
    [CLOSE_CONNECTION, Frame(*REMOTE_CONTROL, {"action": 38})],
    ids=["closed", "other-frame"],
)
def test_ping_without_heartbeat_reply_is_504(*, stack: Stack, reply: TcpReply) -> None:
    stack.device.reset()
    stack.device.respond_tcp(HEARTBEAT, reply=reply)

    response = stack.api.post("/api/remote/ping")

    assert response.status_code == 504


def test_version_handshake_identifies_this_client(stack: Stack) -> None:
    stack.device.reset()

    assert stack.api.get("/api/remote/version").status_code == 200
    assert stack.api.get("/api/remote/version").status_code == 200

    client_ids: list[JsonValue] = []
    for frame in stack.device.received_frames():
        assert (frame.kind, frame.json_type) == VERSION
        assert isinstance(frame.payload, dict)
        assert (frame.payload["code"], frame.payload["type"]) == (10, "JSON")
        client_ids.append(frame.payload["deviceId"])
    [client_id, again] = client_ids
    assert isinstance(client_id, str)
    # docs/protocol.md: deviceId はクライアントの UUID。
    uuid.UUID(client_id)
    # 公式アプリと同じく、1 つのクライアントは同じ ID を名乗る。
    assert again == client_id


@given(
    reply=st.fixed_dictionaries({}, optional=_VERSION_VALUES),
    unknown=_unknown_fields,
)
@example(reply={}, unknown={})
@example(reply=dict.fromkeys(_VERSION_FIELDS), unknown={})
def test_version_reports_device_reply_fields(
    *, stack: Stack, reply: dict[str, Any], unknown: dict[str, Any]
) -> None:
    stack.device.reset()
    stack.device.respond_tcp(VERSION, reply=unknown | reply)

    response = stack.api.get("/api/remote/version")

    assert response.status_code == 200
    expected = {api: reply.get(device) for device, api in _VERSION_FIELDS.items()}
    assert as_json(response.json()) == as_json(expected)


@pytest.mark.parametrize(
    "reply",
    [
        b"not json",
        b"[1, 2]",
        b'"text"',
        b'{"model": "\\ud800"}',
        {"model": 1},
        {"sdkInt": "twenty"},
    ],
    ids=[
        "not-json",
        "array",
        "string",
        "lone-surrogate",
        "model-not-string",
        "sdk-int-not-integer",
    ],
)
def test_unexpected_version_reply_is_502(
    *, stack: Stack, reply: JsonValue | bytes
) -> None:
    stack.device.reset()
    stack.device.respond_tcp(VERSION, reply=reply)

    response = stack.api.get("/api/remote/version")

    assert response.status_code == 502


def test_album_reports_photos_and_light_version(stack: Stack) -> None:
    stack.device.reset()

    response = stack.api.get("/api/remote/album")

    assert response.status_code == 200
    assert response.json() == {
        "count": DEFAULT_ALBUM_REPLY["count"],
        "total_space": DEFAULT_ALBUM_REPLY["totalSpace"],
        "free_space": DEFAULT_ALBUM_REPLY["freeSpace"],
        "light_version": DEFAULT_ALBUM_REPLY["lightVersion"],
        "files": DEFAULT_ALBUM_REPLY["list"],
    }
    # docs/protocol.md: 公式アプリと同じく、同じ接続で Version ハンドシェイクの後に照会する。
    version, album = stack.device.received_frames()
    assert (version.kind, version.json_type) == VERSION
    assert (album.kind, album.json_type) == ALBUM
    assert album.connection == version.connection


@pytest.mark.parametrize(
    "reply",
    [
        {"count": 0, "list": "photo.jpg"},
        {"count": "many", "list": []},
        {"count": 1, "list": [{"name": "a.jpg", "size": "big", "type": 1}]},
    ],
    ids=["list-not-array", "count-not-integer", "size-not-integer"],
)
def test_unexpected_album_reply_is_502(*, stack: Stack, reply: dict[str, Any]) -> None:
    stack.device.reset()
    stack.device.respond_tcp(ALBUM, reply=reply)

    response = stack.api.get("/api/remote/album")

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (
            {"isInstalled": True, "versionCode": 4_010_000, "versionName": "4.1.0"},
            {"installed": True, "version_code": 4_010_000, "version_name": "4.1.0"},
        ),
        (
            {"isInstalled": False, "versionCode": 0, "versionName": ""},
            {"installed": False, "version_code": 0, "version_name": ""},
        ),
    ],
    ids=["installed", "not-installed"],
)
def test_app_reports_installation_and_version(
    *,
    stack: Stack,
    installed: dict[str, JsonValue],
    expected: dict[str, Any],
) -> None:
    stack.device.reset()
    stack.device.respond_tcp(
        APP_INFO, reply={"pkgName": "jp.co.tver.tvapp"} | installed
    )

    response = stack.api.get("/api/remote/apps/jp.co.tver.tvapp")

    assert response.status_code == 200
    assert as_json(response.json()) == as_json(
        {"package": "jp.co.tver.tvapp"} | expected
    )
    version, query = stack.device.received_frames()
    assert (version.kind, version.json_type) == VERSION
    assert (query.kind, query.json_type) == APP_INFO
    assert query.connection == version.connection
    assert isinstance(query.payload, dict)
    assert query.payload["pkgName"] == "jp.co.tver.tvapp"


@pytest.mark.parametrize(
    "package", ["tver", "1jp.tver", "jp..tver", "jp.tver-app", "jp.tver.", "jp.1tver"]
)
def test_package_that_is_not_an_android_package_name_is_422(
    *, stack: Stack, package: str
) -> None:
    stack.device.reset()

    response = stack.api.get(f"/api/remote/apps/{package}")

    assert response.status_code == 422
