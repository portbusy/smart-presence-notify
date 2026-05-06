"""Tests for data models."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from custom_components.smart_presence_notify.const import Priority
from custom_components.smart_presence_notify.models import PendingNotification


def test_pending_notification_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    expires = datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="abc-123",
        title="Test",
        message="Hello",
        priority=Priority.NORMAL,
        created_at=now,
        expires_at=expires,
        extra_data={"push": {"sound": "default"}},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.id == "abc-123"
    assert restored.title == "Test"
    assert restored.priority == Priority.NORMAL
    assert restored.priority == "normal"  # StrEnum: value equality with str
    assert restored.created_at == now
    assert restored.expires_at == expires
    assert restored.extra_data == {"push": {"sound": "default"}}


def test_pending_notification_no_expiry_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="xyz",
        title="T",
        message="M",
        priority=Priority.HIGH,
        created_at=now,
        expires_at=None,
        extra_data={},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.expires_at is None


def test_pending_notification_is_frozen():
    notif = PendingNotification(
        id="x",
        title="T",
        message="M",
        priority=Priority.NORMAL,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=None,
        extra_data={},
    )
    with pytest.raises(FrozenInstanceError):
        notif.title = "mutated"  # type: ignore[misc]
