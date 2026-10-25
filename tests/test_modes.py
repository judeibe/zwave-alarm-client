"""Phase 1: sensor placements, per-mode armed flags and per-mode entry/exit delays."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
MODES = {
    "armed_home": {"entryDelaySec": 60, "exitDelaySec": 60},
    "armed_away": {"entryDelaySec": 60, "exitDelaySec": 120},
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


async def test_get_and_update_modes() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/modes", payload=MODES)
        mocked.patch(f"{BASE}/modes", payload=MODES)
        assert await _call(api.async_get_modes) == MODES
        assert await _call(api.async_update_modes, {"armed_away": {"exitDelaySec": 120}}) == MODES
        (call,) = mocked.requests[("PATCH", URL(f"{BASE}/modes"))]
    assert call.kwargs["json"] == {"armed_away": {"exitDelaySec": 120}}


@pytest.mark.parametrize(("status", "exc"), [(400, api.BadRequest), (403, api.Forbidden)])
async def test_update_modes_errors(status: int, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/modes", status=status, payload={"error": {"code": "bad_request", "message": "x"}})
        with pytest.raises(exc):
            await _call(api.async_update_modes, {"armed_home": {"entryDelaySec": 181}})


async def test_update_sensor_sends_placement_and_armed() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/sensors/s1", payload={"id": "s1", "placement": "ENTRYWAY", "armedHome": True})
        await _call(
            api.async_update_sensor, "s1", {"placement": "ENTRYWAY", "armed": {"home": True}, "alertsOnly": False}
        )
        (call,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
    assert call.kwargs["json"] == {"placement": "ENTRYWAY", "armed": {"home": True}, "alertsOnly": False}


async def test_update_sensor_placement_on_life_safety_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/sensors/s1", status=400, payload={"error": {"code": "bad_request", "message": "x"}})
        with pytest.raises(api.BadRequest):
            await _call(api.async_update_sensor, "s1", {"placement": "ROOM"})


async def test_assign_sensor_optional_phase1_fields_only_sent_when_given() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s1"})
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s2"})
        await _call(
            api.async_assign_sensor,
            "z1", 7, "Hall", "intrusion",
            placement="ENTRYWAY", armed={"away": True}, alerts_only=False,
        )
        await _call(api.async_assign_sensor, "z1", 8, "Door", "intrusion")
        first, second = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
    assert first.kwargs["json"] == {
        "zwaveNodeId": 7, "name": "Hall", "category": "intrusion",
        "placement": "ENTRYWAY", "armed": {"away": True}, "alertsOnly": False,
    }
    assert second.kwargs["json"] == {"zwaveNodeId": 8, "name": "Door", "category": "intrusion"}
