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
    sensors: list[Sensor]


class User(TypedDict):
    id: str
    name: str
    role: Role
    guestExpiresAt: int | None
    guestZoneId: str | None
    failedAttemptCount: int
    lockedUntil: int | None
    createdAt: int


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
