"""Phase 6b: chirps per mode, sensor chirp tones and keypad volume."""

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
    "armed_home": {"entryDelaySec": 60, "exitDelaySec": 60, "chirpsEnabled": False},
    "armed_away": {"entryDelaySec": 60, "exitDelaySec": 60, "chirpsEnabled": True},
    "disarmed": {"chirpsEnabled": False},
}


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


def _err(code: str = "bad_request") -> dict:
    return {"error": {"code": code, "message": code}}


async def test_modes_patch_sends_only_the_changed_chirp_fields() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/modes", payload=MODES)
        mocked.patch(f"{BASE}/modes", payload=MODES)
        mocked.patch(f"{BASE}/modes", payload=MODES)
        assert (await _call(api.async_get_modes))["disarmed"] == {"chirpsEnabled": False}
        await _call(api.async_update_modes, {"disarmed": {"chirpsEnabled": True}})
        await _call(api.async_update_modes, {"armed_away": {"chirpsEnabled": False}})
        first, second = mocked.requests[("PATCH", URL(f"{BASE}/modes"))]
    assert first.kwargs["json"] == {"disarmed": {"chirpsEnabled": True}}
    assert second.kwargs["json"] == {"armed_away": {"chirpsEnabled": False}}


async def test_modes_from_older_service_have_no_chirp_fields() -> None:
    old = {"armed_home": {"entryDelaySec": 60, "exitDelaySec": 60}, "armed_away": {"entryDelaySec": 1, "exitDelaySec": 2}}
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/modes", payload=old)
        modes = await _call(api.async_get_modes)
    assert "disarmed" not in modes and "chirpsEnabled" not in modes["armed_home"]


async def test_modes_bad_chirp_value_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/modes", status=400, payload=_err())
        with pytest.raises(api.BadRequest):
            await _call(api.async_update_modes, {"armed_home": {"chirpsEnabled": "yes"}})  # type: ignore[typeddict-item]


async def test_chirp_tone_on_update_and_assign() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/sensors/s1", payload={"id": "s1", "chirpTone": "doorbell"})
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s2"})
        mocked.post(f"{BASE}/zones/z1/sensors", status=201, payload={"id": "s3"})
        await _call(api.async_update_sensor, "s1", {"chirpTone": "doorbell"})
        await _call(api.async_assign_sensor, "z1", 7, "Door", "intrusion", chirp_tone="none")
        await _call(api.async_assign_sensor, "z1", 8, "Door", "intrusion")
        (patch,) = mocked.requests[("PATCH", URL(f"{BASE}/sensors/s1"))]
        with_tone, without = mocked.requests[("POST", URL(f"{BASE}/zones/z1/sensors"))]
    assert patch.kwargs["json"] == {"chirpTone": "doorbell"}
    assert with_tone.kwargs["json"]["chirpTone"] == "none"
    assert "chirpTone" not in without.kwargs["json"]


async def test_chirp_tone_on_life_safety_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.patch(f"{BASE}/sensors/s1", status=400, payload=_err())
        with pytest.raises(api.BadRequest):
            await _call(api.async_update_sensor, "s1", {"chirpTone": "guitar"})


def test_chirp_tone_values_match_the_service() -> None:
    assert set(api.ChirpTone.__args__) == {"none", "double_beep", "guitar", "wind_chimes", "bing_bong", "doorbell"}


async def test_keypad_volume_get_and_patch() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/keypad-settings", payload={"requireCodeToArm": True, "volume": 40})
        mocked.patch(f"{BASE}/keypad-settings", payload={"requireCodeToArm": True, "volume": 99})
        mocked.patch(f"{BASE}/keypad-settings", status=400, payload=_err())
        assert (await _call(api.async_get_keypad_settings))["volume"] == 40
        await _call(api.async_update_keypad_settings, {"volume": 99})
        with pytest.raises(api.BadRequest):
            await _call(api.async_update_keypad_settings, {"volume": 100})
        first, _ = mocked.requests[("PATCH", URL(f"{BASE}/keypad-settings"))]
    assert first.kwargs["json"] == {"volume": 99}
    assert 99 in api.KEYPAD_VOLUME_RANGE and 100 not in api.KEYPAD_VOLUME_RANGE
