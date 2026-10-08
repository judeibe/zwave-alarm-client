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


KEYPAD = {
    "nodeId": 12,
    "adapterId": "ring-keypad-v2",
    "label": "Ring Keypad v2",
    "capabilities": ["arm_disarm", "emergency", "indicators", "chime", "future_thing"],
    "chimeSounds": ["double_beep", "doorbell"],
    "connectivityStatus": "online",
    "batteryLevel": None,
    "somethingNew": 1,
}


async def test_list_keypads_unwraps_and_keeps_unknown_fields() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/keypads", payload={"keypads": [KEYPAD]})
        keypads = await _call(api.async_list_keypads, TOKEN)
    assert keypads == [KEYPAD]


async def test_list_keypads_empty() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/keypads", payload={"keypads": []})
        assert await _call(api.async_list_keypads, TOKEN) == []


async def test_chime_keypad_posts_sound_and_volume() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/keypads/12/chime", status=204)
        assert await _call(api.async_chime_keypad, TOKEN, 12, "doorbell", volume=60) is None
        request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["json"] == {"sound": "doorbell", "volume": 60}
    assert request.kwargs["headers"] == {"Authorization": "Bearer tok"}


async def test_chime_keypad_omits_volume_by_default() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/keypads/12/chime", status=204)
        await _call(api.async_chime_keypad, TOKEN, 12, "guitar")
        request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["json"] == {"sound": "guitar"}


async def test_chime_keypad_volume_zero_is_sent() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/keypads/12/chime", status=204)
        await _call(api.async_chime_keypad, TOKEN, 12, "guitar", volume=0)
        request = next(iter(mocked.requests.values()))[0]
    assert request.kwargs["json"] == {"sound": "guitar", "volume": 0}


async def test_chime_keypad_unknown_node_is_not_found() -> None:
    body = {"error": {"code": "not_found", "message": "no such keypad"}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/keypads/99/chime", status=404, payload=body)
        with pytest.raises(api.NotFound, match="no such keypad"):
            await _call(api.async_chime_keypad, TOKEN, 99, "doorbell")


async def test_chime_keypad_bad_request() -> None:
    body = {"error": {"code": "bad_request", "message": "unknown sound"}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/keypads/12/chime", status=400, payload=body)
        with pytest.raises(api.BadRequest, match="unknown sound"):
            await _call(api.async_chime_keypad, TOKEN, 12, "kazoo", volume=100)


async def test_list_keypads_status_mapping() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/keypads", status=401)
        with pytest.raises(api.InvalidAuth):
            await _call(api.async_list_keypads, TOKEN)


# --- Config-panel endpoints (contracts/config-panel-api.md) ------------------


async def test_update_and_delete_zone() -> None:
    from yarl import URL

    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/zones/z1", payload={"id": "z1", "name": "Hall", "sensors": []})
        mocked.delete(f"{BASE}/zones/z1", status=204)
        mocked.delete(f"{BASE}/zones/z1?force=true", status=204)
        zone = await _call(api.async_update_zone, TOKEN, "z1", {"name": "Hall", "description": None})
        assert await _call(api.async_delete_zone, TOKEN, "z1") is None
        assert await _call(api.async_delete_zone, TOKEN, "z1", force=True) is None
        (patch_call,) = mocked.requests[("PATCH", URL(f"{BASE}/zones/z1"))]
    assert zone["name"] == "Hall"
    assert patch_call.kwargs["json"] == {"name": "Hall", "description": None}


async def test_zone_not_empty_and_code_in_use_are_typed_conflicts() -> None:
    not_empty = {"error": {"code": "zone_not_empty", "message": "zone has sensors"}}
    in_use = {"error": {"code": "code_in_use", "message": "code already used"}}
    in_zone = {"error": {"code": "zone_in_use", "message": "guest uses zone"}}
    other = {"error": {"code": "last_administrator", "message": "last admin"}}
    with aioresponses() as mocked:
        mocked.delete(f"{BASE}/zones/z1", status=409, payload=not_empty)
        mocked.delete(f"{BASE}/zones/z2?force=true", status=409, payload=in_zone)
        mocked.put(f"{BASE}/users/u1/code", status=409, payload=in_use)
        mocked.delete(f"{BASE}/users/u1/code", status=409, payload=other)
        with pytest.raises(api.ZoneNotEmpty, match="zone has sensors"):
            await _call(api.async_delete_zone, TOKEN, "z1")
        with pytest.raises(api.ZoneInUse):
            await _call(api.async_delete_zone, TOKEN, "z2", force=True)
        with pytest.raises(api.CodeInUse):
            await _call(api.async_set_user_code, TOKEN, "u1", "1234")
        with pytest.raises(api.Conflict) as info:
            await _call(api.async_clear_user_code, TOKEN, "u1")
    assert type(info.value) is api.Conflict
    assert all(issubclass(e, api.Conflict) for e in (api.ZoneNotEmpty, api.ZoneInUse, api.CodeInUse))


async def test_discoverable_sensors_and_sensor_update_unassign() -> None:
    from yarl import URL

    node = {"zwaveNodeId": 9, "name": None, "manufacturer": "Aeotec", "product": "Door", "suggestedCategory": "intrusion", "status": "alive"}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/sensors/discoverable", payload=[node])
        mocked.patch(f"{BASE}/sensors/s1", payload={"id": "s1"})
        mocked.delete(f"{BASE}/sensors/s1", status=204)
        assert await _call(api.async_list_discoverable_sensors, TOKEN) == [node]
        await _call(api.async_update_sensor, TOKEN, "s1", {"zoneId": "z2", "name": "Back door"})
        assert await _call(api.async_unassign_sensor, TOKEN, "s1") is None
        (call,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
    assert call.kwargs["json"] == {"zoneId": "z2", "name": "Back door"}


async def test_user_ha_links_filter_update_and_code() -> None:
    from yarl import URL

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users", status=201, payload={"id": "u1"})
        mocked.get(f"{BASE}/users?haPersonId=person.alex", payload=[{"id": "u1", "hasCode": True}])
        mocked.patch(f"{BASE}/users/u1", payload={"id": "u1"})
        mocked.put(f"{BASE}/users/u1/code", status=204)
        mocked.delete(f"{BASE}/users/u1/code", status=204)
        await _call(
            api.async_create_user, TOKEN, "Alex", "member", "1234", ha_person_id="person.alex", ha_user_id="abc"
        )
        users = await _call(api.async_list_users, TOKEN, ha_person_id="person.alex")
        await _call(api.async_update_user, TOKEN, "u1", {"role": "administrator", "haUserId": None})
        assert await _call(api.async_set_user_code, TOKEN, "u1", "5678") is None
        assert await _call(api.async_clear_user_code, TOKEN, "u1") is None
        (create,) = mocked.requests[("POST", URL(f"{BASE}/users"))]
        (patch,) = mocked.requests[("PATCH", URL(f"{BASE}/users/u1"))]
        (put,) = mocked.requests[("PUT", URL(f"{BASE}/users/u1/code"))]
    assert users == [{"id": "u1", "hasCode": True}]
    assert create.kwargs["json"] == {
        "name": "Alex",
        "role": "member",
        "code": "1234",
        "haPersonId": "person.alex",
        "haUserId": "abc",
    }
    assert patch.kwargs["json"] == {"role": "administrator", "haUserId": None}
    assert put.kwargs["json"] == {"code": "5678"}


async def test_create_user_without_code_omits_the_key() -> None:
    from yarl import URL

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users", status=201, payload={"id": "u1", "hasCode": False})
        user = await _call(api.async_create_user, TOKEN, "Alex", "member", ha_person_id="person.alex")
        (call,) = mocked.requests[("POST", URL(f"{BASE}/users"))]
    assert user["hasCode"] is False
    assert call.kwargs["json"] == {"name": "Alex", "role": "member", "haPersonId": "person.alex"}


async def test_service_unavailable_keeps_message_and_code() -> None:
    body = {"error": {"code": "unavailable", "message": "The zwave-js driver is not ready yet; try again shortly."}}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/panel", status=503, payload=body)
        with pytest.raises(api.ServiceUnavailable) as info:
            await _call(api.async_get_panel_state, TOKEN)
    assert str(info.value) == "The zwave-js driver is not ready yet; try again shortly."
    assert info.value.code == "unavailable"
    assert isinstance(info.value, api.CannotConnect)


async def test_service_unavailable_without_body_has_empty_code() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/panel", status=503)
        with pytest.raises(api.ServiceUnavailable) as info:
            await _call(api.async_get_panel_state, TOKEN)
    assert info.value.code == ""

