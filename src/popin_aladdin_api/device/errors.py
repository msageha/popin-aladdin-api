class AladdinError(Exception):
    """デバイス制御に失敗したときの基底例外。

    fault_code / upnp_error_code は SOAP fault のときだけ埋まるが、API の 502 応答が
    常に同じ形になるよう基底に持たせる。
    """

    fault_code: str | None = None
    upnp_error_code: int | None = None


class AladdinConnectionError(AladdinError):
    """デバイスにネットワーク的に到達できない (接続拒否・タイムアウト・送信失敗)。"""


class AladdinSoapError(AladdinError):
    """デバイスが SOAP fault を返した。"""

    def __init__(
        self, message: str, *, fault_code: str | None, upnp_error_code: int | None
    ) -> None:
        super().__init__(message)
        self.fault_code = fault_code
        self.upnp_error_code = upnp_error_code
