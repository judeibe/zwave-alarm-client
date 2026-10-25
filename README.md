# zwave-alarm-client

Async Python client (aiohttp) for the REST API of the [Z-Wave Alarm service](https://github.com/judeibe/zwave_alarm). Used by the [Home Assistant integration](https://github.com/judeibe/ha-zwave-alarm); contains no Home Assistant code.

```python
import aiohttp
from zwave_alarm_client import async_get_panel_state, async_stream_events, InvalidAuth, CannotConnect

async with aiohttp.ClientSession() as session:
    panel = await async_get_panel_state(session, "192.168.1.50", 3000, None)

    async for event in async_stream_events(session, "192.168.1.50", 3000, None):
        ...  # first event is a full `snapshot`, then `panel.changed`, `sensor.changed`, ...
```

Every call takes `(session, host, port, token, ...)`; `token` is optional: pass `None` (no `Authorization` header is sent, so only host and port are needed); a non-empty value is sent as a bearer token. A cookie session from `async_login` also works with `None`. Pass `secure=True` for https/wss.

## Coverage

| Area | Calls |
|---|---|
| Auth | `async_login`, `async_logout` |
| Panel | `async_get_panel_state`, `async_validate_connection`, `async_arm`, `async_disarm` (zone-restricted guests return a panel with `disarmedZoneIds`) |
| Zones & sensors | `async_get_zones`, `async_create_zone`, `async_update_zone`, `async_delete_zone` (`force=`), `async_list_discoverable_sensors`, `async_assign_sensor`, `async_update_sensor` (also `placement`, `alertsOnly`, `armed={home, away}`), `async_unassign_sensor` |
| Users | `async_list_users` (`ha_person_id=` filter), `async_create_user` (`code` optional; guest expiry / `guest_zone_id`, `ha_person_id`, `ha_user_id`), `async_update_user`, `async_delete_user` |
| Codes (write-only) | `async_set_user_code`, `async_clear_user_code`; users expose only `hasCode` |
| Lockout policy | `async_get_lockout_policy`, `async_update_lockout_policy` |
| Modes | `async_get_modes`, `async_update_modes` (per-mode entry/exit delay, 0-180 s, default 60 s; administrator to change) |
| Events | `async_get_events` |
| HA links | `async_create_ha_link`, `async_delete_ha_link` |
| Keypads | `async_list_keypads`, `async_chime_keypad`, `async_get_keypad_settings`, `async_update_keypad_settings` (`requireCodeToArm`; administrator to change) |
| Schlage locks | `async_list_locks`, `async_get_lock`, `async_refresh_lock`, `async_update_lock_settings`, `async_list_lock_users`, `async_set_lock_user_code`, `async_clear_lock_user_code`, `async_get_lock_schedule_slots`, `async_set_lock_schedules_enabled`, `async_get_lock_schedule`, `async_set_lock_schedule`, `async_clear_lock_schedule`, `async_list_discoverable_locks`, `async_enroll_lock`, `async_unenroll_lock`, `async_set_locked`; `lock_capabilities`, `lock_supports_schedule`, `validate_lock_code` (see below) |
| Push channel | `async_stream_events` (sends keepalive pings, drops `pong`s; reconnect policy is the caller's) |

### Schlage locks (BE469 / BE468)

Follows the service's `contracts/locks.md`. Under `/api/v1`; `userId` is 1-30; no endpoint returns a stored code.

| Call | Request |
|---|---|
| `async_list_locks` / `async_get_lock` | `GET /locks` (`{locks}`), `GET /locks/{nodeId}` |
| `async_refresh_lock` | `POST /locks/{nodeId}/refresh`: re-read every parameter and the schedule slot counts |
| `async_update_lock_settings` | `PATCH /locks/{nodeId}/settings`, any non-empty subset of `LockSettingsUpdate`, validated as a whole |
| `async_list_lock_users` | `GET /locks/{nodeId}/users` (`{users: [{userId, status}]}`, status `enabled`/`disabled`/`available`) |
| `async_set_lock_user_code` / `async_clear_lock_user_code` | `PUT` (`{code, status?}`) / `DELETE /locks/{nodeId}/users/{userId}/code` |
| `async_get_lock_schedule_slots` | `GET /locks/{nodeId}/schedules` (`{slots}`) |
| `async_set_lock_schedules_enabled` | `PUT /locks/{nodeId}/users/{userId}/schedules/enabled` with `{enabled}` |
| `async_get_lock_schedule` / `async_set_lock_schedule` / `async_clear_lock_schedule` | `GET` / `PUT` / `DELETE /locks/{nodeId}/users/{userId}/schedules/{weekDay\|yearDay\|dailyRepeating}/{slotId}` |

Create entities from a lock's `supportedSettings`. Any value in `settings` / `diagnostics` is `None` until the lock reports it; BE469-only settings are always `None` on a BE468 and writing one is a `BadRequest`. Failures to reach the lock (`502 lock_unavailable`) raise `LockUnavailable`, a `CannotConnect`.

| Setting | Param | Notes |
|---|---|---|
| `beeper`, `vacationMode`, `lockAndLeave`, `autoLock` | 0x03, 0x04, 0x05, 0x0F | bool (wire 0x00 / 0xFF) |
| `pinLength` | 0x10 | 4-8, default 4; does not rewrite existing codes |
| `alarmMode` | 0x07 | `off`, `alert`, `tamper`, `forced_entry`; BE469 only |
| `alertSensitivity`, `tamperSensitivity`, `kickSensitivity` | 0x08-0x0A | 0 (unsupported), 1 (most), 3 (medium), 5 (least); 2 and 4 undocumented; BE469 only |
| `localControls` | 0x0B | `True` = local control enabled; BE469 only |

Read-only `diagnostics`: `electronicTransitionCount` (0x0C), `mechanicalTransitionCount` (0x0D), `electronicFailedCount` (0x0E), `electronicHighPreloadTransitionCount` (0x11), `bootloaderVersion` (0x12), `userSlotBitField` (0x06, 4 bytes) and `occupiedUserSlots` (that field decoded to slots 1-30). `scheduleSlots` and `userSlotCount` give the per-user schedule slots per kind and the number of user slots.

Schedules: weekdays are numbers 0 (Sunday) to 6 (Saturday); `yearDay` years are two digits (26 = 2026); `dailyRepeating` takes `weekdays`, a start and a duration.

Codes must be 4-8 digits: `async_set_lock_user_code` and `validate_lock_code` raise `BadRequest` locally otherwise, and passing the lock's `settings["pinLength"]` as `pin_length=` requires that exact length. `async_update_lock_settings` checks `pinLength` (4-8) and sensitivities (0-5) before sending.

The stream carries `lock.changed` (`{lock: LockSummary}`) and the snapshot gains `locks`; see `LockChanged`.

**Enrollment.** A lock is only *paired* until an administrator enrolls it. `GET /locks`, the snapshot's `locks` and `lock.changed` carry enrolled locks only, so every `LockSummary` you receive is enrolled (there is no `enrolled` field): create a device from it, and remove the device on `lock.removed` (`{nodeId}`, `LockRemoved`; sent on unenroll and when the node leaves the network). `async_list_discoverable_locks` (`GET /locks/available`, administrators) returns `AvailableLock` (`nodeId`, `model`, `label`, `connectivityStatus`, `secure`) to choose from; never build devices from it. `async_enroll_lock` (`PUT /locks/{nodeId}/enrollment`, returns the `LockSummary`) and `async_unenroll_lock` (`DELETE`) are idempotent and administrator-only. Unenrolling first clears the lock's user codes and schedules, then always unenrolls, and returns `UnenrollResult` (`{nodeId, cleared, failures}`): when `cleared` is `False` (e.g. the lock was unreachable) its codes may still work, so tell the user to clear them at the lock; enrolling a lock included without S0/S2 raises `LockNotSecure` (a `Conflict`, `409 lock_not_secure`): exclude and re-include it securely.

**Lock and unlock.** `LockSummary.locked` is `True` (bolt thrown), `False` (retracted) or `None` (not reported); it also follows keypad, thumb-turn and auto-lock events. `async_set_locked(node_id, locked)` (`PUT /locks/{nodeId}/state`) returns the `LockSummary` as it was when the lock answered, which may still show the old state: wait for `lock.changed`. `502 lock_unavailable` -> `LockUnavailable`.

**Capabilities.** `lock_capabilities(lock)` returns `LockCapabilities`: `secure` (`bool | None`), `userCodes`, `alarmSettings`, `schedules` (`weekDay` / `yearDay` / `dailyRepeating`, each `True`, `False` or `None` = not reported yet) and `userSlots` (from `userSlotCount`). Hide anything `False`; treat `None` as unknown and refresh. `lock_supports_schedule(lock, kind)` is the shortcut. Reading or writing a kind with no slots is `400 schedule_kind_unsupported`, raised as `ScheduleKindUnsupported` (a `BadRequest`). Only for an older service with no `capabilities` are the flags derived from `scheduleSlots` (0 slots = `False`) and `supportedSettings`.

Response shapes are available as `TypedDict`s in `zwave_alarm_client.models`.

## Errors

All derive from `ZwaveAlarmError`: `CannotConnect` (unreachable, timeout, 5xx; `ServiceUnavailable` for 503), `InvalidAuth` (401), `Forbidden` (403), `NotFound` (404), `BadRequest` (400, message names the field), `Conflict` (409; `CommandRejected` for a lost arm/disarm race, `ZoneNotEmpty`, `ZoneInUse`, `CodeInUse`), `AccountLocked` (423), `TooManyRequests` (429, `.retry_after`), `ScheduleKindUnsupported` (400 `schedule_kind_unsupported`, a `BadRequest`), `LockNotSecure` (409 `lock_not_secure`, a `Conflict`), `LockUnavailable` (502 `lock_unavailable`, a `CannotConnect`).

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `fix` releases a patch, `feat` a minor, `BREAKING CHANGE`/`!` a major. Releases are tagged and published to PyPI from `main`.
