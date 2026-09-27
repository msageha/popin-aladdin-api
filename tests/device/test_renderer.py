from xml.etree import ElementTree as ET

import httpx
import pytest

from popin_aladdin_api.device.errors import (
    AladdinConnectionError,
    AladdinError,
    AladdinSoapError,
)
from popin_aladdin_api.device.models import PlayMode
from popin_aladdin_api.device.renderer import RendererClient

from .test_upnp import DESCRIPTION_XML, FAULT_RESPONSE

pytestmark = pytest.mark.anyio


class FakeRenderer:
    """device description と SOAP 応答を返し、受け取った SOAP 呼び出しを記録する。"""

    def __init__(self) -> None:
        self.responses: dict[str, dict[str, str]] = {}
        self.fault_actions: set[str] = set()
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=DESCRIPTION_XML)
        service_type, action = request.headers["SOAPACTION"].strip('"').split("#")
        body = ET.fromstring(request.content).find("{*}Body")
        assert body is not None
        call = body.find(f"{{*}}{action}")
        assert call is not None
        args = {arg.tag: arg.text or "" for arg in call}
        self.calls.append((request.url.path.split("/")[1], action, args))
        if action in self.fault_actions:
            return httpx.Response(500, text=FAULT_RESPONSE)
        out = "".join(
            f"<{k}>{v}</{k}>" for k, v in self.responses.get(action, {}).items()
        )
        return httpx.Response(
            200,
            text=(
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<s:Body><u:{action}Response xmlns:u="{service_type}">{out}'
                f"</u:{action}Response></s:Body></s:Envelope>"
            ),
        )


@pytest.fixture
def fake() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture
async def client(fake: FakeRenderer):
    renderer = RendererClient("172.16.1.113")
    renderer._http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    async with renderer:
        yield renderer


def test_description_url_uses_port_and_path():
    assert RendererClient("172.16.1.113").description_url == "http://172.16.1.113:1481/"
    client = RendererClient("h", port=8080, description_path="desc.xml")
    assert client.description_url == "http://h:8080/desc.xml"


async def test_device_info_lists_services(client: RendererClient):
    info = await client.device_info()
    assert info.friendly_name == "Aladdin 2"
    assert info.services == ["AVTransport", "RenderingControl"]
    assert info.description_url == "http://172.16.1.113:1481/"


async def test_transport_info_maps_response(client: RendererClient, fake: FakeRenderer):
    fake.responses["GetTransportInfo"] = {
        "CurrentTransportState": "PLAYING",
        "CurrentTransportStatus": "OK",
        "CurrentSpeed": "1",
    }
    info = await client.transport_info()
    assert (info.state, info.status, info.speed) == ("PLAYING", "OK", "1")
    assert fake.calls == [
        ("AVTransport", "GetTransportInfo", {"InstanceID": "0"}),
    ]


async def test_position_info_decodes_durations(
    client: RendererClient, fake: FakeRenderer
):
    fake.responses["GetPositionInfo"] = {
        "Track": "1",
        "TrackDuration": "0:03:32",
        "TrackURI": "http://h/v.mp4",
        "TrackMetaData": "",
        "RelTime": "0:00:30",
        "AbsTime": "NOT_IMPLEMENTED",
    }
    pos = await client.position_info()
    assert pos.track == 1
    assert pos.track_duration_seconds == 212.0
    assert pos.rel_time_seconds == 30.0
    assert pos.track_uri == "http://h/v.mp4"
    assert pos.track_metadata is None


async def test_volume_and_mute(client: RendererClient, fake: FakeRenderer):
    fake.responses["GetVolume"] = {"CurrentVolume": "35"}
    fake.responses["GetMute"] = {"CurrentMute": "1"}
    assert await client.get_volume() == 35
    assert await client.get_mute() is True
    fake.responses["GetMute"] = {"CurrentMute": "0"}
    assert await client.get_mute() is False


async def test_malformed_numeric_response_is_device_error(
    client: RendererClient, fake: FakeRenderer
):
    fake.responses["GetVolume"] = {"CurrentVolume": "loud"}
    with pytest.raises(AladdinError):
        await client.get_volume()


async def test_set_volume_and_mute_build_args(
    client: RendererClient, fake: FakeRenderer
):
    await client.set_volume(40)
    await client.set_mute(True)
    assert fake.calls == [
        (
            "RenderingControl",
            "SetVolume",
            {"InstanceID": "0", "Channel": "Master", "DesiredVolume": "40"},
        ),
        (
            "RenderingControl",
            "SetMute",
            {"InstanceID": "0", "Channel": "Master", "DesiredMute": "1"},
        ),
    ]


async def test_seek_and_play_mode(client: RendererClient, fake: FakeRenderer):
    await client.seek(90)
    await client.set_play_mode(PlayMode.REPEAT_ALL)
    assert fake.calls[0][2] == {
        "InstanceID": "0",
        "Unit": "REL_TIME",
        "Target": "0:01:30",
    }
    assert fake.calls[1][2] == {"InstanceID": "0", "NewPlayMode": "REPEAT_ALL"}


async def test_cast_generates_metadata_then_plays(
    client: RendererClient, fake: FakeRenderer
):
    await client.cast("http://h/v.mp4")
    assert [call[1] for call in fake.calls] == ["SetAVTransportURI", "Play"]
    args = fake.calls[0][2]
    assert args["CurrentURI"] == "http://h/v.mp4"
    assert "DIDL-Lite" in args["CurrentURIMetaData"]


async def test_cast_without_autoplay(client: RendererClient, fake: FakeRenderer):
    await client.cast("http://h/v.mp4", metadata="<DIDL-Lite/>", autoplay=False)
    assert [call[1] for call in fake.calls] == ["SetAVTransportURI"]
    assert fake.calls[0][2]["CurrentURIMetaData"] == "<DIDL-Lite/>"


async def test_missing_service_raises(client: RendererClient):
    with pytest.raises(AladdinError, match="ConnectionManager"):
        await client.protocol_info()


async def test_soap_fault_is_raised(client: RendererClient, fake: FakeRenderer):
    fake.fault_actions.add("SetVolume")
    with pytest.raises(AladdinSoapError) as exc:
        await client.set_volume(20)
    assert exc.value.upnp_error_code == 402


async def test_unreachable_device_is_connection_error():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    renderer = RendererClient("172.16.1.113")
    renderer._http = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    async with renderer:
        with pytest.raises(AladdinConnectionError):
            await renderer.discover()
