"""Pure helpers for the UPnP/DLNA MediaRenderer protocol the popIn Aladdin
speaks: building SOAP envelopes, parsing SOAP responses and the UPnP device
description, and converting the ``H:MM:SS`` time format the AVTransport uses.

Nothing here touches the network; :mod:`aladdin.client` wires these to HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP_ENCODING = "http://schemas.xmlsoap.org/soap/encoding/"
DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"


def _local(tag: str) -> str:
    """Strip an XML namespace (``{ns}tag`` -> ``tag``)."""
    return tag.rsplit("}", 1)[-1]


def build_envelope(service_type: str, action: str, args: Mapping[str, Any]) -> str:
    """Serialize a UPnP control SOAP request.

    Argument values are XML-escaped, so URIs and DIDL metadata can be passed
    verbatim.
    """
    arg_xml = "".join(
        f"<{name}>{escape('' if value is None else str(value))}</{name}>"
        for name, value in args.items()
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENVELOPE_NS}" '
        f's:encodingStyle="{SOAP_ENCODING}">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{service_type}">{arg_xml}</u:{action}>'
        "</s:Body></s:Envelope>"
    )


def parse_soap_response(xml: str, action: str) -> dict[str, str]:
    """Return the ``<u:{action}Response>`` arguments as a flat ``{name: text}``.

    Raises :class:`ValueError` on a SOAP fault so the caller can translate it
    into an :class:`~aladdin.exceptions.AladdinError`.
    """
    root = ET.fromstring(xml)
    body = _find_local(root, "Body")
    if body is None:
        raise ValueError(f"SOAP response for {action} has no Body: {xml[:200]}")

    fault = _find_local(body, "Fault")
    if fault is not None:
        raise ValueError(_format_fault(fault))

    out: dict[str, str] = {}
    for response in list(body):
        for arg in list(response):
            out[_local(arg.tag)] = arg.text or ""
    return out


def _format_fault(fault: ET.Element) -> str:
    code = _text(_find_local(fault, "faultcode"))
    string = _text(_find_local(fault, "faultstring"))
    detail = _find_local(fault, "detail")
    upnp_code = upnp_desc = None
    if detail is not None:
        err = _find_local(detail, "UPnPError")
        if err is not None:
            upnp_code = _text(_find_local(err, "errorCode"))
            upnp_desc = _text(_find_local(err, "errorDescription"))
    parts = [p for p in (code, string) if p]
    if upnp_code or upnp_desc:
        parts.append(f"UPnPError {upnp_code}: {upnp_desc}")
    return "SOAP fault: " + " / ".join(parts)


def _find_local(elem: ET.Element | None, name: str) -> ET.Element | None:
    if elem is None:
        return None
    for child in elem.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(elem: ET.Element | None) -> str | None:
    return elem.text if elem is not None else None


class ServiceRef:
    """A single ``<service>`` from the device description, with URLs already
    resolved to absolute form against the description location."""

    def __init__(
        self,
        service_type: str,
        control_url: str,
        scpd_url: str,
        event_url: str,
    ) -> None:
        self.service_type = service_type
        self.control_url = control_url
        self.scpd_url = scpd_url
        self.event_url = event_url

    @property
    def name(self) -> str:
        """Short name, e.g. ``AVTransport`` from
        ``urn:schemas-upnp-org:service:AVTransport:1``."""
        parts = self.service_type.split(":")
        return parts[-2] if len(parts) >= 2 else self.service_type


class DeviceDescription:
    """Parsed UPnP device description: friendly metadata plus a service map
    keyed by short service name (``AVTransport`` / ``RenderingControl`` / ...)."""

    def __init__(
        self,
        friendly_name: str | None,
        manufacturer: str | None,
        model_name: str | None,
        model_description: str | None,
        udn: str | None,
        services: dict[str, ServiceRef],
    ) -> None:
        self.friendly_name = friendly_name
        self.manufacturer = manufacturer
        self.model_name = model_name
        self.model_description = model_description
        self.udn = udn
        self.services = services


def parse_device_description(xml: str, base_url: str) -> DeviceDescription:
    """Parse the root device description XML fetched from ``base_url``.

    Relative ``controlURL`` / ``SCPDURL`` / ``eventSubURL`` values are resolved
    against ``base_url`` (the description's own location).
    """
    from urllib.parse import urljoin

    root = ET.fromstring(xml)
    device = _find_local(root, "device")
    if device is None:
        raise ValueError("device description has no <device> element")

    services: dict[str, ServiceRef] = {}
    service_list = _find_local(device, "serviceList")
    if service_list is not None:
        for svc in service_list:
            if _local(svc.tag) != "service":
                continue
            svc_type = _child_text(svc, "serviceType")
            if not svc_type:
                continue
            ref = ServiceRef(
                service_type=svc_type,
                control_url=urljoin(base_url, _child_text(svc, "controlURL") or ""),
                scpd_url=urljoin(base_url, _child_text(svc, "SCPDURL") or ""),
                event_url=urljoin(base_url, _child_text(svc, "eventSubURL") or ""),
            )
            services[ref.name] = ref

    return DeviceDescription(
        friendly_name=_child_text(device, "friendlyName"),
        manufacturer=_child_text(device, "manufacturer"),
        model_name=_child_text(device, "modelName"),
        model_description=_child_text(device, "modelDescription"),
        udn=_child_text(device, "UDN"),
        services=services,
    )


def _child_text(parent: ET.Element, name: str) -> str | None:
    for child in parent:
        if _local(child.tag) == name:
            return child.text
    return None


def parse_duration(value: str | None) -> float | None:
    """Parse ``H:MM:SS(.frac)`` (UPnP time) into seconds, or ``None``."""
    if not value or value in ("NOT_IMPLEMENTED", ""):
        return None
    parts = value.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    seconds = 0.0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


def format_duration(seconds: float) -> str:
    """Format seconds as ``H:MM:SS`` for AVTransport ``Seek``."""
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def build_didl_metadata(
    uri: str,
    title: str = "popin-aladdin-api",
    upnp_class: str = "object.item.videoItem",
) -> str:
    """Build a minimal DIDL-Lite metadata document for ``SetAVTransportURI``.

    Some renderers ignore an empty metadata argument; supplying a valid DIDL
    item makes casting reliable across players.
    """
    return (
        f'<DIDL-Lite xmlns="{DIDL_NS}" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"<upnp:class>{escape(upnp_class)}</upnp:class>"
        f"<res protocolInfo={quoteattr('http-get:*:*:*')}>{escape(uri)}</res>"
        "</item></DIDL-Lite>"
    )
