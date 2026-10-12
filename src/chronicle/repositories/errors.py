"""Errors of the repositories layer (design sections 3.3 and 5.1)."""


class ControlPlaneError(Exception):
    """The control plane answered with an error, or could not be reached."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RegistrationError(ControlPlaneError):
    """A trace could not be registered and ``registration_fail_open`` is false."""


class DeliveryError(ControlPlaneError):
    """Queued writes could not be delivered and ``fail_open`` is false (strict mode)."""
