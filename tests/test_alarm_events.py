"""Phase 3a: panic/SOS, silence siren, alarm event history and life-safety `alarmKind`."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
EVENT = {
    "id": "e1",
    "type": "SOS",
    "service": "medical",
    "triggerDeviceId": None,
    "startedAt": 1,
    "sirenState": "sounding",
    "dispatchState": "queued",
    "cancelledAt": None,
    "endedAt": None,
    "details": None,
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


async def test_panic_sends_service_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/panic", status=201, payload=EVENT)
        mocked.post(f"{BASE}/panel/panic", status=201, payload=EVENT)
        assert await _call(api.async_panic, "SOS", "medical") == EVENT
        await _call(api.async_panic, "FIRE")
        sos, fire = mocked.requests[("POST", URL(f"{BASE}/panel/panic"))]
    assert sos.kwargs["json"] == {"type": "SOS", "service": "medical"}
    assert fire.kwargs["json"] == {"type": "FIRE"}


async def test_panic_bad_body_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/panic", status=400, payload={"error": {"code": "bad_request", "message": "x"}})
        with pytest.raises(api.BadRequest):
            await _call(api.async_panic, "PANIC")


async def test_silence_returns_silenced_events_and_conflict_when_quiet() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/silence", payload={"silenced": [EVENT]})
        mocked.post(f"{BASE}/panel/silence", status=409, payload={"error": {"code": "conflict", "message": "quiet"}})
        assert (await _call(api.async_silence))["silenced"] == [EVENT]
        with pytest.raises(api.Conflict):
            await _call(api.async_silence)


async def test_get_alarm_events_query() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/alarm-events?active=true&limit=5", payload=[EVENT])
        mocked.get(f"{BASE}/alarm-events", payload=[])
        assert await _call(api.async_get_alarm_events, True, 5) == [EVENT]
        assert await _call(api.async_get_alarm_events) == []


async def test_sensor_alarm_kind_on_assign_and_update() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s1"})
        mocked.patch(f"{BASE}/sensors/s1", payload={"id": "s1"})
        await _call(api.async_assign_sensor, "z1", 9, "Smoke", "life-safety", alarm_kind="SMOKE")
        await _call(api.async_update_sensor, "s1", {"alarmKind": "CO"})
        (assign,) = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
        (update,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
    assert assign.kwargs["json"]["alarmKind"] == "SMOKE"
    assert update.kwargs["json"] == {"alarmKind": "CO"}
