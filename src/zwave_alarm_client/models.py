"""Typed shapes of the JSON documents exchanged with the service (contracts/rest-api.md, data-model.md)."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

PanelMode = Literal["disarmed", "arming", "armed_away", "armed_home", "alarm_pending", "alarm_triggered"]
ArmMode = Literal["armed_away", "armed_home"]
Role = Literal["administrator", "member", "guest"]
SensorCategory = Literal["intrusion", "life-safety"]


class Panel(TypedDict):
    mode: PanelMode
    pendingDelayEndsAt: int | None
    triggeredBy: str | None
    armedMode: ArmMode | None
    disarmedZoneIds: list[str]


class Sensor(TypedDict):
    id: str
    zwaveNodeId: int
    zoneId: str
    name: str
    category: SensorCategory
    currentState: Literal["normal", "breached"]
    batteryLevel: int | None
    connectivityStatus: Literal["online", "offline"]
    updatedAt: int


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
    haPersonId: NotRequired[str | None]
    haUserId: NotRequired[str | None]


class UserUpdate(TypedDict, total=False):
    name: str
    role: Role
    haPersonId: str | None
    haUserId: str | None
    guestExpiresAt: str | int | None
    guestZoneId: str | None


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


class KeypadSettingsUpdate(TypedDict, total=False):
    """Any non-empty subset of `KeypadSettings` for `PATCH /keypad-settings`."""

    requireCodeToArm: bool


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
