"""Explain the effective blockers, including expiry and retry exhaustion."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from custom_components.smart_presence_notify.const import MAX_DELIVERY_ATTEMPTS, Priority
from custom_components.smart_presence_notify.models import CoordinatorData, PendingNotification
from custom_components.smart_presence_notify.queue_status import explain_queue_item, queue_reason


def test_queue_blockers_and_priority():
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    item = PendingNotification("one", "Title", "Body", Priority.NORMAL, now, None, {})
    away = CoordinatorData([item], None, False, [])
    home = replace(away, someone_home=True, home_persons=["person.mario"])
    assert queue_reason(item, away, now) == "waiting_for_presence"
    assert queue_reason(item, home, now) == "pending"
    retry = replace(item, attempts=1, retry_at=now + timedelta(seconds=30))
    assert queue_reason(retry, away, now) == "waiting_for_presence"
    assert queue_reason(retry, home, now) == "retry_scheduled"
    assert queue_reason(replace(retry, requires_presence=False), away, now) == "retry_scheduled"
    exhausted = replace(retry, attempts=MAX_DELIVERY_ATTEMPTS)
    assert queue_reason(exhausted, away, now) == "retries_exhausted"
    expired = replace(exhausted, expires_at=now)
    assert queue_reason(expired, away, now) == "expiry_pending"
    fallback = replace(item, expired=True, requires_presence=False, expires_at=now)
    assert queue_reason(fallback, away, now) == "pending"
    assert explain_queue_item(fallback, away, now, "unknown")["fallback_delivery"]
    assert "return home" in explain_queue_item(item, away, now, "unknown")["explanation"]
