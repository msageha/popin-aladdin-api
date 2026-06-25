class AladdinError(Exception):
    """A UPnP/SOAP-level failure reported by the renderer."""

    def __init__(
        self,
        message: str,
        *,
        fault_code: str | None = None,
        upnp_error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.fault_code = fault_code
        self.upnp_error_code = upnp_error_code


class AladdinConnectionError(AladdinError):
    """The renderer could not be reached over the network."""
