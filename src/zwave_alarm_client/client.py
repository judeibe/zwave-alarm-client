"""REST client for the Z-Wave Alarm service (contracts/rest-api.md).

Every call takes `(session, host, port, token, ...)`. Authentication is
optional: pass `token=None` (the default posture) and no `Authorization`
header is sent, so the client needs only host and port. A non-empty `token` is
still sent as a bearer token for deployments that enforce one. A cookie session
(see `async_login`, which needs a `ClientSession` that keeps cookies) also
works with `token=None`. `secure=True` switches to `https://` for deployments
behind a TLS-terminating proxy.

Factored out of the Home Assistant integration so the request/response
handling -- the part worth testing -- doesn't need a running Home Assistant.
"""

from __future__ import annotations

from typing import Any, Literal

import aiohttp

from .errors import (
    AccountLocked,
    BadRequest,
    CannotConnect,
    CodeInUse,
    CodeLimit,
    CommandRejected,
    Conflict,
    Forbidden,
    InvalidAuth,
    LockNotSecure,
    LockUnavailable,
    NeedsBypass,
    NotFound,
    ScheduleConflict,
    ScheduleKindUnsupported,
    ServiceUnavailable,
    TooManyRequests,
    ZoneInUse,
    ZoneNotEmpty,
)
from .models import (
    UnenrollResult,
    DailyRepeatingSchedule,
    LockSchedule,
    AvailableLock,
    LockCapabilities,
    LockScheduleSlots,
    LockSettingsUpdate,
    LockModeSettings,
    LockModeSettingsUpdate,
    LockSummary,
    LockSync,
    LockUser,
    LockUserCode,
    WeekDaySchedule,
    YearDaySchedule,
    ArmMode,
    DiscoverableSensor,
    GuestSchedule,
    HaLink,
    ModeSchedule,
    ModeScheduleMode,
    SecurityEventType,
    Weekday,
    KeypadSettings,
    KeypadSettingsUpdate,
    KeypadSummary,
    LockoutPolicy,
    LockoutPolicyUpdate,
    AlarmEvent,
    AlarmKind,
    ArmedFlags,
    PanicType,
    EmergencyService,
    SilenceResult,
    Siren,
    SirenKind,
    ModeConfig,
    ModeConfigUpdate,
    Panel,
    Placement,
    Source,
    Role,
    SecurityEvent,
    SensorCategory,
    ScheduleKind,
    SensorUpdate,
    User,
    UserUpdate,
    Zone,
    ZoneUpdate,
)

LOCK_PIN_LENGTHS = range(4, 9)  # Schlage parameter 0x10: 4-8 digits, default 4
LOCK_SENSITIVITIES = range(0, 6)  # parameters 0x08-0x0A: 0 = not supported, 1 = most ... 5 = least

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
API_PREFIX = "/api/v1"


def base_url(host: str, port: int, *, secure: bool = False, scheme: str | None = None) -> str:
    """`<scheme>://host:port`; `scheme` overrides the http/https choice (used for ws/wss)."""
    return f"{scheme or ('https' if secure else 'http')}://{host}:{port}"


def auth_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _lock_sync(body: Any) -> list[LockSync]:
    """`lockSync` of a code route's `200 {lockSync}` body; `[]` for the older `204` (no body)."""
    return list(body.get("lockSync", [])) if isinstance(body, dict) else []


async def _error_body(response: aiohttp.ClientResponse) -> tuple[str, str, dict[str, Any]]:
    """`(code, message, error)` of the service's `{ "error": { code, message, ...extra } }` body.

    `code` and `message` are `""` and `error` is `{}` if the body is absent or malformed.
    """
    try:
        error = (await response.json(content_type=None))["error"]
        return str(error.get("code", "")), str(error["message"]), dict(error)
    except (aiohttp.ClientError, ValueError, KeyError, TypeError, AttributeError):
        return "", "", {}


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    host: str,
    port: int,
    token: str | None,
    path: str,
    *,
    secure: bool = False,
    conflict: type[Conflict] = Conflict,
    **kwargs: Any,
) -> Any:
    """Send one request and map the service's documented failure statuses to exceptions.

    Returns the decoded JSON body, or `None` for an empty (`204`) response.
    """
    url = f"{base_url(host, port, secure=secure)}{API_PREFIX}{path}"
    try:
        async with session.request(
            method, url, headers=auth_headers(token), timeout=REQUEST_TIMEOUT, **kwargs
        ) as response:
            status = response.status
            if status >= 400:
                code, message, extra = await _error_body(response)
                if status == 400:
                    if code == "schedule_kind_unsupported":
                        raise ScheduleKindUnsupported(message)
                    sensor_ids = extra.get("sensorIds")
                    raise BadRequest(message, sensor_ids if isinstance(sensor_ids, list) else None)
                if status == 401:
                    raise InvalidAuth(message)
                if status == 403:
                    raise Forbidden(message)
                if status == 404:
                    raise NotFound(message)
                if status == 409:
                    if code == "needs_bypass":
                        faulted = extra.get("faulted")
                        raise NeedsBypass(message, faulted if isinstance(faulted, list) else None)
                    if code == "schedule_conflict":
                        other = extra.get("conflictsWith")
                        raise ScheduleConflict(message, other if isinstance(other, str) else None)
                    if code == "zone_not_empty":
                        raise ZoneNotEmpty(message)
                    if code == "zone_in_use":
                        raise ZoneInUse(message)
                    if code == "code_in_use":
                        raise CodeInUse(message)
                    if code == "code_limit":
                        raise CodeLimit(message)
                    if code == "lock_not_secure":
                        raise LockNotSecure(message)
                    raise conflict(message)
                if status == 423:
                    raise AccountLocked(message)
                if status == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    raise TooManyRequests(message, float(retry_after) if retry_after.isdigit() else None)
                if status == 502 and code == "lock_unavailable":
                    raise LockUnavailable(message)
                if status == 503:
                    raise ServiceUnavailable(message, code)
                response.raise_for_status()
            if status == 204:
                return None
            return await response.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect from err


# --- Auth -------------------------------------------------------------------


async def async_login(
    session: aiohttp.ClientSession, host: str, port: int, code: str, *, secure: bool = False
) -> User:
    """`POST /auth/login`: start a cookie session (kept by `session`'s cookie jar) and return the caller's user.

    `401` -> `InvalidAuth`, `423` -> `AccountLocked`, `429` -> `TooManyRequests`.
    """
    return await _request(session, "POST", host, port, None, "/auth/login", secure=secure, json={"code": code})


async def async_logout(
    session: aiohttp.ClientSession, host: str, port: int, *, secure: bool = False
) -> None:
    """`POST /auth/logout`: end the current cookie session."""
    await _request(session, "POST", host, port, None, "/auth/logout", secure=secure)


# --- Panel ------------------------------------------------------------------


async def async_validate_connection(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> Panel:
    """Call `GET /api/v1/panel` and return the decoded AlarmPanel state.

    A `401` is a distinct, user-correctable error (bad token) from any other
    failure (unreachable host, bad port, timeout), which is `CannotConnect`.
    """
    return await _request(session, "GET", host, port, token, "/panel", secure=secure)


async def async_get_panel_state(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> Panel:
    """Fetch the current AlarmPanel state via `GET /api/v1/panel` (same request as `async_validate_connection`)."""
    return await async_validate_connection(session, host, port, token, secure=secure)


async def async_arm(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    mode: ArmMode,
    bypass: list[str] | None = None,
    source: Source | None = None,
    *,
    secure: bool = False,
) -> Panel:
    """`POST /panel/arm` and return the new AlarmPanel state.

    `bypass` lists sensor ids to bypass for this arm session (max 256); `source` defaults to `app` on the
    service. Open or offline intrusion sensors armed for `mode` that are not bypassed make the service answer
    `409 needs_bypass` -> `NeedsBypass` (carrying `faulted`), with nothing changed; retry with their ids in
    `bypass`. The `lock` and `schedule` sources bypass automatically. Arming succeeds even if every sensor is
    bypassed. Unknown or non-intrusion ids in `bypass` are `BadRequest` (`sensor_ids`). Any other `409`
    means the panel is not disarmed or a conflicting native-interface command won the race (FR-014) and is
    `CommandRejected`.
    """
    body: dict[str, Any] = {"mode": mode}
    if bypass is not None:
        body["bypass"] = list(bypass)
    if source is not None:
        body["source"] = source
    return await _request(
        session, "POST", host, port, token, "/panel/arm", secure=secure, conflict=CommandRejected, json=body
    )


async def async_disarm(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, code: str, *, secure: bool = False
) -> Panel:
    """`POST /panel/disarm` and return the new AlarmPanel state.

    A `401` means the code (not the token) was rejected; `423` means the
    account is locked (FR-016). In the service's `trigger_alarm` lockout mode
    a wrong code instead returns `200` with the panel already `alarm_triggered`.
    A zone-restricted guest's code disarms only its zone: the returned panel
    keeps its mode and lists the zone in `disarmedZoneIds` (FR-010a).
    """
    return await _request(
        session, "POST", host, port, token, "/panel/disarm", secure=secure, conflict=CommandRejected, json={"code": code}
    )


# --- Alarm events -----------------------------------------------------------


async def async_panic(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    type: PanicType,  # noqa: A002 - mirrors the service's body field
    service: EmergencyService | None = None,
    *,
    secure: bool = False,
) -> AlarmEvent:
    """`POST /panel/panic`: raise a PANIC, FIRE, MEDICAL or SOS alarm event; allowed in every panel mode.

    `service` (`police`, `fire`, `medical`) only matters for `SOS`. A bad body is `BadRequest`.
    """
    body: dict[str, Any] = {"type": type}
    if service is not None:
        body["service"] = service
    return await _request(session, "POST", host, port, token, "/panel/panic", secure=secure, json=body)


async def async_silence(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> SilenceResult:
    """`POST /panel/silence`: mute the siren but keep the alarm active; returns `{"silenced": [AlarmEvent]}`.

    A `409` (nothing is sounding) is `Conflict`.
    """
    return await _request(session, "POST", host, port, token, "/panel/silence", secure=secure)


async def async_get_alarm_events(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    active: bool | None = None,
    limit: int | None = None,
    *,
    secure: bool = False,
) -> list[AlarmEvent]:
    """`GET /alarm-events`, newest first. `active=True` keeps only open events; `limit` is 1-200 (service default 50)."""
    params: dict[str, Any] = {}
    if active is not None:
        params["active"] = "true" if active else "false"
    if limit is not None:
        params["limit"] = limit
    return await _request(
        session, "GET", host, port, token, "/alarm-events", secure=secure, params=params or None
    )


# --- Sirens -----------------------------------------------------------------


async def async_get_sirens(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[Siren]:
    """`GET /sirens`: the Z-Wave sirens enrolled with the service (empty until one is enrolled)."""
    return await _request(session, "GET", host, port, token, "/sirens", secure=secure)


async def async_put_siren(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    kind: SirenKind,
    name: str | None = None,
    duration_sec: int | None = None,
    *,
    secure: bool = False,
) -> Siren:
    """`PUT /sirens/{nodeId}` (administrator only): enrol or update a siren and return it.

    `duration_sec` (60-600) is allowed only for `OUTDOOR`; BASE and DOME are fixed at 600. A bad value or a
    node zwave-js does not know is `BadRequest`; a driver that is not ready yet is `ServiceUnavailable`.
    """
    body: dict[str, Any] = {"kind": kind}
    if name is not None:
        body["name"] = name
    if duration_sec is not None:
        body["durationSec"] = duration_sec
    return await _request(session, "PUT", host, port, token, f"/sirens/{node_id}", secure=secure, json=body)


async def async_delete_siren(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> None:
    """`DELETE /sirens/{nodeId}` (administrator only); an unknown siren is `NotFound`."""
    await _request(session, "DELETE", host, port, token, f"/sirens/{node_id}", secure=secure)


# --- Zones & sensors --------------------------------------------------------


async def async_get_zones(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[Zone]:
    """`GET /zones`: all zones, each with its joined sensors."""
    return await _request(session, "GET", host, port, token, "/zones", secure=secure)


async def async_create_zone(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, name: str, *, secure: bool = False
) -> Zone:
    """`POST /zones` (administrator only)."""
    return await _request(session, "POST", host, port, token, "/zones", secure=secure, json={"name": name})


async def async_assign_sensor(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    zone_id: str,
    zwave_node_id: int,
    name: str,
    category: SensorCategory,
    *,
    placement: Placement | None = None,
    armed: ArmedFlags | None = None,
    alerts_only: bool | None = None,
    alarm_kind: AlarmKind | None = None,
    secure: bool = False,
) -> dict[str, Any]:
    """`POST /zones/{zoneId}/sensors` (administrator only): assign an existing zwave-js node to a zone.

    `placement`, `armed` (`{"home": bool, "away": bool}`), `alerts_only` and `alarm_kind` (life-safety: `SMOKE`, `CO`, `FLOOD_FREEZE`) are sent only when given; the
    service defaults intrusion sensors to `MAIN_DOOR` armed per the spec (motion armed away only).
    `404` (unknown zone or node) -> `NotFound`; `409` (node already assigned) -> `Conflict`.
    """
    return await _request(
        session,
        "POST",
        host,
        port,
        token,
        f"/zones/{zone_id}/sensors",
        secure=secure,
        json={
            "zwaveNodeId": zwave_node_id,
            "name": name,
            "category": category,
            **({"placement": placement} if placement is not None else {}),
            **({"armed": dict(armed)} if armed is not None else {}),
            **({"alertsOnly": alerts_only} if alerts_only is not None else {}),
            **({"alarmKind": alarm_kind} if alarm_kind is not None else {}),
        },
    )


async def async_update_zone(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    zone_id: str,
    update: ZoneUpdate,
    *,
    secure: bool = False,
) -> Zone:
    """`PATCH /zones/{zoneId}` (administrator only) with any non-empty subset of `name`, `description`."""
    return await _request(session, "PATCH", host, port, token, f"/zones/{zone_id}", secure=secure, json=dict(update))


async def async_delete_zone(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    zone_id: str,
    *,
    force: bool = False,
    secure: bool = False,
) -> None:
    """`DELETE /zones/{zoneId}` (administrator only).

    `409 zone_not_empty` -> `ZoneNotEmpty` if the zone has sensors, unless `force=True`, which unassigns them.
    `409 zone_in_use` -> `ZoneInUse` while a guest's `guest_zone_id` references the zone, even with `force=True`.
    """
    params = {"force": "true"} if force else None
    await _request(session, "DELETE", host, port, token, f"/zones/{zone_id}", secure=secure, params=params)


async def async_list_discoverable_sensors(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[DiscoverableSensor]:
    """`GET /sensors/discoverable` (administrator only): zwave-js nodes not yet assigned to a zone."""
    return await _request(session, "GET", host, port, token, "/sensors/discoverable", secure=secure)


async def async_update_sensor(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    sensor_id: str,
    update: SensorUpdate,
    *,
    secure: bool = False,
) -> dict[str, Any]:
    """`PATCH /sensors/{sensorId}` (administrator only): rename, recategorise, move to another `zoneId`, or set
    `placement`, `alertsOnly` and per-mode `armed` (`{"home": bool, "away": bool}`; either key alone is fine).

    `400` (empty body, bad value, or `placement` on a life-safety sensor) -> `BadRequest`; `404` -> `NotFound`.
    The returned sensor carries the flat `armedHome` / `armedAway` fields."""
    return await _request(
        session, "PATCH", host, port, token, f"/sensors/{sensor_id}", secure=secure, json=dict(update)
    )


async def async_unassign_sensor(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, sensor_id: str, *, secure: bool = False
) -> None:
    """`DELETE /sensors/{sensorId}` (administrator only): unassign it; the zwave-js node itself is kept."""
    await _request(session, "DELETE", host, port, token, f"/sensors/{sensor_id}", secure=secure)


# --- Modes ------------------------------------------------------------------


async def async_get_modes(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> ModeConfig:
    """`GET /modes`: entry and exit delay (whole seconds, 0-180, default 60) for `armed_home` and `armed_away`."""
    return await _request(session, "GET", host, port, token, "/modes", secure=secure)


async def async_update_modes(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    update: ModeConfigUpdate,
    *,
    secure: bool = False,
) -> ModeConfig:
    """`PATCH /modes` (administrator only) with a partial per-mode change; returns the full config.

    A delay outside 0-180 or an empty body is `400` -> `BadRequest`; a non-administrator gets `Forbidden`.
    """
    return await _request(session, "PATCH", host, port, token, "/modes", secure=secure, json=dict(update))


# --- Users ------------------------------------------------------------------


async def async_list_users(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    *,
    ha_person_id: str | None = None,
    secure: bool = False,
) -> list[User]:
    """`GET /users` (administrator only); `ha_person_id` filters to the user linked to that HA person."""
    params = {"haPersonId": ha_person_id} if ha_person_id is not None else None
    return await _request(session, "GET", host, port, token, "/users", secure=secure, params=params)


async def async_create_user(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    name: str,
    role: Role,
    code: str | None = None,
    *,
    confirm_code: str | None = None,
    guest_expires_at: str | int | None = None,
    guest_zone_id: str | None = None,
    ha_person_id: str | None = None,
    ha_user_id: str | None = None,
    secure: bool = False,
) -> User:
    """`POST /users` (administrator only, except the first-run bootstrap of the first administrator).

    `code` may be omitted: the user then exists with `hasCode=false` and gets a code later via
    `async_set_user_code`. The first-run bootstrap administrator must still send one.
    `ha_person_id` / `ha_user_id` link the user to a Home Assistant person / user (display and linking only);
    a `ha_person_id` already linked to another user is a `409` -> `Conflict`.

    New codes must be exactly four digits (`BadRequest` otherwise) and unique: `409 code_in_use` ->
    `CodeInUse`, and the 257th code in the location is `409 code_limit` -> `CodeLimit`. `confirm_code`, the spec's
    second entry, must equal `code` if sent; it is never stored. An `installer` gets `guestExpiresAt` set by the
    service to 48 h from creation.

    A guest needs `guest_expires_at` (ISO date string or epoch ms) and/or
    `guest_zone_id`; a zone-restricted guest disarms only that zone (FR-010a).
    """
    body: dict[str, Any] = {"name": name, "role": role}
    if code is not None:
        body["code"] = code
    if confirm_code is not None:
        body["confirmCode"] = confirm_code
    if guest_expires_at is not None:
        body["guestExpiresAt"] = guest_expires_at
    if guest_zone_id is not None:
        body["guestZoneId"] = guest_zone_id
    if ha_person_id is not None:
        body["haPersonId"] = ha_person_id
    if ha_user_id is not None:
        body["haUserId"] = ha_user_id
    return await _request(session, "POST", host, port, token, "/users", secure=secure, json=body)


async def async_delete_user(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, *, secure: bool = False
) -> None:
    """`DELETE /users/{userId}` (administrator only)."""
    await _request(session, "DELETE", host, port, token, f"/users/{user_id}", secure=secure)


async def async_update_user(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    update: UserUpdate,
    *,
    secure: bool = False,
) -> User:
    """`PATCH /users/{userId}` (administrator only) with any non-empty subset of the fields in `UserUpdate`.

    `409` -> `Conflict` if it would demote the last administrator.
    """
    return await _request(session, "PATCH", host, port, token, f"/users/{user_id}", secure=secure, json=dict(update))


async def async_set_user_code(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    code: str,
    confirm_code: str | None = None,
    *,
    secure: bool = False,
) -> list[LockSync]:
    """`PUT /users/{userId}/code` (administrator only): set or replace the code (exactly 4 digits, write-only).

    Returns one `LockSync` per enrolled lock (the code is pushed to a free slot on each; a `failed` entry does
    not fail the call). Services before 3.7 answer `204`, in which case the list is empty.
    Resets the user's failed attempts and lockout. `409 code_in_use` -> `CodeInUse`; `409 code_limit` ->
    `CodeLimit`. `confirm_code` must equal `code` if sent; a mismatch or a non-4-digit code is `BadRequest`.
    """
    body = {"code": code, **({"confirmCode": confirm_code} if confirm_code is not None else {})}
    return _lock_sync(
        await _request(session, "PUT", host, port, token, f"/users/{user_id}/code", secure=secure, json=body)
    )


async def async_set_duress_code(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    code: str,
    confirm_code: str | None = None,
    *,
    secure: bool = False,
) -> None:
    """`PUT /users/{userId}/duress-code` (administrator only): set the owner's duress code.

    Entering it on a disarm disarms normally but quietly raises a DURESS alarm event. The target must be an
    administrator (`BadRequest` otherwise). Same code rules and errors as `async_set_user_code`; a duress code
    also counts toward the 256-code cap and may not equal another user's code or the user's own.
    """
    body = {"code": code, **({"confirmCode": confirm_code} if confirm_code is not None else {})}
    await _request(session, "PUT", host, port, token, f"/users/{user_id}/duress-code", secure=secure, json=body)


async def async_delete_duress_code(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, *, secure: bool = False
) -> None:
    """`DELETE /users/{userId}/duress-code` (administrator only)."""
    await _request(session, "DELETE", host, port, token, f"/users/{user_id}/duress-code", secure=secure)


async def async_clear_user_code(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, *, secure: bool = False
) -> list[LockSync]:
    """`DELETE /users/{userId}/code` (administrator only): the user can no longer disarm or log in.

    Also clears the user's slot on every enrolled lock and returns one `LockSync` per lock (empty on services
    before 3.7, which answer `204`). `409` -> `Conflict` for the last administrator.
    """
    return _lock_sync(await _request(session, "DELETE", host, port, token, f"/users/{user_id}/code", secure=secure))


# --- Guest schedules --------------------------------------------------------

_SCHEDULE_FIELDS = {"name": "name", "days": "days", "all_day": "allDay", "start": "start", "end": "end", "time_zone": "timeZone"}


async def async_get_guest_schedules(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, *, secure: bool = False
) -> list[GuestSchedule]:
    """`GET /users/{userId}/schedules` (administrator only). No schedule means unlimited keypad access.

    The user must be a guest (`BadRequest` otherwise); an unknown user is `NotFound`.
    """
    return await _request(session, "GET", host, port, token, f"/users/{user_id}/schedules", secure=secure)


async def async_create_guest_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    name: str,
    days: list[Weekday],
    all_day: bool = False,
    start: str | None = None,
    end: str | None = None,
    time_zone: str | None = None,
    *,
    secure: bool = False,
) -> GuestSchedule:
    """`POST /users/{userId}/schedules` (administrator only) and return the schedule.

    `days` has at least one weekday and no repeats. Unless `all_day`, both `start` and `end` (`"HH:MM"`) are
    required and must differ; an `end` at or before `start` is an overnight window. `time_zone` is an IANA name
    (default: the service's zone). Optional fields are sent only when given. A non-guest user or a bad body is
    `BadRequest`.
    """
    body: dict[str, Any] = {"name": name, "days": list(days)}
    if all_day:
        body["allDay"] = True
    if start is not None:
        body["start"] = start
    if end is not None:
        body["end"] = end
    if time_zone is not None:
        body["timeZone"] = time_zone
    return await _request(
        session, "POST", host, port, token, f"/users/{user_id}/schedules", secure=secure, json=body
    )


async def async_update_guest_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    schedule_id: str,
    *,
    secure: bool = False,
    **fields: Any,
) -> GuestSchedule:
    """`PATCH /users/{userId}/schedules/{scheduleId}` (administrator only) with any of `name`, `days`, `all_day`,
    `start`, `end`, `time_zone`; `None` clears `start`, `end` or `time_zone`.

    The service re-checks the merged schedule, so `all_day=False` on an all-day schedule without `start` and
    `end` is `BadRequest`. An unknown schedule is `NotFound`; an unknown field name is a `TypeError`.
    """
    if unknown := set(fields) - set(_SCHEDULE_FIELDS):
        raise TypeError(f"unexpected schedule field(s): {', '.join(sorted(unknown))}")
    body = {_SCHEDULE_FIELDS[key]: value for key, value in fields.items()}
    return await _request(
        session, "PATCH", host, port, token, f"/users/{user_id}/schedules/{schedule_id}", secure=secure, json=body
    )


async def async_delete_guest_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    user_id: str,
    schedule_id: str,
    *,
    secure: bool = False,
) -> None:
    """`DELETE /users/{userId}/schedules/{scheduleId}` (administrator only); an unknown schedule is `NotFound`."""
    await _request(session, "DELETE", host, port, token, f"/users/{user_id}/schedules/{schedule_id}", secure=secure)


# --- Lockout policy ---------------------------------------------------------


async def async_get_lockout_policy(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> LockoutPolicy:
    """`GET /lockout-policy` (administrator only)."""
    return await _request(session, "GET", host, port, token, "/lockout-policy", secure=secure)


async def async_update_lockout_policy(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    update: LockoutPolicyUpdate,
    *,
    secure: bool = False,
) -> LockoutPolicy:
    """`PATCH /lockout-policy` (administrator only) with any non-empty subset of the policy fields (FR-016)."""
    return await _request(session, "PATCH", host, port, token, "/lockout-policy", secure=secure, json=dict(update))


# --- Events -----------------------------------------------------------------


async def async_get_events(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    *,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    type: SecurityEventType | str | list[str] | None = None,  # noqa: A002 - mirrors the query parameter
    device_id: str | None = None,
    user_id: str | None = None,
    before: str | None = None,
    secure: bool = False,
) -> list[SecurityEvent]:
    """`GET /events`: security event history, newest first (FR-011).

    Filters (all optional, sent only when given): `type` is one event type or a list of them (an unknown type
    is `BadRequest`); `device_id`; `user_id` (matches the event's `sourceUserId`); `since` (inclusive) and
    `until` (exclusive) in epoch ms; `before` is an event id to page from (an unknown id returns `[]`);
    `limit` is 1-500 (0 or more than 500 is `BadRequest`).
    """
    if isinstance(type, list):
        type = ",".join(type)
    candidates = (
        ("since", since), ("until", until), ("limit", limit), ("type", type),
        ("deviceId", device_id), ("userId", user_id), ("before", before),
    )
    params = {key: value for key, value in candidates if value is not None}
    return await _request(session, "GET", host, port, token, "/events", secure=secure, params=params)


# --- Lock mode settings -----------------------------------------------------

_LOCK_MODE_FIELDS = ("armOnLockWithCode", "armOnOneTouch", "disarmOnUnlock", "actions")


async def async_get_lock_mode_settings(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> LockModeSettings:
    """`GET /locks/{nodeId}/mode-settings` (administrator, member or installer). An unknown lock is `NotFound`."""
    return await _request(session, "GET", host, port, token, f"/locks/{node_id}/mode-settings", secure=secure)


async def async_put_lock_mode_settings(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    *,
    secure: bool = False,
    **fields: Any,
) -> LockModeSettings:
    """`PUT /locks/{nodeId}/mode-settings` (administrator or installer) and return the settings.

    Pass any of `armOnLockWithCode`, `armOnOneTouch`, `disarmOnUnlock` (booleans) and `actions` (a partial dict
    of `disarmed` / `armed_home` / `armed_away` to `"lock"`, `"unlock"` or `None`, merged per mode). At least
    one is required (`TypeError` for none or an unknown name, before any request); a bad value is `BadRequest`.
    """
    unknown = set(fields) - set(_LOCK_MODE_FIELDS)
    if unknown or not fields:
        raise TypeError(f"unexpected lock mode setting(s): {', '.join(sorted(unknown)) or '(none given)'}")
    return await _request(
        session, "PUT", host, port, token, f"/locks/{node_id}/mode-settings", secure=secure, json=fields
    )


# --- Mode schedules ---------------------------------------------------------

_MODE_SCHEDULE_FIELDS = {
    "name": "name", "mode": "mode", "time": "time", "days": "days", "enabled": "enabled", "time_zone": "timeZone",
}


async def async_get_mode_schedules(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[ModeSchedule]:
    """`GET /mode-schedules`."""
    return await _request(session, "GET", host, port, token, "/mode-schedules", secure=secure)


async def async_create_mode_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    name: str,
    mode: ModeScheduleMode,
    time: str,
    days: list[Weekday],
    enabled: bool | None = None,
    time_zone: str | None = None,
    *,
    secure: bool = False,
) -> ModeSchedule:
    """`POST /mode-schedules` (administrator only) and return the schedule.

    `time` is `"HH:MM"` (24 h) in `time_zone` (an IANA name; default the service's zone); `days` is at least
    one weekday. `enabled` and `time_zone` are sent only when given. A clash with another enabled schedule is
    `409 schedule_conflict` -> `ScheduleConflict` (`conflicts_with`); a bad body is `BadRequest`.
    """
    body: dict[str, Any] = {"name": name, "mode": mode, "time": time, "days": list(days)}
    if enabled is not None:
        body["enabled"] = enabled
    if time_zone is not None:
        body["timeZone"] = time_zone
    return await _request(session, "POST", host, port, token, "/mode-schedules", secure=secure, json=body)


async def async_update_mode_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    schedule_id: str,
    *,
    secure: bool = False,
    **fields: Any,
) -> ModeSchedule:
    """`PATCH /mode-schedules/{id}` (administrator only) with any of `name`, `mode`, `time`, `days`, `enabled`,
    `time_zone` (`None` clears the time zone). Errors as for create; an unknown id is `NotFound`; an unknown
    field name is a `TypeError`.
    """
    if unknown := set(fields) - set(_MODE_SCHEDULE_FIELDS):
        raise TypeError(f"unexpected mode schedule field(s): {', '.join(sorted(unknown))}")
    body = {_MODE_SCHEDULE_FIELDS[key]: value for key, value in fields.items()}
    return await _request(
        session, "PATCH", host, port, token, f"/mode-schedules/{schedule_id}", secure=secure, json=body
    )


async def async_delete_mode_schedule(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, schedule_id: str, *, secure: bool = False
) -> None:
    """`DELETE /mode-schedules/{id}` (administrator only); an unknown id is `NotFound`."""
    await _request(session, "DELETE", host, port, token, f"/mode-schedules/{schedule_id}", secure=secure)


# --- Home Assistant links ---------------------------------------------------


async def async_create_ha_link(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, label: str, *, secure: bool = False
) -> HaLink:
    """`POST /ha-links` (administrator only): the response carries the plaintext `token` exactly once."""
    return await _request(session, "POST", host, port, token, "/ha-links", secure=secure, json={"label": label})


async def async_delete_ha_link(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, link_id: str, *, secure: bool = False
) -> None:
    """`DELETE /ha-links/{linkId}` (administrator only): revoke a token."""
    await _request(session, "DELETE", host, port, token, f"/ha-links/{link_id}", secure=secure)


# --- Keypads ----------------------------------------------------------------


async def async_list_keypads(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[KeypadSummary]:
    """`GET /keypads`: every keypad the service has discovered (keypad contract v1.1).

    The service wraps the list as `{ "keypads": [...] }`; this returns the list itself.
    """
    body = await _request(session, "GET", host, port, token, "/keypads", secure=secure)
    return body["keypads"]


async def async_chime_keypad(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    sound: str,
    *,
    volume: int | None = None,
    secure: bool = False,
) -> None:
    """`POST /keypads/{nodeId}/chime`: play `sound` (one of the keypad's `chimeSounds`) at `volume` 0-99.

    `404` (unknown node) -> `NotFound`; `400` (malformed body, bad volume, a sound the keypad lacks, or a
    keypad without the `chime` capability) -> `BadRequest`.
    """
    body: dict[str, Any] = {"sound": sound}
    if volume is not None:
        body["volume"] = volume
    await _request(session, "POST", host, port, token, f"/keypads/{node_id}/chime", secure=secure, json=body)



async def async_get_keypad_settings(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> KeypadSettings:
    """`GET /keypad-settings`: whether arming from a keypad needs a code (administrator or member)."""
    return await _request(session, "GET", host, port, token, "/keypad-settings", secure=secure)


async def async_update_keypad_settings(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    update: KeypadSettingsUpdate,
    *,
    secure: bool = False,
) -> KeypadSettings:
    """`PATCH /keypad-settings` (administrator only) with any non-empty subset of the settings.

    `403` -> `Forbidden`; `400` (empty or malformed body) -> `BadRequest`.
    """
    return await _request(session, "PATCH", host, port, token, "/keypad-settings", secure=secure, json=dict(update))


# --- Schlage locks (BE469 / BE468; contracts/locks.md) -----------------------


def validate_lock_code(code: str, pin_length: int | None = None) -> None:
    """Raise `BadRequest` unless `code` is 4-8 digits (the lock's PIN range), and `pin_length` long if given.

    Checked locally so a bad code never leaves the process; the service still enforces the lock's configured length.
    """
    if not code.isascii() or not code.isdigit() or len(code) not in LOCK_PIN_LENGTHS:
        raise BadRequest("lock code must be 4-8 digits")
    if pin_length is not None and len(code) != pin_length:
        raise BadRequest(f"lock code must be {pin_length} digits (the lock's configured PIN length)")


def lock_capabilities(lock: LockSummary) -> LockCapabilities:
    """Per-lock capability flags in the service's shape, plus `userSlots` from `userSlotCount`.

    Uses the lock's `capabilities` as sent (schedule flags stay tri-state: `None` = not reported yet). Only for an
    older service that sends none are they derived from `userSlotCount`, `scheduleSlots` (0 slots = `False`) and
    `supportedSettings`, with `secure` unknown.
    """
    user_slots = int(lock.get("userSlotCount") or 0)
    sent = lock.get("capabilities")
    if sent is not None:
        return {**sent, "userSlots": user_slots}
    slots = lock.get("scheduleSlots") or {}
    return {
        "secure": None,
        "userCodes": user_slots > 0,
        "schedules": {k: int(slots.get(k) or 0) > 0 for k in ("weekDay", "yearDay", "dailyRepeating")},  # type: ignore[typeddict-item]
        "alarmSettings": "alarmMode" in lock.get("supportedSettings", []),
        "userSlots": user_slots,
    }


def lock_supports_schedule(lock: LockSummary, kind: ScheduleKind) -> bool | None:
    """Whether `kind` schedules can be used: `False` means the lock has no slots (the service answers `400`)."""
    return lock_capabilities(lock)["schedules"][kind]


def _validate_lock_settings(update: LockSettingsUpdate) -> None:
    if not update:
        raise BadRequest("settings update must set at least one field")
    if "pinLength" in update and update["pinLength"] not in LOCK_PIN_LENGTHS:
        raise BadRequest("pinLength must be between 4 and 8")
    for field in ("alertSensitivity", "tamperSensitivity", "kickSensitivity"):
        if field in update and update[field] not in LOCK_SENSITIVITIES:  # type: ignore[literal-required]
            raise BadRequest(f"{field} must be between 0 and 5")


async def async_list_locks(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[LockSummary]:
    """`GET /locks`: every Schlage lock the service has discovered.

    The service wraps the list as `{ "locks": [...] }`; this returns the list itself. Values are `None` until the
    lock reports them; create entities from each lock's `supportedSettings`.
    """
    body = await _request(session, "GET", host, port, token, "/locks", secure=secure)
    return body["locks"]


async def async_get_lock(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> LockSummary:
    """`GET /locks/{nodeId}`: one lock. `404` (unknown lock) -> `NotFound`."""
    return await _request(session, "GET", host, port, token, f"/locks/{node_id}", secure=secure)


async def async_refresh_lock(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> LockSummary:
    """`POST /locks/{nodeId}/refresh`: re-read every parameter and the schedule slot counts from the lock.

    `502 lock_unavailable` -> `LockUnavailable`.
    """
    return await _request(session, "POST", host, port, token, f"/locks/{node_id}/refresh", secure=secure)


async def async_update_lock_settings(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    update: LockSettingsUpdate,
    *,
    secure: bool = False,
) -> LockSummary:
    """`PATCH /locks/{nodeId}/settings` with any non-empty subset of the writable settings.

    The service validates the whole body before writing anything. `pinLength` must be 4-8 and sensitivities 0-5
    (`BadRequest` before sending); a BE469-only setting sent to a BE468 is a `400` -> `BadRequest`;
    `502 lock_unavailable` -> `LockUnavailable`. Returns the lock with its refreshed settings.
    """
    _validate_lock_settings(update)
    return await _request(
        session, "PATCH", host, port, token, f"/locks/{node_id}/settings", secure=secure, json=dict(update)
    )


async def async_list_lock_users(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> list[LockUser]:
    """`GET /locks/{nodeId}/users`: status of user slots 1-30 (`enabled`, `disabled`, `available`); no codes.

    The service wraps the list as `{ "users": [...] }`; this returns the list itself.
    """
    body = await _request(session, "GET", host, port, token, f"/locks/{node_id}/users", secure=secure)
    return body["users"]


async def async_set_lock_user_code(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    user_id: int,
    code: str,
    *,
    status: Literal["enabled", "disabled"] | None = None,
    pin_length: int | None = None,
    secure: bool = False,
) -> LockUserCode:
    """`PUT /locks/{nodeId}/users/{userId}/code`: write-only; 4-8 digits, `status` defaults to enabled server-side.

    Pass the lock's `settings["pinLength"]` as `pin_length` to also require that exact length (`BadRequest`);
    the service enforces it too once known. Changing `pinLength` does not rewrite existing codes.
    """
    validate_lock_code(code, pin_length)
    body: dict[str, Any] = {"code": code}
    if status is not None:
        body["status"] = status
    return await _request(
        session, "PUT", host, port, token, f"/locks/{node_id}/users/{user_id}/code", secure=secure, json=body
    )


async def async_clear_lock_user_code(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, user_id: int, *, secure: bool = False
) -> None:
    """`DELETE /locks/{nodeId}/users/{userId}/code`."""
    await _request(session, "DELETE", host, port, token, f"/locks/{node_id}/users/{user_id}/code", secure=secure)


async def async_get_lock_schedule_slots(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> LockScheduleSlots:
    """`GET /locks/{nodeId}/schedules`: schedule slots available per user for each kind (unwrapped from `{ "slots" }`)."""
    body = await _request(session, "GET", host, port, token, f"/locks/{node_id}/schedules", secure=secure)
    return body["slots"]


async def async_set_lock_schedules_enabled(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    user_id: int,
    enabled: bool,
    *,
    secure: bool = False,
) -> None:
    """`PUT /locks/{nodeId}/users/{userId}/schedules/enabled`: turn schedule enforcement on or off for that user."""
    await _request(
        session,
        "PUT",
        host,
        port,
        token,
        f"/locks/{node_id}/users/{user_id}/schedules/enabled",
        secure=secure,
        json={"enabled": enabled},
    )


async def async_get_lock_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    user_id: int,
    kind: ScheduleKind,
    slot_id: int,
    *,
    secure: bool = False,
) -> LockSchedule:
    """`GET /locks/{nodeId}/users/{userId}/schedules/{kind}/{slotId}`; `schedule` is `None` for an empty slot."""
    return await _request(
        session, "GET", host, port, token, f"/locks/{node_id}/users/{user_id}/schedules/{kind}/{slot_id}", secure=secure
    )


async def async_set_lock_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    user_id: int,
    kind: ScheduleKind,
    slot_id: int,
    schedule: WeekDaySchedule | YearDaySchedule | DailyRepeatingSchedule,
    *,
    secure: bool = False,
) -> None:
    """`PUT /locks/{nodeId}/users/{userId}/schedules/{kind}/{slotId}` with the schedule for `kind`.

    `slot_id` is 1..`scheduleSlots[kind]`; times, ranges and weekdays are validated by the service (`BadRequest`).
    """
    await _request(
        session,
        "PUT",
        host,
        port,
        token,
        f"/locks/{node_id}/users/{user_id}/schedules/{kind}/{slot_id}",
        secure=secure,
        json=dict(schedule),
    )


async def async_clear_lock_schedule(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    user_id: int,
    kind: ScheduleKind,
    slot_id: int,
    *,
    secure: bool = False,
) -> None:
    """`DELETE /locks/{nodeId}/users/{userId}/schedules/{kind}/{slotId}`."""
    await _request(
        session, "DELETE", host, port, token, f"/locks/{node_id}/users/{user_id}/schedules/{kind}/{slot_id}", secure=secure
    )


# --- Lock enrollment (contracts/locks.md) -------------------------------------------------------------------------


async def async_list_discoverable_locks(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, *, secure: bool = False
) -> list[AvailableLock]:
    """`GET /locks/available` (administrators): Schlage locks paired to the controller but not enrolled.

    Use it only to offer "add lock"; never create Home Assistant devices or entities from it. `GET /locks`, the
    snapshot and `lock.changed` carry enrolled locks only. Unwrapped from `{ "locks": [...] }`.
    """
    body = await _request(session, "GET", host, port, token, "/locks/available", secure=secure)
    return body["locks"]


async def async_enroll_lock(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> LockSummary:
    """`PUT /locks/{nodeId}/enrollment` (administrators, idempotent): add a paired lock to the alarm system.

    `404` (unknown node) -> `NotFound`; `409 lock_not_secure` (included without S0/S2) -> `LockNotSecure`;
    `502 lock_unavailable` -> `LockUnavailable`. Returns the enrolled lock.
    """
    return await _request(session, "PUT", host, port, token, f"/locks/{node_id}/enrollment", secure=secure)


async def async_unenroll_lock(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, node_id: int, *, secure: bool = False
) -> UnenrollResult:
    """`DELETE /locks/{nodeId}/enrollment` (administrators, idempotent): clear the lock, then remove it from the alarm system.

    The service first deletes the user codes and schedules on the lock, then unenrolls it, always: an unreachable
    lock is still unenrolled and reported with `cleared=False` and `failures` (codes may still work on it). A lock
    that is not enrolled returns `cleared=True`. The stream sends `lock.removed`. `404` (unknown node) -> `NotFound`.
    """
    return await _request(session, "DELETE", host, port, token, f"/locks/{node_id}/enrollment", secure=secure)


async def async_set_locked(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    node_id: int,
    locked: bool,
    *,
    secure: bool = False,
) -> LockSummary:
    """`PUT /locks/{nodeId}/state` with `{locked}`: `True` throws the bolt, `False` retracts it.

    The bolt moves after the lock answers, so the returned summary may still show the old `locked`; the new state
    arrives as `lock.changed`. `404` (unknown or not enrolled) -> `NotFound`; `502 lock_unavailable` ->
    `LockUnavailable`.
    """
    return await _request(
        session, "PUT", host, port, token, f"/locks/{node_id}/state", secure=secure, json={"locked": locked}
    )
