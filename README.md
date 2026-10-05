# zwave-alarm-client

Async Python client (aiohttp) for the REST API of the [Z-Wave Alarm service](https://github.com/judeibe/zwave_alarm). Used by the [Home Assistant integration](https://github.com/judeibe/ha-zwave-alarm); contains no Home Assistant code.

```python
import aiohttp
from zwave_alarm_client import async_get_panel_state, async_stream_events, InvalidAuth, CannotConnect

async with aiohttp.ClientSession() as session:
    panel = await async_get_panel_state(session, "192.168.1.50", 3000, token)

    async for event in async_stream_events(session, "192.168.1.50", 3000, token):
        ...  # first event is a full `snapshot`, then `panel.changed`, `sensor.changed`, ...
```

Every call takes `(session, host, port, token, ...)`; pass `token=None` to use a cookie session from `async_login` instead, and `secure=True` for https/wss.

## Coverage

| Area | Calls |
|---|---|
| Auth | `async_login`, `async_logout` |
| Panel | `async_get_panel_state`, `async_validate_connection`, `async_arm`, `async_disarm` (zone-restricted guests return a panel with `disarmedZoneIds`) |
| Zones & sensors | `async_get_zones`, `async_create_zone`, `async_update_zone`, `async_delete_zone` (`force=`), `async_list_discoverable_sensors`, `async_assign_sensor`, `async_update_sensor`, `async_unassign_sensor` |
| Users | `async_list_users` (`ha_person_id=` filter), `async_create_user` (`code` optional; guest expiry / `guest_zone_id`, `ha_person_id`, `ha_user_id`), `async_update_user`, `async_delete_user` |
| Codes (write-only) | `async_set_user_code`, `async_clear_user_code`; users expose only `hasCode` |
| Lockout policy | `async_get_lockout_policy`, `async_update_lockout_policy` |
| Events | `async_get_events` |
| HA links | `async_create_ha_link`, `async_delete_ha_link` |
| Keypads | `async_list_keypads`, `async_chime_keypad` |
| Push channel | `async_stream_events` (sends keepalive pings, drops `pong`s; reconnect policy is the caller's) |

Response shapes are available as `TypedDict`s in `zwave_alarm_client.models`.

## Errors

All derive from `ZwaveAlarmError`: `CannotConnect` (unreachable, timeout, 5xx; `ServiceUnavailable` for 503), `InvalidAuth` (401), `Forbidden` (403), `NotFound` (404), `BadRequest` (400, message names the field), `Conflict` (409; `CommandRejected` for a lost arm/disarm race, `ZoneNotEmpty`, `ZoneInUse`, `CodeInUse`), `AccountLocked` (423), `TooManyRequests` (429, `.retry_after`).

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `fix` releases a patch, `feat` a minor, `BREAKING CHANGE`/`!` a major. Releases are tagged and published to PyPI from `main`.
