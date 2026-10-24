"""Tests for the Schlage lock calls: listing, config, PIN-length-checked codes and Schedule Entry Lock schedules."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
TOKEN = "tok"
BASE = f"http://{HOST}:{PORT}/api/v1"

LOCK = {
    "nodeId": 5,
    "model": "BE469",
    "label": "Schlage BE469 Touchscreen Deadbolt with Alarm",
    "connectivityStatus": "online",
    "batteryLevel": 90,
    "supportedSettings": [
        "beeper", "vacationMode", "lockAndLeave", "autoLock", "pinLength",
        "alarmMode", "alertSensitivity", "tamperSensitivity", "kickSensitivity", "localControls",
    ],
    "settings": {
        "beeper": True, "vacationMode": False, "lockAndLeave": False, "autoLock": True, "pinLength": 4,
        "alarmMode": "alert", "alertSensitivity": 3, "tamperSensitivity": 3, "kickSensitivity": 5, "localControls": True,
    },
    "diagnostics": {
        "electronicTransitionCount": 1200, "mechanicalTransitionCount": 40, "electronicFailedCount": 2,
        "electronicHighPreloadTransitionCount": 7, "bootloaderVersion": 4,
        "userSlotBitField": [1, 0, 0, 0], "occupiedUserSlots": [1], "futureField": "kept",
    },
    "scheduleSlots": {"weekDay": 7, "yearDay": 7, "dailyRepeating": 7},
    "userSlotCount": 30,
}

BE468 = {
    **LOCK,
    "nodeId": 6,
    "model": "BE468",
    "supportedSettings": ["beeper", "vacationMode", "lockAndLeave", "autoLock", "pinLength"],
    "settings": {**LOCK["settings"], "alarmMode": None, "alertSensitivity": None, "tamperSensitivity": None,
                 "kickSensitivity": None, "localControls": None},
}


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


async def _call(coro_fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await coro_fn(session, HOST, PORT, *args, **kwargs)


def _sent(mocked, method: str, path: str):
    (call,) = mocked.requests[(method, URL(f"{BASE}{path}"))]
    return call


async def test_list_locks_unwraps_and_keeps_unknown_fields_and_nulls() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks", payload={"locks": [LOCK, BE468]})
        locks = await _call(api.async_list_locks, TOKEN)
    assert locks == [LOCK, BE468]
    assert locks[1]["settings"]["alarmMode"] is None


async def test_get_lock_and_unknown_node() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks/5", payload=LOCK)
        mocked.get(f"{BASE}/locks/99", status=404)
        assert await _call(api.async_get_lock, TOKEN, 5) == LOCK
        with pytest.raises(api.NotFound):
            await _call(api.async_get_lock, TOKEN, 99)


async def test_refresh_lock_posts_and_returns_summary() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/locks/5/refresh", payload=LOCK)
        assert await _call(api.async_refresh_lock, TOKEN, 5) == LOCK
        assert _sent(mocked, "POST", "/locks/5/refresh").kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}


async def test_lock_unavailable_502_is_distinct_but_a_cannot_connect() -> None:
    assert issubclass(api.LockUnavailable, api.CannotConnect)
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/locks/5/refresh", status=502, payload=_error("lock_unavailable", "no answer"))
        mocked.post(f"{BASE}/locks/6/refresh", status=502, payload=_error("bad_gateway", "other"))
        with pytest.raises(api.LockUnavailable, match="no answer"):
            await _call(api.async_refresh_lock, TOKEN, 5)
        with pytest.raises(api.CannotConnect) as info:
            await _call(api.async_refresh_lock, TOKEN, 6)
        assert not isinstance(info.value, api.LockUnavailable)


async def test_update_settings_patches_settings_route_with_only_given_fields() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/locks/5/settings", payload=LOCK)
        assert await _call(api.async_update_lock_settings, TOKEN, 5, {"beeper": False, "pinLength": 6}) == LOCK
        assert _sent(mocked, "PATCH", "/locks/5/settings").kwargs["json"] == {"beeper": False, "pinLength": 6}


@pytest.mark.parametrize(
    "update",
    [{}, {"pinLength": 3}, {"pinLength": 9}, {"kickSensitivity": 6}, {"alertSensitivity": -1}],
)
async def test_update_settings_rejects_invalid_values_before_sending(update: dict) -> None:
    with aioresponses() as mocked:
        with pytest.raises(api.BadRequest):
            await _call(api.async_update_lock_settings, TOKEN, 5, update)
        assert not mocked.requests


async def test_update_settings_accepts_range_boundaries() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/locks/5/settings", payload=LOCK, repeat=True)
        for update in ({"pinLength": 4}, {"pinLength": 8}, {"tamperSensitivity": 0}, {"kickSensitivity": 5}):
            await _call(api.async_update_lock_settings, TOKEN, 5, update)


async def test_update_settings_be469_only_on_be468_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/locks/6/settings", status=400, payload=_error("bad_request", "alarmMode is BE469-only"))
        with pytest.raises(api.BadRequest, match="BE469-only"):
            await _call(api.async_update_lock_settings, TOKEN, 6, {"alarmMode": "tamper"})


async def test_update_settings_lock_unavailable() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/locks/5/settings", status=502, payload=_error("lock_unavailable", "rejected"))
        with pytest.raises(api.LockUnavailable):
            await _call(api.async_update_lock_settings, TOKEN, 5, {"beeper": True})


async def test_list_lock_users_unwraps() -> None:
    users = [{"userId": 1, "status": "enabled"}, {"userId": 2, "status": "available"}]
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks/5/users", payload={"users": users})
        assert await _call(api.async_list_lock_users, TOKEN, 5) == users


async def test_set_lock_user_code_sends_code_and_optional_status() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/locks/5/users/3/code", payload={"userId": 3, "status": "disabled"}, repeat=True)
        result = await _call(api.async_set_lock_user_code, TOKEN, 5, 3, "123456", status="disabled", pin_length=6)
        assert result == {"userId": 3, "status": "disabled"}
        await _call(api.async_set_lock_user_code, TOKEN, 5, 3, "1234")
        first, second = mocked.requests[("PUT", URL(f"{BASE}/locks/5/users/3/code"))]
        assert first.kwargs["json"] == {"code": "123456", "status": "disabled"}
        assert second.kwargs["json"] == {"code": "1234"}


async def test_clear_lock_user_code() -> None:
    with aioresponses() as mocked:
        mocked.delete(f"{BASE}/locks/5/users/3/code", status=204)
        assert await _call(api.async_clear_lock_user_code, TOKEN, 5, 3) is None


@pytest.mark.parametrize("code", ["", "123", "123456789", "12a4", "١٢٣٤", "12 4"])
async def test_set_lock_user_code_rejects_non_pin_before_sending(code: str) -> None:
    with aioresponses() as mocked:
        with pytest.raises(api.BadRequest, match="4-8 digits"):
            await _call(api.async_set_lock_user_code, TOKEN, 5, 1, code)
        assert not mocked.requests


async def test_set_lock_user_code_must_match_configured_pin_length() -> None:
    with aioresponses() as mocked:
        with pytest.raises(api.BadRequest, match="6 digits"):
            await _call(api.async_set_lock_user_code, TOKEN, 5, 1, "1234", pin_length=6)
        assert not mocked.requests


async def test_set_lock_user_code_in_use() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/locks/5/users/1/code", status=409, payload=_error("code_in_use", "taken"))
        with pytest.raises(api.CodeInUse):
            await _call(api.async_set_lock_user_code, TOKEN, 5, 1, "1234")


def test_validate_lock_code_accepts_boundaries() -> None:
    api.validate_lock_code("1234")
    api.validate_lock_code("12345678", 8)


async def test_get_lock_schedule_slots_unwraps() -> None:
    slots = {"weekDay": 7, "yearDay": 7, "dailyRepeating": 7}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks/5/schedules", payload={"slots": slots})
        assert await _call(api.async_get_lock_schedule_slots, TOKEN, 5) == slots


@pytest.mark.parametrize("enabled", [True, False])
async def test_enable_disable_user_schedules(enabled: bool) -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/locks/5/users/3/schedules/enabled", status=204)
        assert await _call(api.async_set_lock_schedules_enabled, TOKEN, 5, 3, enabled) is None
        assert _sent(mocked, "PUT", "/locks/5/users/3/schedules/enabled").kwargs["json"] == {"enabled": enabled}


SCHEDULES = [
    ("weekDay", {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 30}),
    (
        "yearDay",
        {
            "startYear": 26, "startMonth": 1, "startDay": 2, "startHour": 0, "startMinute": 0,
            "stopYear": 26, "stopMonth": 1, "stopDay": 9, "stopHour": 12, "stopMinute": 0,
        },
    ),
    ("dailyRepeating", {"weekdays": [1, 2, 3], "startHour": 8, "startMinute": 30, "durationHour": 9, "durationMinute": 0}),
]


@pytest.mark.parametrize(("kind", "schedule"), SCHEDULES)
async def test_get_set_and_clear_schedule_per_kind(kind: str, schedule: dict) -> None:
    path = f"/locks/5/users/3/schedules/{kind}/2"
    with aioresponses() as mocked:
        mocked.get(f"{BASE}{path}", payload={"kind": kind, "userId": 3, "slotId": 2, "schedule": schedule})
        mocked.put(f"{BASE}{path}", status=204)
        mocked.delete(f"{BASE}{path}", status=204)
        got = await _call(api.async_get_lock_schedule, TOKEN, 5, 3, kind, 2)
        assert got["schedule"] == schedule
        assert await _call(api.async_set_lock_schedule, TOKEN, 5, 3, kind, 2, schedule) is None
        assert await _call(api.async_clear_lock_schedule, TOKEN, 5, 3, kind, 2) is None
        assert _sent(mocked, "PUT", path).kwargs["json"] == schedule


async def test_empty_schedule_slot_is_none() -> None:
    body = {"kind": "weekDay", "userId": 3, "slotId": 1, "schedule": None}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks/5/users/3/schedules/weekDay/1", payload=body)
        assert (await _call(api.async_get_lock_schedule, TOKEN, 5, 3, "weekDay", 1))["schedule"] is None


async def test_invalid_schedule_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.put(
            f"{BASE}/locks/5/users/3/schedules/weekDay/9", status=400, payload=_error("bad_request", "slotId exceeds 7")
        )
        with pytest.raises(api.BadRequest, match="exceeds 7"):
            await _call(api.async_set_lock_schedule, TOKEN, 5, 3, "weekDay", 9, SCHEDULES[0][1])
