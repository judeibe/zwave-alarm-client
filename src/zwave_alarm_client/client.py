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
    CommandRejected,
    Conflict,
    Forbidden,
    InvalidAuth,
    LockUnavailable,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    ZoneInUse,
    ZoneNotEmpty,
)
from .models import (
    DailyRepeatingSchedule,
    LockSchedule,
    LockScheduleSlots,
    LockSettingsUpdate,
    LockSummary,
    LockUser,
    LockUserCode,
    WeekDaySchedule,
    YearDaySchedule,
    ArmMode,
    DiscoverableSensor,
    HaLink,
    KeypadSummary,
    LockoutPolicy,
    LockoutPolicyUpdate,
    Panel,
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


async def _error_body(response: aiohttp.ClientResponse) -> tuple[str, str]:
    """`(code, message)` of the service's `{ "error": { code, message } }` body; `""` for either if absent."""
    try:
        error = (await response.json(content_type=None))["error"]
        return str(error.get("code", "")), str(error["message"])
    except (aiohttp.ClientError, ValueError, KeyError, TypeError, AttributeError):
        return "", ""


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
                code, message = await _error_body(response)
                if status == 400:
                    raise BadRequest(message)
                if status == 401:
                    raise InvalidAuth(message)
                if status == 403:
                    raise Forbidden(message)
                if status == 404:
                    raise NotFound(message)
                if status == 409:
                    if code == "zone_not_empty":
                        raise ZoneNotEmpty(message)
                    if code == "zone_in_use":
                        raise ZoneInUse(message)
                    if code == "code_in_use":
                        raise CodeInUse(message)
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
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, mode: ArmMode, *, secure: bool = False
) -> Panel:
    """`POST /panel/arm` and return the new AlarmPanel state.

    A `409` means a conflicting native-interface command won the race
    (FR-014) and is `CommandRejected`.
    """
    return await _request(
        session, "POST", host, port, token, "/panel/arm", secure=secure, conflict=CommandRejected, json={"mode": mode}
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
    secure: bool = False,
) -> dict[str, Any]:
    """`POST /zones/{zoneId}/sensors` (administrator only): assign an existing zwave-js node to a zone.

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
        json={"zwaveNodeId": zwave_node_id, "name": name, "category": category},
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
    """`PATCH /sensors/{sensorId}` (administrator only): rename, recategorise or move to another `zoneId`."""
    return await _request(
        session, "PATCH", host, port, token, f"/sensors/{sensor_id}", secure=secure, json=dict(update)
    )


async def async_unassign_sensor(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, sensor_id: str, *, secure: bool = False
) -> None:
    """`DELETE /sensors/{sensorId}` (administrator only): unassign it; the zwave-js node itself is kept."""
    await _request(session, "DELETE", host, port, token, f"/sensors/{sensor_id}", secure=secure)


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

    A guest needs `guest_expires_at` (ISO date string or epoch ms) and/or
    `guest_zone_id`; a zone-restricted guest disarms only that zone (FR-010a).
    """
    body: dict[str, Any] = {"name": name, "role": role}
    if code is not None:
        body["code"] = code
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
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, code: str, *, secure: bool = False
) -> None:
    """`PUT /users/{userId}/code` (administrator only): set or replace the code (4-12 digits, write-only).

    Resets the user's failed attempts and lockout. `409 code_in_use` -> `CodeInUse`.
    """
    await _request(session, "PUT", host, port, token, f"/users/{user_id}/code", secure=secure, json={"code": code})


async def async_clear_user_code(
    session: aiohttp.ClientSession, host: str, port: int, token: str | None, user_id: str, *, secure: bool = False
) -> None:
    """`DELETE /users/{userId}/code` (administrator only): the user can no longer disarm or log in.

    `409` -> `Conflict` for the last administrator.
    """
    await _request(session, "DELETE", host, port, token, f"/users/{user_id}/code", secure=secure)


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
    limit: int | None = None,
    secure: bool = False,
) -> list[SecurityEvent]:
    """`GET /events`: security event history, newest first (FR-011)."""
    params = {key: value for key, value in (("since", since), ("limit", limit)) if value is not None}
    return await _request(session, "GET", host, port, token, "/events", secure=secure, params=params)


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


# --- Schlage locks (BE469 / BE468; contracts/locks.md) -----------------------


def validate_lock_code(code: str, pin_length: int | None = None) -> None:
    """Raise `BadRequest` unless `code` is 4-8 digits (the lock's PIN range), and `pin_length` long if given.

    Checked locally so a bad code never leaves the process; the service still enforces the lock's configured length.
    """
    if not code.isascii() or not code.isdigit() or len(code) not in LOCK_PIN_LENGTHS:
        raise BadRequest("lock code must be 4-8 digits")
    if pin_length is not None and len(code) != pin_length:
        raise BadRequest(f"lock code must be {pin_length} digits (the lock's configured PIN length)")


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
