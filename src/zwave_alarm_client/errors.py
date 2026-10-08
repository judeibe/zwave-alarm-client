"""Exceptions raised by the Z-Wave Alarm client, one per documented failure mode."""

from __future__ import annotations


class ZwaveAlarmError(Exception):
    """Base class for every error this package raises."""


class CannotConnect(ZwaveAlarmError):
    """The service could not be reached, timed out, or answered with an unexpected 5xx."""


class ServiceUnavailable(CannotConnect):
    """The service answered `503`: it is up but not ready (e.g. the Z-Wave driver is still starting)."""

    def __init__(self, message: str = "", code: str = "") -> None:
        super().__init__(message)
        self.code = code


class InvalidAuth(ZwaveAlarmError):
    """The service rejected the token, session or code (401)."""


class Forbidden(ZwaveAlarmError):
    """The caller is authenticated but its role may not perform this action (403, FR-010a)."""


class NotFound(ZwaveAlarmError):
    """The addressed zone, user or link does not exist (404)."""


class AccountLocked(ZwaveAlarmError):
    """The caller's account is locked out from repeated wrong codes (423, FR-016)."""


class Conflict(ZwaveAlarmError):
    """The request conflicts with current state (409), e.g. a sensor node already assigned to a zone."""


class ZoneNotEmpty(Conflict):
    """The zone still has sensors (409 `zone_not_empty`); retry with `force=True` to unassign them."""


class ZoneInUse(Conflict):
    """A guest's `guestZoneId` still references the zone (409 `zone_in_use`); `force=True` does not override it."""


class CodeInUse(Conflict):
    """Another user already has this code (409 `code_in_use`); codes must be unique because login identifies by code."""


class CommandRejected(Conflict):
    """A conflicting concurrent arm/disarm won the race (409, FR-014)."""


class BadRequest(ZwaveAlarmError):
    """The request failed schema validation (400); `str(err)` names the offending field."""


class TooManyRequests(ZwaveAlarmError):
    """Login is rate-limited per client IP (429); `retry_after` is the `Retry-After` header in seconds, if sent."""

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
