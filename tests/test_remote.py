import json
import struct

import pytest

from aladdin.remote import (
    CEILING_BUTTONS,
    PROJECTOR_KEYS,
    PROJECTOR_STATELESS_KEYS,
    AladdinRemoteClient,
    all_buttons,
)

pytestmark = pytest.mark.unit

_HEADER = "<IBB"


def _client(monkeypatch):
    client = AladdinRemoteClient("http://172.16.1.113", timeout=1)
    tcp: list[bytes] = []
    udp: list[str] = []
    monkeypatch.setattr(client, "_send_tcp", lambda data, **kw: tcp.append(data))
    monkeypatch.setattr(client, "_send_udp", lambda msg: udp.append(msg))
    return client, tcp, udp


def test_host_parsed_from_url():
    client = AladdinRemoteClient("http://172.16.1.113")
    assert client.host == "172.16.1.113"
    assert client.tcp_port == 30913
    assert client.udp_port == 16735


def test_pack_layout_matches_protocol():
    data = AladdinRemoteClient._pack(1, 7, {"action": 38})
    payload_len, op1, op2 = struct.unpack(_HEADER, data[:6])
    payload = data[6:]
    assert (op1, op2) == (1, 7)
    assert payload_len == len(payload)
    assert json.loads(payload) == {"action": 38}


def test_light_sends_correct_frame(monkeypatch):
    client, tcp, _ = _client(monkeypatch)
    client.light("on")
    payload_len, op1, op2 = struct.unpack(_HEADER, tcp[0][:6])
    assert (op1, op2) == (1, 7)
    assert json.loads(tcp[0][6:]) == {"action": CEILING_BUTTONS["on"]}


def test_light_rejects_unknown(monkeypatch):
    client, _, _ = _client(monkeypatch)
    with pytest.raises(ValueError):
        client.light("strobe")


def test_text_uses_op2_10(monkeypatch):
    client, tcp, _ = _client(monkeypatch)
    client.text("hello")
    _, op1, op2 = struct.unpack(_HEADER, tcp[0][:6])
    assert (op1, op2) == (1, 10)
    assert json.loads(tcp[0][6:]) == {"text": "hello"}


def test_voice_uses_op2_9(monkeypatch):
    client, tcp, _ = _client(monkeypatch)
    client.voice_control("つけて")
    _, op1, op2 = struct.unpack(_HEADER, tcp[0][:6])
    assert (op1, op2) == (1, 9)
    assert json.loads(tcp[0][6:]) == {"text": "つけて", "success": True}


def test_dpad_key_press_release_sequence(monkeypatch):
    client, _, udp = _client(monkeypatch)
    monkeypatch.setattr("aladdin.remote.time.sleep", lambda _s: None)
    client.key("down")
    code = PROJECTOR_KEYS["down"]
    assert udp[0] == f"KEYSSTATUS:{code}+1"
    # release: every D-pad key cleared, then the pressed key once more
    assert udp[-1] == f"KEYSSTATUS:{code}+0"
    assert any(m == f"KEYSSTATUS:{PROJECTOR_KEYS['up']}+0" for m in udp)


def test_stateless_key_single_press(monkeypatch):
    client, _, udp = _client(monkeypatch)
    client.key("back")
    assert udp == [f"KEYPRESSES:{PROJECTOR_STATELESS_KEYS['back']}"]


def test_key_rejects_unknown(monkeypatch):
    client, _, _ = _client(monkeypatch)
    with pytest.raises(ValueError):
        client.key("rewind")


def test_free_memory_sends_control_command(monkeypatch):
    client, _, udp = _client(monkeypatch)
    client.free_memory()
    payload = json.loads(udp[0])
    assert payload["action"] == 20000
    assert payload["packageName"] == "cc.popIn.aladdin"
    assert payload["controlCmd"] == {"mode": 9, "type": 2, "time": 0}


def test_capture_sends_control_command(monkeypatch):
    client, _, udp = _client(monkeypatch)
    client.capture()
    assert json.loads(udp[0])["controlCmd"] == {"mode": 9, "type": 1, "time": 0}


def test_udp_ping_action(monkeypatch):
    client, _, udp = _client(monkeypatch)
    client.udp_ping()
    assert json.loads(udp[0])["action"] == 10002


def test_all_buttons_groups():
    groups = all_buttons()
    assert "on" in groups["light"]
    assert "up" in groups["key"]
    assert "back" in groups["key_stateless"]
