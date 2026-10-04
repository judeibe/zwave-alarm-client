"""Tests for the REST calls beyond arm/disarm, and the shared status->exception mapping."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
TOKEN = "tok"
BASE = f"http://{HOST}:{PORT}/api/v1"


async def _call(coro_fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await coro_fn(session, HOST, PORT, *args, **kwargs)


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (400, api.BadRequest),
        (401, api.InvalidAuth),
        (403, api.Forbidden),
        (404, api.NotFound),
        (409, api.Conflict),
        (423, api.AccountLocked),
        (503, api.ServiceUnavailable),
        (500, api.CannotConnect),
    ],
)
async def test_status_maps_to_exception(status: int, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/zones", status=status)
        with pytest.raises(exc):
            await _call(api.async_get_zones, TOKEN)


async def test_service_unavailable_is_a_cannot_connect() -> None:
    assert issubclass(api.ServiceUnavailable, api.CannotConnect)
    assert issubclass(api.CommandRejected, api.Conflict)
    assert issubclass(api.CannotConnect, api.ZwaveAlarmError)


async def test_error_message_from_body_is_exposed() -> None:
    body = {"error": {"code": "bad_request", "message": '"name" must not be empty'}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones", status=400, payload=body)
        with pytest.raises(api.BadRequest, match='"name" must not be empty'):
            await _call(api.async_create_zone, TOKEN, "")


async def test_429_carries_retry_after() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/auth/login", status=429, headers={"Retry-After": "42"})
        with pytest.raises(api.TooManyRequests) as info:
            await _call(api.async_login, "1234")
    assert info.value.retry_after == 42


async def test_timeout_is_cannot_connect() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/panel", exception=TimeoutError())
        with pytest.raises(api.CannotConnect):
            await _call(api.async_get_panel_state, TOKEN)


async def test_arm_conflict_is_command_rejected_but_sensor_conflict_is_plain_conflict() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=409)
        mocked.post(f"{BASE}/zones/z1/sensors", status=409)
        with pytest.raises(api.CommandRejected):
            await _call(api.async_arm, TOKEN, "armed_away")
        with pytest.raises(api.Conflict) as info:
            await _call(api.async_assign_sensor, TOKEN, "z1", 5, "Door", "intrusion")
    assert not isinstance(info.value, api.CommandRejected)


async def test_secure_uses_https() -> None:
    with aioresponses() as mocked:
        mocked.get(f"https://{HOST}:{PORT}/api/v1/panel", payload={"mode": "disarmed"})
        assert (await _call(api.async_get_panel_state, TOKEN, secure=True))["mode"] == "disarmed"


async def test_login_posts_code_without_bearer_header_and_returns_user() -> None:
    user = {"id": "u1", "name": "Owner", "role": "administrator"}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/auth/login", payload=user)
        assert await _call(api.async_login, "1234") == user
        (call,) = mocked.requests[("POST", __import__("yarl").URL(f"{BASE}/auth/login"))]
    assert call.kwargs["json"] == {"code": "1234"}
    assert "Authorization" not in call.kwargs["headers"]


async def test_logout_handles_empty_body() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/auth/logout", status=204)
        assert await _call(api.async_logout) is None


async def test_create_zone_and_assign_sensor_send_expected_bodies() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones", status=201, payload={"id": "z1", "name": "Garage", "sensors": []})
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s1"})
        zone = await _call(api.async_create_zone, TOKEN, "Garage")
        await _call(api.async_assign_sensor, TOKEN, zone["id"], 7, "Side door", "life-safety")
        from yarl import URL

        (zone_call,) = mocked.requests[("POST", URL(f"{BASE}/zones"))]
        (sensor_call,) = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
    assert zone_call.kwargs["json"] == {"name": "Garage"}
    assert sensor_call.kwargs["json"] == {"zwaveNodeId": 7, "name": "Side door", "category": "life-safety"}


async def test_create_user_guest_fields_only_sent_when_given() -> None:
    from yarl import URL

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users", status=201, payload={"id": "u1"}, repeat=True)
        await _call(api.async_create_user, TOKEN, "Nina", "member", "1111")
        await _call(
            api.async_create_user, TOKEN, "Sam", "guest", "2222", guest_zone_id="z1", guest_expires_at="2030-01-01"
        )
        first, second = mocked.requests[("POST", URL(f"{BASE}/users"))]
    assert first.kwargs["json"] == {"name": "Nina", "role": "member", "code": "1111"}
    assert second.kwargs["json"] == {
        "name": "Sam",
        "role": "guest",
        "code": "2222",
        "guestExpiresAt": "2030-01-01",
        "guestZoneId": "z1",
    }


async def test_list_and_delete_user() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/users", payload=[{"id": "u1"}])
        mocked.delete(f"{BASE}/users/u1", status=204)
        assert await _call(api.async_list_users, TOKEN) == [{"id": "u1"}]
        assert await _call(api.async_delete_user, TOKEN, "u1") is None


async def test_lockout_policy_get_and_patch() -> None:
    from yarl import URL

    policy = {"failedAttemptThreshold": 3, "cooldownSeconds": 60, "onThresholdExceeded": "trigger_alarm"}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/lockout-policy", payload=policy)
        mocked.patch(f"{BASE}/lockout-policy", payload=policy)
        assert await _call(api.async_get_lockout_policy, TOKEN) == policy
        assert await _call(api.async_update_lockout_policy, TOKEN, {"onThresholdExceeded": "trigger_alarm"}) == policy
        (call,) = mocked.requests[("PATCH", URL(f"{BASE}/lockout-policy"))]
    assert call.kwargs["json"] == {"onThresholdExceeded": "trigger_alarm"}


async def test_get_events_passes_only_given_query_params() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/events?limit=5", payload=[])
        mocked.get(f"{BASE}/events?since=100&limit=5", payload=[{"id": "e1"}])
        assert await _call(api.async_get_events, TOKEN, limit=5) == []
        assert await _call(api.async_get_events, TOKEN, since=100, limit=5) == [{"id": "e1"}]


async def test_ha_link_create_returns_token_and_delete_revokes() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/ha-links", status=201, payload={"id": "l1", "label": "HA", "token": "secret"})
        mocked.delete(f"{BASE}/ha-links/l1", status=204)
        assert (await _call(api.async_create_ha_link, TOKEN, "HA"))["token"] == "secret"
        assert await _call(api.async_delete_ha_link, TOKEN, "l1") is None


async def test_disarm_zone_restricted_guest_panel_is_returned_verbatim() -> None:
    panel = {"mode": "armed_away", "armedMode": "armed_away", "disarmedZoneIds": ["z1"], "pendingDelayEndsAt": None}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/disarm", payload=panel)
        assert await _call(api.async_disarm, TOKEN, "2222") == panel
