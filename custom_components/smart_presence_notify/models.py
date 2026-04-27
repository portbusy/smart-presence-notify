"""Data models for Smart Presence Notify."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .coordinator import SmartPresenceNotifyCoordinator


@dataclass
class PendingNotification:
    id: str
    title: str
    message: str
    priority: Literal["normal", "high"]
    created_at: datetime
    expires_at: datetime | None
    extra_data: dict

    def to_dict(self) -> dict:
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
    def from_dict(cls, data: dict) -> PendingNotification:
        return cls(
            id=data["id"],
            title=data["title"],
            message=data["message"],
            priority=data["priority"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            extra_data=data.get("extra_data", {}),
        )


@dataclass
class NotificationRecord:
    title: str
    sent_at: datetime
    recipients: list[str]
    priority: Literal["normal", "high"]


@dataclass
class CoordinatorData:
    queue: list[PendingNotification]
    last_sent: NotificationRecord | None
    someone_home: bool
    home_persons: list[str]


@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator
