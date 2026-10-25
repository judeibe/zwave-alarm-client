"""Phase 3b: sirens and the sensor `tampered` flag."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
SIREN = {"nodeId": 12, "kind": "OUTDOOR", "name": "Porch", "durationSec": 240, "createdAt": 1}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


async def test_get_sirens() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/sirens", payload=[SIREN])
        mocked.get(f"{BASE}/sirens", payload=[])
        assert await _call(api.async_get_sirens) == [SIREN]
        assert await _call(api.async_get_sirens) == []


async def test_put_siren_sends_optional_fields_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/sirens/12", payload=SIREN)
        mocked.put(f"{BASE}/sirens/3", payload={**SIREN, "nodeId": 3, "kind": "BASE", "durationSec": 600})
        assert await _call(api.async_put_siren, 12, "OUTDOOR", "Porch", 240) == SIREN
        await _call(api.async_put_siren, 3, "BASE")
        outdoor, base = (
            mocked.requests[("PUT", URL(f"{BASE}/sirens/12"))][0],
            mocked.requests[("PUT", URL(f"{BASE}/sirens/3"))][0],
        )
    assert outdoor.kwargs["json"] == {"kind": "OUTDOOR", "name": "Porch", "durationSec": 240}
    assert base.kwargs["json"] == {"kind": "BASE"}


@pytest.mark.parametrize(("status", "exc"), [(400, api.BadRequest), (503, api.ServiceUnavailable)])
async def test_put_siren_errors(status: int, exc: type[Exception]) -> None:
    code = "bad_request" if status == 400 else "unavailable"
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/sirens/12", status=status, payload={"error": {"code": code, "message": "x"}})
        with pytest.raises(exc):
            await _call(api.async_put_siren, 12, "BASE", None, 90)


async def test_delete_siren_and_not_found() -> None:
    with aioresponses() as mocked:
        mocked.delete(f"{BASE}/sirens/12", status=204)
        mocked.delete(f"{BASE}/sirens/99", status=404, payload={"error": {"code": "not_found", "message": "x"}})
        assert await _call(api.async_delete_siren, 12) is None
        with pytest.raises(api.NotFound):
            await _call(api.async_delete_siren, 99)


async def test_tampered_reason_round_trips_through_needs_bypass() -> None:
    faulted = [{"sensorId": "s1", "name": "Door", "zoneId": "z1", "reason": "tampered"}]
    body = {"error": {"code": "needs_bypass", "message": "x", "faulted": faulted}}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/panel/arm", status=409, payload=body)
        with pytest.raises(api.NeedsBypass) as info:
            await _call(api.async_arm, "armed_away")
    assert info.value.faulted[0]["reason"] == "tampered"
