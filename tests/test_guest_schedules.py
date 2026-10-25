"""Phase 4b: guest schedules (keypad access windows)."""

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
    "id": "sc1", "userId": "u1", "name": "Weekdays", "days": ["mon", "tue"], "allDay": False,
    "start": "08:00", "end": "17:00", "timeZone": "America/Chicago", "createdAt": 1,
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


async def test_get_schedules() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/users/u1/schedules", payload=[SCHEDULE])
        assert await _call(api.async_get_guest_schedules, "u1") == [SCHEDULE]


async def test_create_sends_optional_fields_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users/u1/schedules", status=201, payload=SCHEDULE)
        mocked.post(f"{BASE}/users/u1/schedules", status=201, payload=SCHEDULE)
        await _call(api.async_create_guest_schedule, "u1", "Weekdays", ["mon"], start="08:00", end="17:00",
                    time_zone="America/Chicago")
        await _call(api.async_create_guest_schedule, "u1", "Always", ["sat", "sun"], all_day=True)
        timed, all_day = mocked.requests[("POST", URL(f"{BASE}/users/u1/schedules"))]
    assert timed.kwargs["json"] == {
        "name": "Weekdays", "days": ["mon"], "start": "08:00", "end": "17:00", "timeZone": "America/Chicago",
    }
    assert all_day.kwargs["json"] == {"name": "Always", "days": ["sat", "sun"], "allDay": True}


async def test_update_maps_python_names_and_passes_none_through() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/users/u1/schedules/sc1", payload=SCHEDULE)
        await _call(api.async_update_guest_schedule, "u1", "sc1", all_day=True, start=None, end=None, time_zone=None)
        (call,) = mocked.requests[("PATCH", URL(f"{BASE}/users/u1/schedules/sc1"))]
    assert call.kwargs["json"] == {"allDay": True, "start": None, "end": None, "timeZone": None}


async def test_update_rejects_unknown_field_without_a_request() -> None:
    with pytest.raises(TypeError):
        await _call(api.async_update_guest_schedule, "u1", "sc1", colour="red")


async def test_delete_and_errors() -> None:
    err = lambda code: {"error": {"code": code, "message": code}}  # noqa: E731
    with aioresponses() as mocked:
        mocked.delete(f"{BASE}/users/u1/schedules/sc1", status=204)
        mocked.delete(f"{BASE}/users/u1/schedules/nope", status=404, payload=err("not_found"))
        mocked.post(f"{BASE}/users/u2/schedules", status=400, payload=err("bad_request"))
        assert await _call(api.async_delete_guest_schedule, "u1", "sc1") is None
        with pytest.raises(api.NotFound):
            await _call(api.async_delete_guest_schedule, "u1", "nope")
        with pytest.raises(api.BadRequest):
            await _call(api.async_create_guest_schedule, "u2", "x", ["mon"], all_day=True)
