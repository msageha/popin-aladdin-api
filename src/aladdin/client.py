"""Synchronous client for the popIn Aladdin's local UPnP/DLNA MediaRenderer.

The device ("Aladdin 2", a Platinum renderer) publishes a UPnP device
description on ``<host>:<upnp_port>/`` and exposes three services:

* ``AVTransport``     -- transport state + playback control + casting
* ``RenderingControl`` -- volume / mute
* ``ConnectionManager`` -- supported protocols

There is no authentication; anyone on the LAN can drive it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from .exceptions import AladdinConnectionError, AladdinError
from .soap import (
    DeviceDescription,
    ServiceRef,
    build_didl_metadata,
    build_envelope,
    format_duration,
    parse_device_description,
    parse_duration,
    parse_soap_response,
)

AV_TRANSPORT = "AVTransport"
RENDERING_CONTROL = "RenderingControl"
CONNECTION_MANAGER = "ConnectionManager"

PLAY_MODES = (
    "NORMAL",
    "REPEAT_ONE",
    "REPEAT_ALL",
    "SHUFFLE",
    "SHUFFLE_NOREPEAT",
)


class AladdinClient:
    def __init__(
        self,
        host: str,
        *,
        upnp_port: int = 1481,
        description_path: str = "/",
        timeout: int = 10,
    ) -> None:
        self.host = host.rstrip("/")
        self.upnp_port = upnp_port
        self.description_path = description_path
        self.timeout = timeout
        self._session = requests.Session()
        self._description: DeviceDescription | None = None

    @property
    def description_url(self) -> str:
        # host already carries the scheme (http://...); swap in the UPnP port.
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.host)
        netloc = f"{parts.hostname}:{self.upnp_port}"
        return urljoin(
            urlunsplit((parts.scheme or "http", netloc, "/", "", "")),
            self.description_path,
        )

    def _get(self, url: str) -> requests.Response:
        try:
            return self._session.get(url, timeout=self.timeout)
        except requests.exceptions.RequestException as err:
            raise AladdinConnectionError(
                f"Cannot reach popIn Aladdin at {url}: {err}"
            ) from err

    def discover(self, *, refresh: bool = False) -> DeviceDescription:
        """Fetch and cache the UPnP device description (service control URLs)."""
        if self._description is not None and not refresh:
            return self._description
        resp = self._get(self.description_url)
        try:
            desc = parse_device_description(resp.text, self.description_url)
        except Exception as err:
            raise AladdinError(
                f"Could not parse device description from {self.description_url}: "
                f"{resp.text[:200]}"
            ) from err
        self._description = desc
        return desc

    def _service(self, name: str) -> ServiceRef:
        desc = self.discover()
        svc = desc.services.get(name)
        if svc is None:
            raise AladdinError(
                f"Renderer does not expose a {name} service "
                f"(found: {sorted(desc.services)})"
            )
        return svc

    def invoke(
        self, service: str, action: str, args: dict[str, Any] | None = None
    ) -> dict[str, str]:
        """Call a SOAP ``action`` on ``service`` and return its response args."""
        svc = self._service(service)
        body = build_envelope(svc.service_type, action, args or {})
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPACTION": f'"{svc.service_type}#{action}"',
        }
        try:
            resp = self._session.post(
                svc.control_url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as err:
            raise AladdinConnectionError(
                f"Cannot reach popIn Aladdin at {svc.control_url}: {err}"
            ) from err

        try:
            return parse_soap_response(resp.text, action)
        except ValueError as err:
            raise AladdinError(
                f"{service}#{action} failed: {err}",
                fault_code=str(resp.status_code),
            ) from err

    def device_info(self) -> dict[str, Any]:
        desc = self.discover()
        return {
            "friendly_name": desc.friendly_name,
            "manufacturer": desc.manufacturer,
            "model_name": desc.model_name,
            "model_description": desc.model_description,
            "udn": desc.udn,
            "services": sorted(desc.services),
            "description_url": self.description_url,
        }

    def transport_info(self) -> dict[str, Any]:
        r = self.invoke(AV_TRANSPORT, "GetTransportInfo", {"InstanceID": 0})
        return {
            "state": r.get("CurrentTransportState"),
            "status": r.get("CurrentTransportStatus"),
            "speed": r.get("CurrentSpeed"),
        }

    def position_info(self) -> dict[str, Any]:
        r = self.invoke(AV_TRANSPORT, "GetPositionInfo", {"InstanceID": 0})
        return {
            "track": _to_int(r.get("Track")),
            "track_duration": r.get("TrackDuration"),
            "track_duration_seconds": parse_duration(r.get("TrackDuration")),
            "track_uri": r.get("TrackURI") or None,
            "track_metadata": r.get("TrackMetaData") or None,
            "rel_time": r.get("RelTime"),
            "rel_time_seconds": parse_duration(r.get("RelTime")),
            "abs_time": r.get("AbsTime"),
        }

    def media_info(self) -> dict[str, Any]:
        r = self.invoke(AV_TRANSPORT, "GetMediaInfo", {"InstanceID": 0})
        return {
            "nr_tracks": _to_int(r.get("NrTracks")),
            "media_duration": r.get("MediaDuration"),
            "current_uri": r.get("CurrentURI") or None,
            "current_uri_metadata": r.get("CurrentURIMetaData") or None,
            "play_medium": r.get("PlayMedium"),
        }

    def transport_settings(self) -> dict[str, Any]:
        r = self.invoke(AV_TRANSPORT, "GetTransportSettings", {"InstanceID": 0})
        return {
            "play_mode": r.get("PlayMode"),
            "rec_quality_mode": r.get("RecQualityMode"),
        }

    def current_transport_actions(self) -> list[str]:
        r = self.invoke(AV_TRANSPORT, "GetCurrentTransportActions", {"InstanceID": 0})
        actions = r.get("Actions", "")
        return [a.strip() for a in actions.split(",") if a.strip()]

    def get_volume(self) -> int | None:
        r = self.invoke(
            RENDERING_CONTROL, "GetVolume", {"InstanceID": 0, "Channel": "Master"}
        )
        return _to_int(r.get("CurrentVolume"))

    def get_mute(self) -> bool | None:
        r = self.invoke(
            RENDERING_CONTROL, "GetMute", {"InstanceID": 0, "Channel": "Master"}
        )
        return _to_bool(r.get("CurrentMute"))

    def status(self) -> dict[str, Any]:
        """Aggregate the commonly-wanted state in one call."""
        info = self.transport_info()
        pos = self.position_info()
        return {
            "state": info["state"],
            "status": info["status"],
            "volume": self.get_volume(),
            "mute": self.get_mute(),
            "current_uri": self.media_info()["current_uri"],
            "track_duration_seconds": pos["track_duration_seconds"],
            "position_seconds": pos["rel_time_seconds"],
        }

    def protocol_info(self) -> dict[str, list[str]]:
        r = self.invoke(CONNECTION_MANAGER, "GetProtocolInfo")
        return {
            "source": [p for p in (r.get("Source") or "").split(",") if p],
            "sink": [p for p in (r.get("Sink") or "").split(",") if p],
        }

    def play(self, speed: str = "1") -> None:
        self.invoke(AV_TRANSPORT, "Play", {"InstanceID": 0, "Speed": speed})

    def pause(self) -> None:
        self.invoke(AV_TRANSPORT, "Pause", {"InstanceID": 0})

    def stop(self) -> None:
        self.invoke(AV_TRANSPORT, "Stop", {"InstanceID": 0})

    def next(self) -> None:
        self.invoke(AV_TRANSPORT, "Next", {"InstanceID": 0})

    def previous(self) -> None:
        self.invoke(AV_TRANSPORT, "Previous", {"InstanceID": 0})

    def seek(self, seconds: float) -> None:
        self.invoke(
            AV_TRANSPORT,
            "Seek",
            {"InstanceID": 0, "Unit": "REL_TIME", "Target": format_duration(seconds)},
        )

    def set_play_mode(self, mode: str) -> None:
        if mode not in PLAY_MODES:
            raise AladdinError(
                f"unknown play mode {mode!r}; expected one of {PLAY_MODES}"
            )
        self.invoke(AV_TRANSPORT, "SetPlayMode", {"InstanceID": 0, "NewPlayMode": mode})

    def set_av_transport_uri(
        self,
        uri: str,
        *,
        metadata: str | None = None,
        title: str = "popin-aladdin-api",
        upnp_class: str = "object.item.videoItem",
        autoplay: bool = True,
    ) -> None:
        """Load ``uri`` as the current media (and start playing by default)."""
        if metadata is None:
            metadata = build_didl_metadata(uri, title=title, upnp_class=upnp_class)
        self.invoke(
            AV_TRANSPORT,
            "SetAVTransportURI",
            {"InstanceID": 0, "CurrentURI": uri, "CurrentURIMetaData": metadata},
        )
        if autoplay:
            self.play()

    def set_volume(self, volume: int) -> None:
        if not 0 <= volume <= 100:
            raise AladdinError(f"volume must be 0..100, got {volume}")
        self.invoke(
            RENDERING_CONTROL,
            "SetVolume",
            {"InstanceID": 0, "Channel": "Master", "DesiredVolume": volume},
        )

    def set_mute(self, mute: bool) -> None:
        self.invoke(
            RENDERING_CONTROL,
            "SetMute",
            {"InstanceID": 0, "Channel": "Master", "DesiredMute": "1" if mute else "0"},
        )


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)
