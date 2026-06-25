import pytest

from aladdin.soap import (
    build_didl_metadata,
    build_envelope,
    format_duration,
    parse_device_description,
    parse_duration,
    parse_soap_response,
)

pytestmark = pytest.mark.unit


# A trimmed copy of the real "Aladdin 2" device description (port 1481).
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
        {"InstanceID": 0, "CurrentURI": "http://h/a&b.mp4"},
    )
    assert "<u:SetAVTransportURI " in body
    assert 'xmlns:u="urn:schemas-upnp-org:service:AVTransport:1"' in body
    assert "<CurrentURI>http://h/a&amp;b.mp4</CurrentURI>" in body
    assert body.startswith("<?xml")


def test_parse_soap_response_extracts_args():
    out = parse_soap_response(GET_VOLUME_RESPONSE, "GetVolume")
    assert out == {"CurrentVolume": "35"}


def test_parse_soap_response_raises_on_fault():
    with pytest.raises(ValueError) as exc:
        parse_soap_response(FAULT_RESPONSE, "SetVolume")
    assert "402" in str(exc.value)
    assert "Invalid Args" in str(exc.value)


def test_parse_device_description_resolves_urls():
    base = "http://172.16.1.113:1481/"
    desc = parse_device_description(DESCRIPTION_XML, base)
    assert desc.friendly_name == "Aladdin 2"
    assert desc.manufacturer == "Plutinosoft LLC"
    assert desc.udn == "uuid:54F15F164D4F-dmr"
    assert set(desc.services) == {"AVTransport", "RenderingControl"}

    av = desc.services["AVTransport"]
    assert av.service_type == "urn:schemas-upnp-org:service:AVTransport:1"
    assert (
        av.control_url
        == "http://172.16.1.113:1481/AVTransport/54F15F164D4F-dmr/control.xml"
    )
    assert av.name == "AVTransport"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("00:00:00", 0.0),
        ("0:01:30", 90.0),
        ("1:00:00", 3600.0),
        ("00:03:32", 212.0),
        ("NOT_IMPLEMENTED", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0:00:00"), (90, "0:01:30"), (3600, "1:00:00"), (212.6, "0:03:33")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_build_didl_metadata_is_valid_xml():
    didl = build_didl_metadata("http://h/v.mp4?a=1&b=2", title="My <Video>")
    assert "DIDL-Lite" in didl
    assert "My &lt;Video&gt;" in didl
    assert "http://h/v.mp4?a=1&amp;b=2" in didl
    # parses without error
    from xml.etree import ElementTree as ET

    ET.fromstring(didl)
