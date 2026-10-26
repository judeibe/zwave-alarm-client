"""Typed shapes of the JSON documents exchanged with the service (contracts/rest-api.md, data-model.md)."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

PanelMode = Literal["disarmed", "arming", "armed_away", "armed_home", "alarm_pending", "alarm_triggered"]
ArmMode = Literal["armed_away", "armed_home"]
Role = Literal["administrator", "member", "guest", "installer"]  # installer access expires after 48 h
SensorCategory = Literal["intrusion", "life-safety"]
Source = Literal["app", "keypad", "lock", "schedule", "alexa"]
# The service reserves "tampered", "not_set_up" and "updating" for later; accept them already.
FaultedReason = Literal["open", "offline", "tampered", "not_set_up", "updating"]
AlarmEventType = Literal["BURGLARY", "SMOKE", "CO", "PANIC", "FIRE_MEDICAL", "DURESS", "SOS", "FLOOD_FREEZE"]
EmergencyService = Literal["police", "fire", "medical"]
SirenState = Literal["none", "sounding", "silenced", "timed_out", "stopped"]
DispatchState = Literal["none", "held", "queued", "cancelled"]
PanicType = Literal["PANIC", "FIRE", "MEDICAL", "SOS"]
AlarmKind = Literal["SMOKE", "CO", "FLOOD_FREEZE"]  # life-safety sensors only
SirenKind = Literal["BASE", "DOME", "OUTDOOR"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SecurityEventType = Literal[
    "armed", "disarmed", "breach", "alarm_triggered", "alarm_cleared", "device_fault", "lockout", "guest_code_used",
    "bypassed", "tamper", "tamper_cleared", "siren_silenced",
    "code_added", "code_changed", "code_removed", "duress_code_set", "duress_code_removed",
    "guest_schedule_added", "guest_schedule_updated", "guest_schedule_removed",
    "mode_schedule_added", "mode_schedule_updated", "mode_schedule_removed",
    "mode_schedule_applied", "mode_schedule_skipped",
    "lock_locked", "lock_unlocked", "lock_jammed", "lock_offline", "lock_online",  # deviceId "node-<n>"
]  # keypad kinds arrive with service phase 6b
LockAction = Literal["lock", "unlock"]
LockModeKey = Literal["disarmed", "armed_home", "armed_away"]
LockSyncStatus = Literal["synced", "failed"]
LockEventKind = Literal["locked", "unlocked", "armed", "disarmed", "jammed"]
LockMethod = Literal["keypad", "one_touch", "manual", "app", "auto", "unknown"]
ChirpTone = Literal["none", "double_beep", "guitar", "wind_chimes", "bing_bong", "doorbell"]
KEYPAD_VOLUME_RANGE = range(0, 100)  # whole levels, 0-99
ModeScheduleMode = Literal["disarmed", "armed_home", "armed_away"]
Placement = Literal["MAIN_DOOR", "SECONDARY_DOOR", "WINDOW", "ENTRYWAY", "ROOM", "GLASS_BREAK"]
MODE_DELAY_RANGE = range(0, 181)  # whole seconds, per armed mode


class AlarmEvent(TypedDict):
    """An alarm event (`POST /panel/panic`, `GET /alarm-events`, the `alarm.event` stream message). Times are epoch ms."""

    id: str
    type: AlarmEventType
    service: EmergencyService | None
    triggerDeviceId: str | None
    startedAt: int
    sirenState: SirenState
    dispatchState: DispatchState
    cancelledAt: int | None
    endedAt: int | None  # None while the event is open
    details: str | None


class Siren(TypedDict):
    """A Z-Wave siren node enrolled with the service (`GET /sirens`, `siren.changed`). `createdAt` is epoch ms."""

    nodeId: int
    kind: SirenKind
    name: str
    durationSec: int  # fixed at 600 for BASE and DOME; 60-600 (default 180) for OUTDOOR
    createdAt: int


class SilenceResult(TypedDict):
    silenced: list[AlarmEvent]


class FaultedSensor(TypedDict):
    """One entry of `NeedsBypass.faulted`."""

    sensorId: str
    name: str
    zoneId: str
    reason: FaultedReason


class ModeDelays(TypedDict):
    entryDelaySec: int
    exitDelaySec: int
    chirpsEnabled: NotRequired[bool]  # sensor chirps in this mode; absent before service 3.8


class ModeChirps(TypedDict):
    """The `disarmed` mode has no delays, only the chirp toggle."""

    chirpsEnabled: bool


class ModeConfig(TypedDict):
    """`GET /modes`: delays and chirps for each armed mode, and the disarmed chirp toggle."""

    armed_home: ModeDelays
    armed_away: ModeDelays
    disarmed: NotRequired[ModeChirps]  # absent before service 3.8


class ModeDelaysUpdate(TypedDict, total=False):
    entryDelaySec: int
    exitDelaySec: int
    chirpsEnabled: bool


class ModeConfigUpdate(TypedDict, total=False):
    armed_home: ModeDelaysUpdate
    armed_away: ModeDelaysUpdate
    disarmed: ModeChirps


class Panel(TypedDict):
    mode: PanelMode
    pendingDelayEndsAt: int | None
    triggeredBy: str | None
    armedMode: ArmMode | None
    disarmedZoneIds: list[str]
    exitEndsAt: NotRequired[int | None]  # epoch ms while `arming`; absent before service 3.1
    entryEndsAt: NotRequired[int | None]  # epoch ms while `alarm_pending`
    bypassedDeviceIds: NotRequired[list[str]]  # sensors bypassed for the current arm session
    modes: NotRequired[ModeConfig]  # on `GET /panel`, `panel.changed` and the snapshot; absent before service 3.0


class Sensor(TypedDict):
    id: str
    zwaveNodeId: int
    zoneId: str
    name: str
    category: SensorCategory
    currentState: Literal["normal", "breached"]
    batteryLevel: int | None
    connectivityStatus: Literal["online", "offline"]
    placement: Placement | None  # None for life-safety sensors
    armedHome: bool
    armedAway: bool
    alertsOnly: bool
    alarmKind: NotRequired[AlarmKind | None]  # None on intrusion sensors; absent before service 3.2
    chirpTone: NotRequired[ChirpTone | None]  # None on life-safety sensors; absent before service 3.8
    tampered: NotRequired[bool]  # cover removed; absent before service 3.3
    updatedAt: int


class ArmedFlags(TypedDict, total=False):
    home: bool
    away: bool


class Zone(TypedDict):
    id: str
    name: str
    description: NotRequired[str | None]  # config-panel contract; absent on older services
    sensors: list[Sensor]


class ZoneUpdate(TypedDict, total=False):
    name: str
    description: str | None


class SensorUpdate(TypedDict, total=False):
    name: str
    category: SensorCategory
    zoneId: str
    placement: Placement
    alertsOnly: bool
    alarmKind: AlarmKind
    chirpTone: ChirpTone
    armed: ArmedFlags


class DiscoverableSensor(TypedDict):
    """An unassigned zwave-js node from `GET /sensors/discoverable`."""

    zwaveNodeId: int
    name: str | None
    manufacturer: str | None
    product: str | None
    suggestedCategory: SensorCategory | None
    status: Literal["alive", "dead", "asleep"]


class User(TypedDict):
    id: str
    name: str
    role: Role
    guestExpiresAt: int | None
    guestZoneId: str | None
    failedAttemptCount: int
    lockedUntil: int | None
    createdAt: int
    # Config-panel contract fields; absent on older services. A code is never returned, only whether one is set.
    hasCode: NotRequired[bool]
    lockSlots: NotRequired[list[LockSlot]]  # absent before service 3.7
    lockSync: NotRequired[list[LockSync]]  # only on the `POST /users` response when the user got a code
    hasDuressCode: NotRequired[bool]  # only an administrator can have one; absent before service 3.4
    haPersonId: NotRequired[str | None]
    haUserId: NotRequired[str | None]


class UserUpdate(TypedDict, total=False):
    name: str
    role: Role
    haPersonId: str | None
    haUserId: str | None
    guestExpiresAt: str | int | None
    guestZoneId: str | None


class GuestSchedule(TypedDict):
    """When a guest's code works at the keypad (`/users/{userId}/schedules`); locks do not enforce it."""

    id: str
    userId: str
    name: str
    days: list[Weekday]
    allDay: bool
    start: str | None  # "HH:MM"; None when allDay. An end at or before start is an overnight window.
    end: str | None
    timeZone: str | None  # IANA name; None means the service's own zone
    createdAt: int


class ModeSchedule(TypedDict):
    """A scheduled mode change (`/mode-schedules`); the service applies it with source `schedule`."""

    id: str
    name: str
    mode: ModeScheduleMode
    time: str  # "HH:MM", 24 h, in timeZone
    days: list[Weekday]
    enabled: bool
    timeZone: str | None  # IANA name; None means the service's own zone
    createdAt: int
    lastRunAt: int | None


class LockoutPolicy(TypedDict):
    failedAttemptThreshold: int
    cooldownSeconds: int
    onThresholdExceeded: Literal["lockout", "trigger_alarm"]


class LockoutPolicyUpdate(TypedDict, total=False):
    failedAttemptThreshold: int
    cooldownSeconds: int
    onThresholdExceeded: Literal["lockout", "trigger_alarm"]


class SecurityEvent(TypedDict):
    id: str
    type: str
    source: str
    sourceUserId: str | None
    relatedZoneId: str | None
    relatedSensorId: str | None
    details: str | None
    occurredAt: int
    # Absent before service 3.6. `type` is a SecurityEventType today but stays `str` so newer kinds still parse.
    actor: NotRequired[str | None]
    deviceId: NotRequired[str | None]
    deviceName: NotRequired[str | None]


class HaLink(TypedDict):
    id: str
    label: str
    connectionStatus: Literal["connected", "disconnected"]
    lastSeenAt: int | None
    createdAt: int
    token: NotRequired[str]  # plaintext, present only in the creation response


class KeypadSummary(TypedDict):
    """A keypad as listed by `GET /keypads` and carried by `keypad.changed` and the snapshot's `keypads`.

    `capabilities` is open-ended (known: `arm_disarm`, `emergency`, `indicators`, `chime`): ignore values you do not know.
    `chimeSounds` is empty without the `chime` capability. The service may add fields; ignore those too.
    """

    nodeId: int
    adapterId: str
    label: str
    capabilities: list[str]
    chimeSounds: list[str]
    connectivityStatus: Literal["online", "offline"]
    batteryLevel: int | None


class KeypadSettings(TypedDict):
    """`GET /keypad-settings`, also the snapshot's `keypadSettings` and a `keypad.settings` message's `settings`."""

    requireCodeToArm: bool  # arming from a keypad needs a valid user code; disarming always does
    volume: NotRequired[int]  # 0-99, chirps, delay tones and announcements (not the siren); absent before service 3.8


class KeypadSettingsUpdate(TypedDict, total=False):
    """Any non-empty subset of `KeypadSettings` for `PATCH /keypad-settings`."""

    requireCodeToArm: bool
    volume: int


class KeypadInput(TypedDict):
    """The `input` of a `keypad.event`; never carries the code.

    `kind` is open-ended (known: `code_entered`, `arm_away`, `arm_home`, `disarm`, `cancel`, `emergency`): ignore
    kinds you do not know. `emergency` is present only when `kind` is `emergency`.
    """

    kind: str
    emergency: NotRequired[Literal["fire", "police", "medical"]]


class KeypadEvent(TypedDict):
    """A `keypad.event` stream message: a button press on a keypad."""

    type: Literal["keypad.event"]
    nodeId: int
    adapterId: str
    input: KeypadInput


class KeypadChanged(TypedDict):
    """A `keypad.changed` stream message: a keypad was discovered or its state (connectivity, battery, ...) changed."""

    type: Literal["keypad.changed"]
    keypad: KeypadSummary


class KeypadSettingsChanged(TypedDict):
    """A `keypad.settings` stream message: an administrator changed the keypad settings."""

    type: Literal["keypad.settings"]
    settings: KeypadSettings


# --- Schlage locks (BE469 / BE468; contracts/locks.md) -----------------------

LockModel = Literal["BE469", "BE468"]
AlarmMode = Literal["off", "alert", "tamper", "forced_entry"]
ScheduleKind = Literal["weekDay", "yearDay", "dailyRepeating"]
LockUserStatus = Literal["enabled", "disabled", "available"]
# 0 = not supported, 1 = most sensitive, 3 = medium, 5 = least; 2 and 4 are undocumented intermediates.
Sensitivity = Literal[0, 1, 2, 3, 4, 5]


class LockSettings(TypedDict):
    """Writable parameters 0x03-0x05, 0x07-0x0B, 0x0F and 0x10; any value is `None` until the lock reports it.

    The BE469-only settings are always `None` on a BE468 (and absent from its `supportedSettings`).
    """

    beeper: bool | None  # 0x03
    vacationMode: bool | None  # 0x04
    lockAndLeave: bool | None  # 0x05
    autoLock: bool | None  # 0x0F
    pinLength: int | None  # 0x10, 4-8, default 4
    alarmMode: AlarmMode | None  # 0x07, BE469 only
    alertSensitivity: Sensitivity | None  # 0x08, BE469 only
    tamperSensitivity: Sensitivity | None  # 0x09, BE469 only
    kickSensitivity: Sensitivity | None  # 0x0A, BE469 only
    localControls: bool | None  # 0x0B, BE469 only; True = local control enabled


class LockSettingsUpdate(TypedDict, total=False):
    """Any non-empty subset of the writable `LockSettings` for `PATCH /locks/{nodeId}/settings`."""

    beeper: bool
    vacationMode: bool
    lockAndLeave: bool
    autoLock: bool
    pinLength: int
    alarmMode: AlarmMode
    alertSensitivity: Sensitivity
    tamperSensitivity: Sensitivity
    kickSensitivity: Sensitivity
    localControls: bool


class LockDiagnostics(TypedDict):
    """Read-only parameters 0x06, 0x0C-0x0E, 0x11 and 0x12; any value is `None` until the lock reports it."""

    electronicTransitionCount: int | None  # 0x0C
    mechanicalTransitionCount: int | None  # 0x0D
    electronicFailedCount: int | None  # 0x0E
    electronicHighPreloadTransitionCount: int | None  # 0x11, a subset of 0x0C
    bootloaderVersion: int | None  # 0x12
    userSlotBitField: list[int] | None  # 0x06: 4 bytes, bytes 1-3 = slots 1-24, byte 4 = slots 25-30, LSB lowest
    occupiedUserSlots: list[int] | None  # 0x06 decoded to slot numbers 1-30


class LockScheduleSlots(TypedDict):
    """Schedule Entry Lock slots available per user, for each schedule kind."""

    weekDay: int
    yearDay: int
    dailyRepeating: int


class LockModeSettings(TypedDict):
    """What an enrolled lock does with the alarm (`/locks/{nodeId}/mode-settings`); everything is off by default."""

    armOnLockWithCode: bool  # locking with an app-created code arms away
    armOnOneTouch: bool  # the one-touch button arms away
    disarmOnUnlock: bool  # unlocking with an app-created code disarms
    actions: dict[LockModeKey, LockAction | None]  # lock or unlock when the panel enters each mode


class LockModeSettingsUpdate(TypedDict, total=False):
    armOnLockWithCode: bool
    armOnOneTouch: bool
    disarmOnUnlock: bool
    actions: dict[LockModeKey, LockAction | None]  # partial; merges per mode


class LockSync(TypedDict):
    """One lock's result when a user's code is pushed to, or cleared from, an enrolled lock."""

    nodeId: int
    slot: int
    status: LockSyncStatus
    message: NotRequired[str]


class LockSlot(TypedDict):
    nodeId: int
    slot: int
    status: LockSyncStatus


class LockEvent(TypedDict):
    """The `lock.event` stream message."""

    type: Literal["lock.event"]
    nodeId: int
    kind: LockEventKind
    userId: str | None  # the app user behind the code, when it is one of ours
    method: LockMethod


class LockSummary(TypedDict):
    """A lock as listed by `GET /locks` and carried by `lock.changed` and the snapshot's `locks`.

    Create entities from `supportedSettings`, not from the model. The service may add fields; ignore those.
    """

    nodeId: int
    model: LockModel
    label: str
    connectivityStatus: Literal["online", "offline"]
    batteryLevel: int | None
    supportedSettings: list[str]
    settings: LockSettings
    diagnostics: LockDiagnostics
    scheduleSlots: LockScheduleSlots
    userSlotCount: int
    locked: NotRequired[bool | None]  # True = bolt thrown, False = retracted, None = not reported yet
    capabilities: NotRequired[LockCapabilities]  # absent on services that predate it; use `lock_capabilities()`
    modeSettings: NotRequired[LockModeSettings]  # absent before service 3.7


class LockScheduleCapabilities(TypedDict):
    """Per schedule kind: `True` supported, `False` the lock has no slots (writing is `400`), `None` not reported yet."""

    weekDay: bool | None
    yearDay: bool | None
    dailyRepeating: bool | None


class LockCapabilities(TypedDict):
    """What a lock supports, so UIs can hide controls it lacks (the BE469 commonly reports no daily-repeating slots).

    `secure` is `None` while unknown; user codes and schedules need S0/S2. `userSlots` is added by
    `lock_capabilities()` from `userSlotCount`; the service does not send it inside `capabilities`.
    """

    secure: bool | None
    userCodes: bool
    schedules: LockScheduleCapabilities
    alarmSettings: bool  # BE469 alarm mode / sensitivities / local controls
    userSlots: NotRequired[int]


class AvailableLock(TypedDict):
    """A lock that is paired but not enrolled (`GET /locks/available`, administrators only). Not a device source."""

    nodeId: int
    model: LockModel
    label: str
    connectivityStatus: Literal["online", "offline"]
    secure: bool | None


class LockUser(TypedDict):
    """One user slot (1-30) from `GET /locks/{nodeId}/users`; the code itself is never returned."""

    userId: int
    status: LockUserStatus


class LockUserCode(TypedDict):
    """Result of setting a code."""

    userId: int
    status: Literal["enabled", "disabled"]


class WeekDaySchedule(TypedDict):
    """`weekday` is 0 (Sunday) to 6 (Saturday); stop is after start."""

    weekday: int
    startHour: int
    startMinute: int
    stopHour: int
    stopMinute: int


class YearDaySchedule(TypedDict):
    """A date range; years are two digits (26 = 2026), stop is after start."""

    startYear: int
    startMonth: int
    startDay: int
    startHour: int
    startMinute: int
    stopYear: int
    stopMonth: int
    stopDay: int
    stopHour: int
    stopMinute: int


class DailyRepeatingSchedule(TypedDict):
    """`weekdays` are numbers 0 (Sunday) to 6 (Saturday)."""

    weekdays: list[int]
    startHour: int
    startMinute: int
    durationHour: int
    durationMinute: int


class LockSchedule(TypedDict):
    """`GET /locks/{nodeId}/users/{userId}/schedules/{kind}/{slotId}`; `schedule` is `None` for an empty slot."""

    kind: ScheduleKind
    userId: int
    slotId: int
    schedule: WeekDaySchedule | YearDaySchedule | DailyRepeatingSchedule | None


class LockChanged(TypedDict):
    """A `lock.changed` stream message: a lock appeared or any of its state changed (also when the lock reports on its own)."""

    type: Literal["lock.changed"]
    lock: LockSummary


class LockRemoved(TypedDict):
    """A `lock.removed` stream message: the lock was unenrolled or left the network; remove its device and entities."""

    type: Literal["lock.removed"]
    nodeId: int


class UnenrollResult(TypedDict):
    """Result of `DELETE /locks/{nodeId}/enrollment`. The lock is always unenrolled, even when `cleared` is `False`.

    When `cleared` is `False` the lock's codes may still work: tell the user to clear them at the lock. `failures`
    holds one human-readable line per step that failed (a single entry when the lock was unreachable).
    """

    nodeId: int
    cleared: bool
    failures: list[str]
