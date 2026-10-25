"""Phase 5: event filters and fields, and mode schedules."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
SCHEDULE = {
    "id": "m1", "name": "Night", "mode": "armed_home", "time": "22:00", "days": ["mon", "tue"],
    "enabled": True, "timeZone": "America/Chicago", "createdAt": 1, "lastRunAt": None,
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


def _err(code: str, **extra) -> dict:
    return {"error": {"code": code, "message": code, **extra}}


async def test_events_filters_are_sent_only_when_given_and_type_list_is_joined() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/events", payload=[])
        mocked.get(
            f"{BASE}/events?before=e9&deviceId=s1&limit=500&since=1&type=tamper%2Ctamper_cleared&until=2&userId=u1",
            payload=[{"id": "e1", "actor": "Alex", "deviceId": "s1", "deviceName": "Door"}],
        )
        assert await _call(api.async_get_events) == []
        events = await _call(
            api.async_get_events, since=1, until=2, limit=500, type=["tamper", "tamper_cleared"],
            device_id="s1", user_id="u1", before="e9",
        )
    assert events[0]["deviceName"] == "Door"


async def test_events_single_type_string_and_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/events?type=armed", payload=[])
        mocked.get(f"{BASE}/events?type=nope", status=400, payload=_err("bad_request"))
        assert await _call(api.async_get_events, type="armed") == []
        with pytest.raises(api.BadRequest):
            await _call(api.async_get_events, type="nope")


async def test_mode_schedule_crud() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/mode-schedules", payload=[SCHEDULE])
        mocked.post(f"{BASE}/mode-schedules", status=201, payload=SCHEDULE)
        mocked.post(f"{BASE}/mode-schedules", status=201, payload=SCHEDULE)
        mocked.patch(f"{BASE}/mode-schedules/m1", payload=SCHEDULE)
        mocked.delete(f"{BASE}/mode-schedules/m1", status=204)
        assert await _call(api.async_get_mode_schedules) == [SCHEDULE]
        await _call(api.async_create_mode_schedule, "Night", "armed_home", "22:00", ["mon"])
        await _call(
            api.async_create_mode_schedule, "Night", "armed_home", "22:00", ["mon"], False, "America/Chicago"
        )
        await _call(api.async_update_mode_schedule, "m1", enabled=False, time_zone=None)
        assert await _call(api.async_delete_mode_schedule, "m1") is None
        plain, full = mocked.requests[("POST", URL(f"{BASE}/mode-schedules"))]
        (patch,) = mocked.requests[("PATCH", URL(f"{BASE}/mode-schedules/m1"))]
    assert plain.kwargs["json"] == {"name": "Night", "mode": "armed_home", "time": "22:00", "days": ["mon"]}
    assert full.kwargs["json"]["enabled"] is False and full.kwargs["json"]["timeZone"] == "America/Chicago"
    assert patch.kwargs["json"] == {"enabled": False, "timeZone": None}


async def test_schedule_conflict_exposes_conflicting_id() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/mode-schedules", status=409, payload=_err("schedule_conflict", conflictsWith="m7"))
        with pytest.raises(api.ScheduleConflict) as info:
            await _call(api.async_create_mode_schedule, "Dup", "armed_away", "22:00", ["mon"])
    assert info.value.conflicts_with == "m7"
    assert isinstance(info.value, api.Conflict)


async def test_mode_schedule_errors_and_unknown_field() -> None:
    with aioresponses() as mocked:
        mocked.delete(f"{BASE}/mode-schedules/nope", status=404, payload=_err("not_found"))
        with pytest.raises(api.NotFound):
            await _call(api.async_delete_mode_schedule, "nope")
    with pytest.raises(TypeError):
        await _call(api.async_update_mode_schedule, "m1", colour="red")
