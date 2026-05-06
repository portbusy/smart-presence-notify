"""Data models for Smart Presence Notify."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .const import Priority

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "extra_data": self.extra_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingNotification:
        return cls(
            id=data["id"],
            title=data["title"],
            message=data["message"],
            priority=Priority(data["priority"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            extra_data=data.get("extra_data", {}),
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


@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator
