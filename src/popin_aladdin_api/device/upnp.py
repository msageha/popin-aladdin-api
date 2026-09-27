"""UPnP/DLNA MediaRenderer プロトコルの純粋関数。ネットワークには触れない。

SOAP envelope の組み立て、SOAP 応答と device description の解析、AVTransport の
``H:MM:SS`` 形式の変換、キャスト用 DIDL-Lite の生成を担う。
"""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .errors import AladdinError, AladdinSoapError
from .models import DeviceDescription, UpnpService

SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_ENCODING_NS = "http://schemas.xmlsoap.org/soap/encoding/"
DIDL_LITE_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"


def build_envelope(service_type: str, action: str, args: Mapping[str, Any]) -> str:
    """UPnP control の SOAP リクエストを組み立てる。引数値は XML エスケープする。"""
    arguments = "".join(
        f"<{name}>{escape('' if value is None else str(value))}</{name}>"
        for name, value in args.items()
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENVELOPE_NS}" s:encodingStyle="{SOAP_ENCODING_NS}">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">{arguments}</u:{action}></s:Body>'
        "</s:Envelope>"
    )


def parse_response(xml: str, action: str) -> dict[str, str]:
    """``<u:{action}Response>`` の出力引数を ``{名前: 文字列}`` で返す。

    Raises:
        AladdinSoapError: 応答が SOAP fault のとき。
        AladdinError: 応答が SOAP envelope として解釈できないとき。
    """
    body = _parse_xml(xml, action).find("{*}Body")
    if body is None:
        raise AladdinError(f"{action}: SOAP response has no Body element")
    fault = body.find("{*}Fault")
    if fault is not None:
        raise _soap_fault(action, fault)
    return {
        argument.tag.rpartition("}")[2]: argument.text or ""
        for response in body
        for argument in response
    }


def _soap_fault(action: str, fault: ET.Element) -> AladdinSoapError:
    fault_code = fault.findtext("{*}faultcode")
    fault_string = fault.findtext("{*}faultstring")
    error_code = fault.findtext(".//{*}errorCode")
    error_description = fault.findtext(".//{*}errorDescription")
    parts = [part for part in (fault_code, fault_string) if part]
    if error_code or error_description:
        parts.append(f"UPnPError {error_code}: {error_description}")
    try:
        upnp_error_code = int(error_code) if error_code else None
    except ValueError:
        upnp_error_code = None
    return AladdinSoapError(
        f"{action} failed: {' / '.join(parts)}",
        fault_code=fault_code,
        upnp_error_code=upnp_error_code,
    )


def parse_device_description(xml: str, base_url: str) -> DeviceDescription:
    """device description XML を解析する。相対 controlURL は base_url で絶対化する。"""
    device = _parse_xml(xml, "device description").find("{*}device")
    if device is None:
        raise AladdinError("device description has no <device> element")
    services: dict[str, UpnpService] = {}
    for service in device.iterfind("{*}serviceList/{*}service"):
        service_type = service.findtext("{*}serviceType")
        control_url = service.findtext("{*}controlURL") or ""
        if not service_type:
            continue
        try:
            absolute_control_url = urljoin(base_url, control_url)
        except ValueError as err:
            raise AladdinError(
                f"device description has an invalid controlURL: {control_url!r}"
            ) from err
        services[_service_name(service_type)] = UpnpService(
            service_type=service_type, control_url=absolute_control_url
        )
    return DeviceDescription(
        friendly_name=device.findtext("{*}friendlyName") or None,
        manufacturer=device.findtext("{*}manufacturer") or None,
        model_name=device.findtext("{*}modelName") or None,
        model_description=device.findtext("{*}modelDescription") or None,
        udn=device.findtext("{*}UDN") or None,
        services=services,
    )


def _service_name(service_type: str) -> str:
    """``urn:schemas-upnp-org:service:AVTransport:1`` → ``AVTransport``。"""
    parts = service_type.split(":")
    return parts[-2] if len(parts) >= 2 else service_type


def _parse_xml(xml: str, subject: str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as err:
        raise AladdinError(f"{subject}: malformed XML: {xml[:200]!r}") from err


def parse_duration(value: str | None) -> float | None:
    """AVTransport の ``H:MM:SS(.fff)`` を秒にする。空や NOT_IMPLEMENTED は None。"""
    if not value or value == "NOT_IMPLEMENTED":
        return None
    try:
        parts = [float(part) for part in value.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def format_duration(seconds: float) -> str:
    """秒を Seek 用の ``H:MM:SS`` にする。"""
    hours, rest = divmod(round(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def build_didl_metadata(uri: str, *, title: str, upnp_class: str) -> str:
    """SetAVTransportURI 用の最小 DIDL-Lite。空のメタデータを無視する renderer があるため必ず付ける。"""
    return (
        f'<DIDL-Lite xmlns="{DIDL_LITE_NS}" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"<upnp:class>{escape(upnp_class)}</upnp:class>"
        f'<res protocolInfo="http-get:*:*:*">{escape(uri)}</res>'
        "</item></DIDL-Lite>"
    )
