"""Service 3.9: per-sensor entry settings and the Ring supported-device allowlist."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
SENSOR = {
    "id": "s1", "zwaveNodeId": 39, "zoneId": "z1", "name": "Front door", "category": "intrusion",
    "currentState": "normal", "batteryLevel": 90, "connectivityStatus": "online", "placement": "MAIN_DOOR",
    "armedHome": True, "armedAway": True, "alertsOnly": False, "alarmKind": None, "chirpTone": "double_beep",
    "chimeEnabled": True, "chimeSound": "double_beep", "sensorKind": "door", "entryway": "Front door",
    "isInterior": False, "quickExitEnabled": False, "quickEntrySupported": False, "updatedAt": 1,
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


def _err(code: str) -> dict:
    return {"error": {"code": code, "message": code}}


async def test_get_sensors_and_one_sensor() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/sensors", payload=[SENSOR])
        mocked.get(f"{BASE}/sensors/s1", payload=SENSOR)
        mocked.get(f"{BASE}/sensors/nope", status=404, payload=_err("not_found"))
        assert (await _call(api.async_get_sensors))[0]["sensorKind"] == "door"
        assert (await _call(api.async_get_sensor, "s1"))["entryway"] == "Front door"
        with pytest.raises(api.NotFound):
            await _call(api.async_get_sensor, "nope")


async def test_supported_devices() -> None:
    devices = [
        {"brand": "Ring", "model": "Contact Sensor", "manufacturerId": 838, "productType": 513, "productId": 1,
         "deviceType": "contact", "category": "intrusion", "suggestedSensorKind": "door"},
        {"brand": "Ring", "model": "Range Extender", "manufacturerId": 838, "productType": 1, "productId": 2,
         "deviceType": "range_extender", "category": None, "suggestedSensorKind": "interior"},
    ]
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/sensors/supported-devices", payload=devices)
        got = await _call(api.async_list_supported_devices)
    assert got[1]["category"] is None and got[0]["brand"] == "Ring"


async def test_update_sends_only_the_given_entry_fields() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/sensors/s1", payload=SENSOR)
        await _call(
            api.async_update_sensor, "s1",
            {"chimeEnabled": False, "chimeSound": "guitar", "sensorKind": "window", "entryway": None, "isInterior": True},
        )
        (request,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
    assert request.kwargs["json"] == {
        "chimeEnabled": False, "chimeSound": "guitar", "sensorKind": "window", "entryway": None, "isInterior": True,
    }


async def test_assign_sends_entry_fields_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", payload=SENSOR)
        mocked.post(f"{BASE}/zones/z1/sensors", payload=SENSOR)
        await _call(api.async_assign_sensor, "z1", 39, "Front door", "intrusion")
        await _call(
            api.async_assign_sensor, "z1", 39, "Front door", "intrusion",
            chime_enabled=False, chime_sound="doorbell", sensor_kind="door", entryway="Front", is_interior=False,
            quick_entry_supported=True,
        )
        plain, full = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
    assert plain.kwargs["json"] == {"zwaveNodeId": 39, "name": "Front door", "category": "intrusion"}
    assert full.kwargs["json"] == {
        "zwaveNodeId": 39, "name": "Front door", "category": "intrusion", "chimeEnabled": False,
        "chimeSound": "doorbell", "sensorKind": "door", "entryway": "Front", "isInterior": False,
        "quickEntrySupported": True,
    }


@pytest.mark.parametrize(("code", "exc"), [("unsupported_device", api.UnsupportedDevice), ("category_mismatch", api.CategoryMismatch)])
async def test_422_maps_to_typed_errors(code: str, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", status=422, payload=_err(code))
        with pytest.raises(exc):
            await _call(api.async_assign_sensor, "z1", 7, "x", "intrusion")


async def test_unknown_422_is_not_a_connection_error_mapping() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", status=422, payload=_err("other"))
        with pytest.raises(api.CannotConnect):
            await _call(api.async_assign_sensor, "z1", 7, "x", "intrusion")


async def test_older_sensor_without_entry_fields_still_parses() -> None:
    old = {k: v for k, v in SENSOR.items() if k not in {"chimeEnabled", "chimeSound", "sensorKind", "entryway", "isInterior", "quickExitEnabled", "quickEntrySupported"}}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/sensors/s1", payload=old)
        got = await _call(api.async_get_sensor, "s1")
    assert "sensorKind" not in got


async def test_quick_exit_posts_and_returns_the_window() -> None:
    reply = {"sensorId": "s1", "expiresAt": "2026-10-28T13:28:28.000Z"}
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/sensors/s1/quick-exit", payload=reply)
        assert await _call(api.async_quick_exit, "s1") == reply
        (request,) = mocked.requests[("POST", URL(f"{BASE}/sensors/s1/quick-exit"))]
    assert "json" not in request.kwargs


@pytest.mark.parametrize(
    ("code", "exc"),
    [("quick_exit_disabled", api.QuickExitDisabled), ("quick_exit_unavailable", api.QuickExitUnavailable)],
)
async def test_quick_exit_409s_are_typed_conflicts(code: str, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/sensors/s1/quick-exit", status=409, payload=_err(code))
        with pytest.raises(exc) as info:
            await _call(api.async_quick_exit, "s1")
    assert isinstance(info.value, api.Conflict)


async def test_quick_exit_unknown_sensor_is_not_found() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/sensors/nope/quick-exit", status=404, payload=_err("not_found"))
        with pytest.raises(api.NotFound):
            await _call(api.async_quick_exit, "nope")


async def test_assign_and_update_send_quick_exit_and_keep_the_old_alias() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/zones/z1/sensors", payload=SENSOR)
        mocked.patch(f"{BASE}/sensors/s1", payload=SENSOR)
        await _call(api.async_assign_sensor, "z1", 39, "Door", "intrusion", quick_exit_enabled=True)
        await _call(api.async_update_sensor, "s1", {"quickExitEnabled": False})
        (post,) = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
        (patch,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
    assert post.kwargs["json"]["quickExitEnabled"] is True and "quickEntrySupported" not in post.kwargs["json"]
    assert patch.kwargs["json"] == {"quickExitEnabled": False}
