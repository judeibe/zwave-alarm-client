"""Phase 4a: 4-digit unique codes, the 256 cap, duress code, installer role and disarm rate limit."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

import zwave_alarm_client as api

HOST = "192.168.1.50"
PORT = 3000
BASE = f"http://{HOST}:{PORT}/api/v1"


async def _call(fn, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        return await fn(session, HOST, PORT, None, *args, **kwargs)


def _err(code: str) -> dict:
    return {"error": {"code": code, "message": code}}


async def test_create_user_sends_confirm_code_and_installer_role() -> None:
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/users", status=201, payload={"id": "u1", "role": "installer"})
        await _call(api.async_create_user, "Tech", "installer", "1234", confirm_code="1234")
        (call,) = mocked.requests[("POST", URL(f"{BASE}/users"))]
    assert call.kwargs["json"] == {"name": "Tech", "role": "installer", "code": "1234", "confirmCode": "1234"}


async def test_set_user_code_confirm_only_when_given() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u1/code", status=204)
        mocked.put(f"{BASE}/users/u1/code", status=204)
        await _call(api.async_set_user_code, "u1", "1234", "1234")
        await _call(api.async_set_user_code, "u1", "1234")
        first, second = mocked.requests[("PUT", URL(f"{BASE}/users/u1/code"))]
    assert first.kwargs["json"] == {"code": "1234", "confirmCode": "1234"}
    assert second.kwargs["json"] == {"code": "1234"}


@pytest.mark.parametrize(
    ("code", "exc"), [("code_in_use", api.CodeInUse), ("code_limit", api.CodeLimit)]
)
async def test_code_conflicts_are_typed_conflicts(code: str, exc: type[Exception]) -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u1/code", status=409, payload=_err(code))
        with pytest.raises(exc) as info:
            await _call(api.async_set_user_code, "u1", "1234")
    assert isinstance(info.value, api.Conflict)
    assert not isinstance(info.value, api.CodeInUse) or exc is api.CodeInUse


async def test_bad_code_is_bad_request() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u1/code", status=400, payload=_err("bad_request"))
        with pytest.raises(api.BadRequest):
            await _call(api.async_set_user_code, "u1", "12", "13")


async def test_duress_code_set_and_delete() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u1/duress-code", status=204)
        mocked.delete(f"{BASE}/users/u1/duress-code", status=204)
        assert await _call(api.async_set_duress_code, "u1", "4321", "4321") is None
        assert await _call(api.async_delete_duress_code, "u1") is None
        (put,) = mocked.requests[("PUT", URL(f"{BASE}/users/u1/duress-code"))]
    assert put.kwargs["json"] == {"code": "4321", "confirmCode": "4321"}


async def test_duress_code_errors() -> None:
    with aioresponses() as mocked:
        mocked.put(f"{BASE}/users/u2/duress-code", status=400, payload=_err("bad_request"))
        mocked.put(f"{BASE}/users/u1/duress-code", status=409, payload=_err("code_in_use"))
        with pytest.raises(api.BadRequest):
            await _call(api.async_set_duress_code, "u2", "4321")
        with pytest.raises(api.CodeInUse):
            await _call(api.async_set_duress_code, "u1", "4321")


async def test_disarm_rate_limit_is_too_many_requests() -> None:
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/panel/disarm", status=429, payload=_err("too_many_requests"), headers={"Retry-After": "30"}
        )
        with pytest.raises(api.TooManyRequests) as info:
            await _call(api.async_disarm, "0000")
    assert info.value.retry_after == 30.0
