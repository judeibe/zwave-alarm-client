"""Phase 2: pre-arm bypass (`needs_bypass`), arm sources and the arm-session panel fields."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
FAULTED = [
    {"sensorId": "s1", "name": "Front door", "zoneId": "z1", "reason": "open"},
    {"sensorId": "s2", "name": "Back door", "zoneId": "z1", "reason": "offline"},
]
PANEL = {
    "mode": "arming",
    "armedMode": "armed_away",
    "pendingDelayEndsAt": 1000,
    "exitEndsAt": 1000,
    "entryEndsAt": None,
    "disarmedZoneIds": [],
    "bypassedDeviceIds": ["s1", "s2"],
}


async def _arm(*args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await api.async_arm(session, HOST, PORT, None, *args, **kwargs)


async def test_arm_sends_bypass_and_source_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", payload=PANEL)
        mocked.post(f"{BASE}/panel/arm", payload=PANEL)
        assert await _arm("armed_away", ["s1", "s2"], "keypad") == PANEL
        await _arm("armed_home")
        first, second = mocked.requests[("POST", URL(f"{BASE}/panel/arm"))]
    assert first.kwargs["json"] == {"mode": "armed_away", "bypass": ["s1", "s2"], "source": "keypad"}
    assert second.kwargs["json"] == {"mode": "armed_home"}


async def test_arm_with_empty_bypass_list_is_sent() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", payload=PANEL)
        await _arm("armed_away", [])
        (call,) = mocked.requests[("POST", URL(f"{BASE}/panel/arm"))]
    assert call.kwargs["json"] == {"mode": "armed_away", "bypass": []}


async def test_needs_bypass_carries_faulted_and_is_a_conflict() -> None:
    body = {"error": {"code": "needs_bypass", "message": "Faulted sensors", "faulted": FAULTED}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=409, payload=body)
        with pytest.raises(api.NeedsBypass) as info:
            await _arm("armed_away")
    assert info.value.faulted == FAULTED
    assert isinstance(info.value, api.Conflict)
    assert not isinstance(info.value, api.CommandRejected)


async def test_retry_with_faulted_ids_succeeds() -> None:
    body = {"error": {"code": "needs_bypass", "message": "Faulted sensors", "faulted": FAULTED}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=409, payload=body)
        mocked.post(f"{BASE}/panel/arm", payload=PANEL)
        with pytest.raises(api.NeedsBypass) as info:
            await _arm("armed_away")
        panel = await _arm("armed_away", [f["sensorId"] for f in info.value.faulted])
    assert panel["bypassedDeviceIds"] == ["s1", "s2"]


async def test_plain_conflict_stays_command_rejected() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=409, payload={"error": {"code": "conflict", "message": "busy"}})
        with pytest.raises(api.CommandRejected):
            await _arm("armed_away")


async def test_bad_bypass_ids_exposed_on_bad_request() -> None:
    body = {"error": {"code": "bad_request", "message": "Unknown sensors", "sensorIds": ["nope"]}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=400, payload=body)
        with pytest.raises(api.BadRequest) as info:
            await _arm("armed_away", ["nope"])
    assert info.value.sensor_ids == ["nope"]


async def test_bad_request_without_sensor_ids_defaults_empty() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=400, payload={"error": {"code": "bad_request", "message": "x"}})
        with pytest.raises(api.BadRequest) as info:
            await _arm("armed_away")
    assert info.value.sensor_ids == []
