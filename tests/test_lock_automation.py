"""Phase 6a: lock mode settings, per-lock code sync and lock history kinds."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"
SETTINGS = {
    "armOnLockWithCode": True, "armOnOneTouch": False, "disarmOnUnlock": True,
    "actions": {"disarmed": "unlock", "armed_home": None, "armed_away": "lock"},
}
SYNC = [
    {"nodeId": 44, "slot": 3, "status": "synced"},
    {"nodeId": 45, "slot": 1, "status": "failed", "message": "lock asleep"},
]


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


def _err(code: str) -> dict:
    return {"error": {"code": code, "message": code}}


async def test_get_and_put_mode_settings_send_only_given_fields() -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/locks/44/mode-settings", payload=SETTINGS)
        mocked.put(f"{BASE}/locks/44/mode-settings", payload=SETTINGS)
        assert await _call(api.async_get_lock_mode_settings, 44) == SETTINGS
        await _call(api.async_put_lock_mode_settings, 44, disarmOnUnlock=True, actions={"armed_away": "lock"})
        (call,) = mocked.requests[("PUT", URL(f"{BASE}/locks/44/mode-settings"))]
    assert call.kwargs["json"] == {"disarmOnUnlock": True, "actions": {"armed_away": "lock"}}


async def test_put_mode_settings_clears_an_action_with_none() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/locks/44/mode-settings", payload=SETTINGS)
        await _call(api.async_put_lock_mode_settings, 44, actions={"disarmed": None})
        (call,) = mocked.requests[("PUT", URL(f"{BASE}/locks/44/mode-settings"))]
    assert call.kwargs["json"] == {"actions": {"disarmed": None}}


@pytest.mark.parametrize("fields", [{}, {"colour": "red"}])
async def test_put_mode_settings_rejects_empty_or_unknown_before_any_request(fields: dict) -> None:
    with pytest.raises(TypeError):
        await _call(api.async_put_lock_mode_settings, 44, **fields)


@pytest.mark.parametrize(("status", "exc"), [(404, api.NotFound), (400, api.BadRequest), (403, api.Forbidden)])
async def test_mode_settings_errors(status: int, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/locks/9/mode-settings", status=status, payload=_err("x"))
        with pytest.raises(exc):
            await _call(api.async_put_lock_mode_settings, 9, armOnOneTouch=True)


async def test_code_routes_return_lock_sync_on_200_and_empty_on_204() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u1/code", payload={"lockSync": SYNC})
        mocked.delete(f"{BASE}/users/u1/code", payload={"lockSync": SYNC[:1]})
        mocked.put(f"{BASE}/users/u2/code", status=204)
        mocked.put(f"{BASE}/users/u3/code", payload={})
        assert await _call(api.async_set_user_code, "u1", "1234") == SYNC
        assert await _call(api.async_clear_user_code, "u1") == SYNC[:1]
        assert await _call(api.async_set_user_code, "u2", "1234") == []
        assert await _call(api.async_set_user_code, "u3", "1234") == []


async def test_create_user_response_carries_lock_sync() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users", status=201, payload={"id": "u1", "hasCode": True, "lockSync": SYNC})
        user = await _call(api.async_create_user, "Alex", "member", "1234")
    assert user["lockSync"] == SYNC


def test_lock_history_kinds_and_event_shape_are_typed() -> None:
    kinds = set(api.SecurityEventType.__args__)
    assert {"lock_locked", "lock_unlocked", "lock_jammed", "lock_offline", "lock_online"} <= kinds
    event: api.LockEvent = {
        "type": "lock.event", "nodeId": 44, "kind": "armed", "userId": None, "method": "one_touch",
    }
    assert event["kind"] in api.LockEventKind.__args__
    assert event["method"] in api.LockMethod.__args__
