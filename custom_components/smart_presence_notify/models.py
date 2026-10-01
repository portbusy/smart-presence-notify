"""Data models for Smart Presence Notify."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

from .const import Priority
from .validation import notification_target

if TYPE_CHECKING:
    from .coordinator import SmartPresenceNotifyCoordinator


@dataclass(frozen=True)
class PendingNotification:
    id: str
    title: str
    message: str
    priority: Priority
    created_at: datetime
    expires_at: datetime | None
    extra_data: dict[str, Any]
    targets: list[str] | None = None
    delivered_targets: list[str] = field(default_factory=list)
    requires_presence: bool = True
    expired: bool = False
    attempts: int = 0
    retry_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "extra_data": self.extra_data,
            "targets": self.targets,
            "delivered_targets": self.delivered_targets,
            "requires_presence": self.requires_presence,
            "expired": self.expired,
            "attempts": self.attempts,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingNotification:
        if not isinstance(data, dict):
            raise ValueError("Notification must be an object")
        for key in ("id", "title", "message"):
            if not isinstance(data[key], str) or (key == "id" and not data[key]):
                raise ValueError(f"Invalid notification {key}")
        extra = data.get("extra_data", {})
        if not isinstance(extra, dict):
            raise ValueError("Invalid notification data")
        _validate_json(extra)
        targets = _targets(data.get("targets"))
        delivered = _targets(data.get("delivered_targets", []))
        attempts = data.get("attempts", 0)
        if type(attempts) is not int or attempts < 0:
            raise ValueError("Invalid delivery attempt count")
        for key in ("requires_presence", "expired"):
            if key in data and not isinstance(data[key], bool):
                raise ValueError(f"Invalid notification {key}")
        return cls(
            id=data["id"],
            title=data["title"],
            message=data["message"],
            priority=Priority(data["priority"]),
            created_at=_date(data["created_at"]),
            expires_at=(_date(data["expires_at"]) if data.get("expires_at") else None),
            extra_data=extra,
            targets=targets,
            delivered_targets=delivered or [],
            requires_presence=data.get("requires_presence", True),
            expired=data.get("expired", False),
            attempts=attempts,
            retry_at=_date(data["retry_at"]) if data.get("retry_at") else None,
        )


@dataclass(frozen=True)
class NotificationRecord:
    title: str
    sent_at: datetime
    recipients: list[str]
    priority: Priority


@dataclass(frozen=True)
class CoordinatorData:
    queue: list[PendingNotification]
    last_sent: NotificationRecord | None
    someone_home: bool
    home_persons: list[str]
    last_error: str | None = None
    failed_recipients: list[str] = field(default_factory=list)


@dataclass
class ResponseToken:
    response_id: str
    expires_at: datetime | None = None
    sent: bool = False
    answered: bool = False


@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator


type SNPConfigEntry = ConfigEntry[SNPRuntimeData]


def _date(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Notification timestamps must include a time zone")
    return result


def _targets(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("Notification targets must be a list")
    return list(dict.fromkeys(notification_target(target) for target in value))


def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json(item)
        return
    raise ValueError("Notification data must contain JSON values")
