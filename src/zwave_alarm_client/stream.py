"""WebSocket push channel client (contracts/websocket-events.md)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from .client import API_PREFIX, auth_headers, base_url
from .errors import CannotConnect, InvalidAuth

DEFAULT_PING_INTERVAL = 30.0


async def _ping_loop(ws: aiohttp.ClientWebSocketResponse, interval: float) -> None:
    """Send the channel's only client->server message, `{"type": "ping"}`, until the socket closes."""
    while not ws.closed:
        await asyncio.sleep(interval)
        try:
            await ws.send_json({"type": "ping"})
        except (aiohttp.ClientError, ConnectionError):
            return


async def async_stream_events(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    token: str | None,
    *,
    secure: bool = False,
    ping_interval: float = DEFAULT_PING_INTERVAL,
) -> AsyncIterator[dict[str, Any]]:
    """Connect to `/api/v1/stream` and yield each server event (`snapshot`, `panel.changed`, ...) as a dict.

    The first event of every connection is a full `snapshot`; a caller that
    reconnects after a drop must discard its incremental state and rebuild
    from that new snapshot before trusting later events. A liveness `ping` is
    sent every `ping_interval` seconds and the server's `pong` replies are
    swallowed. Malformed messages are skipped.

    Ends normally when the server closes the connection. Raises `InvalidAuth`
    when the upgrade is refused with `401` (unknown/revoked token, or a guest
    session) and `CannotConnect` for any other connection failure; reconnect
    policy (backoff, availability) is left to the caller.
    """
    url = f"{base_url(host, port, scheme='wss' if secure else 'ws')}{API_PREFIX}/stream"
    try:
        async with session.ws_connect(url, headers=auth_headers(token)) as ws:
            pinger = asyncio.create_task(_ping_loop(ws, ping_interval))
            try:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.ERROR:
                        raise CannotConnect from ws.exception()
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        event = json.loads(message.data)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") not in (None, "pong"):
                        yield event
            finally:
                pinger.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pinger
    except aiohttp.WSServerHandshakeError as err:
        if err.status == 401:
            raise InvalidAuth from err
        raise CannotConnect from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise CannotConnect from err
