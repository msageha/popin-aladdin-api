"""popIn Aladdin の UPnP/DLNA MediaRenderer ("Aladdin 2"、Platinum 実装) を叩く async クライアント。

device description (``http://<host>:1481/``) から各 service の controlURL を解決し、
SOAP でアクションを呼ぶ。UDN が機体ごとに異なるため controlURL は決め打ちしない。
認証は無い。並行呼び出しは直列化しないので、呼び出し側で制御する。
"""

from collections.abc import Mapping
from typing import Any, Self
from urllib.parse import urljoin

import httpx

from .errors import AladdinConnectionError, AladdinError
from .models import (
    DeviceDescription,
    DeviceInfo,
    MediaInfo,
    PlayMode,
    PositionInfo,
    ProtocolInfo,
    RendererStatus,
    TransportInfo,
)
from .upnp import (
    build_didl_metadata,
    build_envelope,
    format_duration,
    parse_device_description,
    parse_duration,
    parse_response,
)

UPNP_PORT = 1481
DEFAULT_CAST_TITLE = "popin-aladdin-api"
DEFAULT_UPNP_CLASS = "object.item.videoItem"

AV_TRANSPORT = "AVTransport"
RENDERING_CONTROL = "RenderingControl"
CONNECTION_MANAGER = "ConnectionManager"

_INSTANCE = {"InstanceID": 0}
_MASTER = {"InstanceID": 0, "Channel": "Master"}


class RendererClient:
    def __init__(
        self,
        host: str,
        *,
        port: int = UPNP_PORT,
        description_path: str = "/",
        timeout: float = 10.0,
    ) -> None:
        self.description_url = urljoin(f"http://{host}:{port}/", description_path)
        self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._description: DeviceDescription | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def discover(self) -> DeviceDescription:
        """device description を取得する。UDN と controlURL は機体固有だが不変なのでプロセス生存中はキャッシュする。"""
        if self._description is None:
            response = await self._request("GET", self.description_url)
            if response.is_error:
                raise AladdinError(
                    f"device description at {self.description_url} returned "
                    f"HTTP {response.status_code}"
                )
            self._description = parse_device_description(
                response.text, self.description_url
            )
        return self._description

    async def invoke(
        self, service: str, action: str, args: Mapping[str, Any]
    ) -> dict[str, str]:
        """``service`` の SOAP ``action`` を呼び、出力引数を返す。"""
        description = await self.discover()
        target = description.services.get(service)
        if target is None:
            raise AladdinError(
                f"renderer has no {service} service "
                f"(found: {sorted(description.services)})"
            )
        response = await self._request(
            "POST",
            target.control_url,
            content=build_envelope(target.service_type, action, args),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"{target.service_type}#{action}"',
            },
        )
        return parse_response(response.text, action)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.InvalidURL as err:
            raise AladdinError(f"invalid URL in device description: {url!r}") from err
        except httpx.HTTPError as err:
            raise AladdinConnectionError(
                f"cannot reach popIn Aladdin at {url}: {err}"
            ) from err

    async def device_info(self) -> DeviceInfo:
        description = await self.discover()
        return DeviceInfo(
            **description.model_dump(exclude={"services"}),
            services=sorted(description.services),
            description_url=self.description_url,
        )

    async def transport_info(self) -> TransportInfo:
        result = await self.invoke(AV_TRANSPORT, "GetTransportInfo", _INSTANCE)
        return TransportInfo(
            state=result.get("CurrentTransportState"),
            status=result.get("CurrentTransportStatus"),
            speed=result.get("CurrentSpeed"),
        )

    async def position_info(self) -> PositionInfo:
        result = await self.invoke(AV_TRANSPORT, "GetPositionInfo", _INSTANCE)
        return PositionInfo(
            track=_int(result, "Track"),
            track_duration=result.get("TrackDuration"),
            track_duration_seconds=parse_duration(result.get("TrackDuration")),
            track_uri=result.get("TrackURI") or None,
            track_metadata=result.get("TrackMetaData") or None,
            rel_time=result.get("RelTime"),
            rel_time_seconds=parse_duration(result.get("RelTime")),
            abs_time=result.get("AbsTime"),
        )

    async def media_info(self) -> MediaInfo:
        result = await self.invoke(AV_TRANSPORT, "GetMediaInfo", _INSTANCE)
        return MediaInfo(
            nr_tracks=_int(result, "NrTracks"),
            media_duration=result.get("MediaDuration"),
            current_uri=result.get("CurrentURI") or None,
            current_uri_metadata=result.get("CurrentURIMetaData") or None,
            play_medium=result.get("PlayMedium"),
        )

    async def protocol_info(self) -> ProtocolInfo:
        result = await self.invoke(CONNECTION_MANAGER, "GetProtocolInfo", {})
        return ProtocolInfo(
            source=_csv(result.get("Source")), sink=_csv(result.get("Sink"))
        )

    async def get_volume(self) -> int:
        result = await self.invoke(RENDERING_CONTROL, "GetVolume", _MASTER)
        volume = _int(result, "CurrentVolume")
        if not 0 <= volume <= 100:
            raise AladdinError(f"CurrentVolume is out of range 0..100: {volume}")
        return volume

    async def get_mute(self) -> bool:
        result = await self.invoke(RENDERING_CONTROL, "GetMute", _MASTER)
        return _bool(result, "CurrentMute")

    async def status(self) -> RendererStatus:
        transport = await self.transport_info()
        position = await self.position_info()
        media = await self.media_info()
        return RendererStatus(
            state=transport.state,
            status=transport.status,
            volume=await self.get_volume(),
            mute=await self.get_mute(),
            current_uri=media.current_uri,
            track_duration_seconds=position.track_duration_seconds,
            position_seconds=position.rel_time_seconds,
        )

    async def play(self, speed: str = "1") -> None:
        await self.invoke(AV_TRANSPORT, "Play", {**_INSTANCE, "Speed": speed})

    async def pause(self) -> None:
        await self.invoke(AV_TRANSPORT, "Pause", _INSTANCE)

    async def stop(self) -> None:
        await self.invoke(AV_TRANSPORT, "Stop", _INSTANCE)

    async def next(self) -> None:
        await self.invoke(AV_TRANSPORT, "Next", _INSTANCE)

    async def previous(self) -> None:
        await self.invoke(AV_TRANSPORT, "Previous", _INSTANCE)

    async def seek(self, seconds: float) -> None:
        await self.invoke(
            AV_TRANSPORT,
            "Seek",
            {**_INSTANCE, "Unit": "REL_TIME", "Target": format_duration(seconds)},
        )

    async def set_play_mode(self, mode: PlayMode) -> None:
        await self.invoke(
            AV_TRANSPORT, "SetPlayMode", {**_INSTANCE, "NewPlayMode": mode}
        )

    async def cast(
        self,
        uri: str,
        *,
        title: str = DEFAULT_CAST_TITLE,
        upnp_class: str = DEFAULT_UPNP_CLASS,
        metadata: str | None = None,
        autoplay: bool = True,
    ) -> None:
        """``uri`` を現在のメディアとして読み込み、``autoplay`` なら続けて再生する。"""
        if metadata is None:
            metadata = build_didl_metadata(uri, title=title, upnp_class=upnp_class)
        await self.invoke(
            AV_TRANSPORT,
            "SetAVTransportURI",
            {**_INSTANCE, "CurrentURI": uri, "CurrentURIMetaData": metadata},
        )
        if autoplay:
            await self.play()

    async def set_volume(self, volume: int) -> None:
        await self.invoke(
            RENDERING_CONTROL, "SetVolume", {**_MASTER, "DesiredVolume": volume}
        )

    async def set_mute(self, mute: bool) -> None:
        await self.invoke(
            RENDERING_CONTROL, "SetMute", {**_MASTER, "DesiredMute": int(mute)}
        )


def _int(result: Mapping[str, str], name: str) -> int:
    try:
        return int(result[name])
    except (KeyError, ValueError) as err:
        raise AladdinError(
            f"{name} is missing or not an integer: {result.get(name)!r}"
        ) from err


def _bool(result: Mapping[str, str], name: str) -> bool:
    value = result.get(name, "").strip().lower()
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    raise AladdinError(f"{name} is missing or not a boolean: {value!r}")


def _csv(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item]
