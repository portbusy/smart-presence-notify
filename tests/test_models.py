"""Tests for data models."""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.smart_presence_notify.models import (
    CoordinatorData,
    NotificationRecord,
    PendingNotification,
)


def test_pending_notification_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    expires = datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="abc-123",
        title="Test",
        message="Hello",
        priority="normal",
        created_at=now,
        expires_at=expires,
        extra_data={"push": {"sound": "default"}},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.id == "abc-123"
    assert restored.title == "Test"
    assert restored.priority == "normal"
    assert restored.created_at == now
    assert restored.expires_at == expires
    assert restored.extra_data == {"push": {"sound": "default"}}


def test_pending_notification_no_expiry_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="xyz",
        title="T",
        message="M",
        priority="high",
        created_at=now,
        expires_at=None,
        extra_data={},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.expires_at is None
