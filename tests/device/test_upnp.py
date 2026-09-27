from xml.etree import ElementTree as ET

import pytest

from popin_aladdin_api.device.errors import AladdinError, AladdinSoapError
from popin_aladdin_api.device.upnp import (
    build_didl_metadata,
    build_envelope,
    format_duration,
    parse_device_description,
    parse_duration,
    parse_response,
)

# 実機 "Aladdin 2" (port 1481) の device description を短くしたもの。
DESCRIPTION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<root configId="258119" xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Aladdin 2</friendlyName>
    <manufacturer>Plutinosoft LLC</manufacturer>
    <modelName>AV Renderer Device</modelName>
    <UDN>uuid:54F15F164D4F-dmr</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <SCPDURL>/AVTransport/54F15F164D4F-dmr/scpd.xml</SCPDURL>
        <controlURL>/AVTransport/54F15F164D4F-dmr/control.xml</controlURL>
        <eventSubURL>/AVTransport/54F15F164D4F-dmr/event.xml</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
        <SCPDURL>/RenderingControl/54F15F164D4F-dmr/scpd.xml</SCPDURL>
        <controlURL>/RenderingControl/54F15F164D4F-dmr/control.xml</controlURL>
        <eventSubURL>/RenderingControl/54F15F164D4F-dmr/event.xml</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>"""

GET_VOLUME_RESPONSE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    "<s:Body>"
    '<u:GetVolumeResponse xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
    "<CurrentVolume>35</CurrentVolume>"
    "</u:GetVolumeResponse></s:Body></s:Envelope>"
)

FAULT_RESPONSE = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    "<s:Body><s:Fault>"
    "<faultcode>s:Client</faultcode>"
    "<faultstring>UPnPError</faultstring>"
    '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
    "<errorCode>402</errorCode>"
    "<errorDescription>Invalid Args</errorDescription>"
    "</UPnPError></detail>"
    "</s:Fault></s:Body></s:Envelope>"
)


def test_build_envelope_escapes_and_wraps():
    body = build_envelope(
        "urn:schemas-upnp-org:service:AVTransport:1",
        "SetAVTransportURI",
        {"InstanceID": 0, "CurrentURI": "http://h/a&b.mp4", "Empty": None},
    )
    assert body.startswith("<?xml")
    assert 'xmlns:u="urn:schemas-upnp-org:service:AVTransport:1"' in body
    assert "<InstanceID>0</InstanceID>" in body
    assert "<CurrentURI>http://h/a&amp;b.mp4</CurrentURI>" in body
    assert "<Empty></Empty>" in body


def test_parse_response_extracts_args():
    assert parse_response(GET_VOLUME_RESPONSE, "GetVolume") == {"CurrentVolume": "35"}


def test_parse_response_raises_structured_fault():
    with pytest.raises(AladdinSoapError) as exc:
        parse_response(FAULT_RESPONSE, "SetVolume")
    assert exc.value.fault_code == "s:Client"
    assert exc.value.upnp_error_code == 402
    assert "Invalid Args" in str(exc.value)


@pytest.mark.parametrize("xml", ["not xml", "<other/>"])
def test_parse_response_rejects_non_soap(xml):
    with pytest.raises(AladdinError):
        parse_response(xml, "GetVolume")


def test_parse_device_description_resolves_urls():
    desc = parse_device_description(DESCRIPTION_XML, "http://172.16.1.113:1481/")
    assert desc.friendly_name == "Aladdin 2"
    assert desc.manufacturer == "Plutinosoft LLC"
    assert desc.model_description is None
    assert desc.udn == "uuid:54F15F164D4F-dmr"
    assert set(desc.services) == {"AVTransport", "RenderingControl"}
    av = desc.services["AVTransport"]
    assert av.service_type == "urn:schemas-upnp-org:service:AVTransport:1"
    assert (
        av.control_url
        == "http://172.16.1.113:1481/AVTransport/54F15F164D4F-dmr/control.xml"
    )


def test_parse_device_description_requires_device_element():
    with pytest.raises(AladdinError):
        parse_device_description("<root/>", "http://h/")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:00:00", 0.0),
        ("0:01:30", 90.0),
        ("1:00:00", 3600.0),
        ("00:03:32", 212.0),
        ("0:00:01.500", 1.5),
        ("NOT_IMPLEMENTED", None),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0:00:00"), (90, "0:01:30"), (3600, "1:00:00"), (212.6, "0:03:33")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_build_didl_metadata_is_valid_xml():
    didl = build_didl_metadata(
        "http://h/v.mp4?a=1&b=2", title="My <Video>", upnp_class="object.item.videoItem"
    )
    assert "My &lt;Video&gt;" in didl
    assert "http://h/v.mp4?a=1&amp;b=2" in didl
    ET.fromstring(didl)
