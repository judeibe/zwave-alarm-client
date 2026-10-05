"""Tests for the WebSocket stream client against a real in-process server."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import zwave_alarm_client as api

SNAPSHOT = {"type": "snapshot", "panel": {"mode": "disarmed", "pendingDelayEndsAt": None, "disarmedZoneIds": []}, "zones": []}


async def _serve(handler):
    app = web.Application()
    app.router.add_get("/api/v1/stream", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def _collect(server: TestServer, token: str | None = "tok", **kwargs) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        return [e async for e in api.async_stream_events(session, "127.0.0.1", server.port, token, **kwargs)]


async def test_yields_events_in_order_and_skips_pong_and_garbage() -> None:
    seen_auth: list[str | None] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        seen_auth.append(request.headers.get("Authorization"))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(SNAPSHOT)
        await ws.send_str("not json")
        await ws.send_json({"type": "pong"})
        await ws.send_json({"type": "panel.changed", "mode": "armed_away"})
        await ws.close()
        return ws

    server = await _serve(handler)
    try:
        events = await _collect(server)
    finally:
        await server.close()

    assert [e["type"] for e in events] == ["snapshot", "panel.changed"]
    assert seen_auth == ["Bearer tok"]


async def test_sends_periodic_ping_and_ignores_pong_reply() -> None:
    pings: list[dict] = []

    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(SNAPSHOT)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT and json.loads(msg.data) == {"type": "ping"}:
                pings.append(json.loads(msg.data))
                await ws.send_json({"type": "pong"})
                await ws.send_json({"type": "event.recorded", "event": {"id": "e1"}})
                await ws.close()
        return ws

    server = await _serve(handler)
    try:
        events = await asyncio.wait_for(_collect(server, ping_interval=0.05), timeout=5)
    finally:
        await server.close()

    assert pings == [{"type": "ping"}]
    assert [e["type"] for e in events] == ["snapshot", "event.recorded"]


async def test_handshake_401_is_invalid_auth() -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": {"code": "unauthorized", "message": "no"}}, status=401)

    server = await _serve(handler)
    try:
        with pytest.raises(api.InvalidAuth):
            await _collect(server)
    finally:
        await server.close()


async def test_handshake_other_failure_is_cannot_connect() -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=503)

    server = await _serve(handler)
    try:
        with pytest.raises(api.CannotConnect):
            await _collect(server)
    finally:
        await server.close()


async def test_unreachable_host_is_cannot_connect() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(api.CannotConnect):
            async for _ in api.async_stream_events(session, "127.0.0.1", 1, "tok"):
                pass


async def test_keypad_messages_pass_through_including_unknown_kinds_and_fields() -> None:
    keypad = {"nodeId": 12, "adapterId": "ring-keypad-v2", "label": "K", "capabilities": ["future"], "chimeSounds": [],
              "connectivityStatus": "online", "batteryLevel": None, "extra": True}
    messages = [
        {**SNAPSHOT, "keypads": [keypad]},
        {"type": "keypad.changed", "keypad": keypad},
        {"type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": "emergency", "emergency": "fire"}},
        {"type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": "from_the_future"}},
    ]

    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        for message in messages:
            await ws.send_json(message)
        await ws.close()
        return ws

    server = await _serve(handler)
    try:
        events = await _collect(server)
    finally:
        await server.close()

    assert events == messages


async def test_snapshot_without_keypads_is_still_delivered() -> None:
    async def handler(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json(SNAPSHOT)
        await ws.close()
        return ws

    server = await _serve(handler)
    try:
        events = await _collect(server)
    finally:
        await server.close()

    assert events == [SNAPSHOT]
    assert "keypads" not in events[0]
