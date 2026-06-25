"""Client for the popIn Aladdin's proprietary remote-control protocol.

Besides the standard UPnP/DLNA renderer (see :mod:`aladdin.client`), the device
runs the MAXHUB-derived "popIn" control service used by the official app for
the ceiling light, the projector's D-pad / hardware keys, on-screen keyboard
(text) input and voice commands.

Two transports are used:

* **TCP 30913** -- length-prefixed framing ``struct '<IBB'`` (uint32 payload
  length, uint8 ``op1``, uint8 ``op2``) followed by a JSON payload. Used for the
  ceiling light, text input and voice control. A ping yields a 6-byte null reply.
* **UDP 16735** -- ASCII datagrams for the projector keys: stateful D-pad keys
  as ``KEYSSTATUS:<key>+<1|0>`` (press/release) and stateless keys as
  ``KEYPRESSES:<key>``.

There is no authentication, handshake or encryption.

The protocol constants mirror the reverse-engineering published in
https://github.com/kmaehashi/popin-aladdin-light (MIT).
"""

from __future__ import annotations

import json
import socket
import struct
import time
from urllib.parse import urlsplit

from .exceptions import AladdinConnectionError

# Ceiling-light buttons -> action code (TCP op1=1, op2=7).
CEILING_BUTTONS: dict[str, int] = {
    "switch": 31,
    "brighter": 32,
    "darker": 33,
    "cooler": 34,
    "warmer": 35,
    "full": 36,
    "night": 37,
    "on": 38,
    "off": 39,
    "eco": 40,
    "sleep": 41,
}

# Projector D-pad keys -> key code (UDP, stateful press/release).
PROJECTOR_KEYS: dict[str, int] = {
    "home": 35,
    "up": 36,
    "right": 37,
    "down": 38,
    "ok": 49,
    "left": 50,
}

# Projector hardware keys -> key code (UDP, single press).
PROJECTOR_STATELESS_KEYS: dict[str, int] = {
    "back": 48,
    "vol_up": 115,
    "vol_down": 114,
    "power": 116,
    "menu": 139,
}

_HEADER_FORMAT = "<IBB"

DEFAULT_TCP_PORT = 30913
DEFAULT_UDP_PORT = 16735


class AladdinRemoteClient:
    def __init__(
        self,
        host: str,
        *,
        tcp_port: int = DEFAULT_TCP_PORT,
        udp_port: int = DEFAULT_UDP_PORT,
        timeout: int = 10,
    ) -> None:
        # Accept either a bare host or a URL like http://172.16.1.113.
        self.host = urlsplit(host).hostname or host.rstrip("/")
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.timeout = timeout

    @staticmethod
    def _pack(op1: int, op2: int, payload_obj: object) -> bytes:
        payload = json.dumps(payload_obj).encode("utf-8")
        return struct.pack(_HEADER_FORMAT, len(payload), op1, op2) + payload

    def _send_tcp(self, data: bytes, *, expect_null_reply: bool = False) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.tcp_port))
            sock.sendall(data)
            if expect_null_reply:
                header = sock.recv(6)
                payload_len, op1, op2 = struct.unpack(_HEADER_FORMAT, header)
                if (payload_len, op1, op2) != (0, 0, 0):
                    raise AladdinConnectionError(
                        f"Unexpected TCP reply: len={payload_len} op1={op1} op2={op2}"
                    )
        except OSError as err:
            raise AladdinConnectionError(
                f"Cannot reach popIn Aladdin control port "
                f"{self.host}:{self.tcp_port}: {err}"
            ) from err
        finally:
            sock.close()

    def _send_udp(self, message: str) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(message.encode("ascii"), (self.host, self.udp_port))
        except OSError as err:
            raise AladdinConnectionError(
                f"Cannot send to popIn Aladdin control port "
                f"{self.host}:{self.udp_port}: {err}"
            ) from err
        finally:
            sock.close()

    def ping(self) -> bool:
        """TCP keep-alive ping; returns True on the expected null reply."""
        self._send_tcp(self._pack(0, 0, 1), expect_null_reply=True)
        return True

    def light(self, button: str) -> None:
        if button not in CEILING_BUTTONS:
            raise ValueError(
                f"unknown light button {button!r}; "
                f"expected one of {sorted(CEILING_BUTTONS)}"
            )
        self._send_tcp(self._pack(1, 7, {"action": CEILING_BUTTONS[button]}))

    def text(self, value: str) -> None:
        """Type into the focused on-screen input field."""
        self._send_tcp(self._pack(1, 10, {"text": value}))

    def voice_control(self, value: str) -> None:
        """Inject a voice-assistant command as text."""
        self._send_tcp(self._pack(1, 9, {"text": value, "success": True}))

    def key(self, button: str, *, duration: float = 0.1) -> None:
        """Press a projector key: D-pad (stateful) or hardware (stateless)."""
        if button in PROJECTOR_KEYS:
            self._press_dpad(button, duration=duration)
        elif button in PROJECTOR_STATELESS_KEYS:
            self._send_udp(f"KEYPRESSES:{PROJECTOR_STATELESS_KEYS[button]}")
        else:
            raise ValueError(
                f"unknown key {button!r}; expected one of "
                f"{sorted(set(PROJECTOR_KEYS) | set(PROJECTOR_STATELESS_KEYS))}"
            )

    # Maintenance commands ride a separate JSON-over-UDP "action" protocol.
    def _action(self, action_code: int, extra: dict | None = None) -> None:
        payload: dict[str, object] = {
            "version": "2.4.26",
            "appid": "1482854652",
            "packageName": "cc.popIn.aladdin",
            "msgid": "0",
            "action": action_code,
        }
        if extra:
            payload.update(extra)
        self._send_udp(json.dumps(payload))

    def _control_command(self, mode: int, type_: int, time_: int = 0) -> None:
        self._action(
            20000, {"controlCmd": {"mode": mode, "type": type_, "time": time_}}
        )

    def free_memory(self) -> None:
        """Ask the device to free background-app memory (controlCmd mode 9/2)."""
        self._control_command(9, 2, 0)

    def capture(self) -> None:
        """Trigger the device's capture command (controlCmd mode 9/1)."""
        self._control_command(9, 1, 0)

    def udp_ping(self) -> None:
        """Fire-and-forget UDP keep-alive (action 10002, no reply)."""
        self._action(10002)

    def _set_key_status(self, key: int, pressed: bool) -> None:
        self._send_udp(f"KEYSSTATUS:{key}+{'1' if pressed else '0'}")

    def _press_dpad(self, button: str, *, duration: float) -> None:
        key = PROJECTOR_KEYS[button]
        self._set_key_status(key, True)
        time.sleep(duration)
        # Release: clear every D-pad key, then the pressed key once more
        # (matches the device's expected release sequence).
        for other in PROJECTOR_KEYS.values():
            self._set_key_status(other, False)
        self._set_key_status(key, False)


def all_buttons() -> dict[str, list[str]]:
    """Expose the supported button names, grouped by category."""
    return {
        "light": list(CEILING_BUTTONS),
        "key": list(PROJECTOR_KEYS),
        "key_stateless": list(PROJECTOR_STATELESS_KEYS),
    }
