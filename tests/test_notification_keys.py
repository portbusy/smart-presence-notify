"""Stable cancellation keys across persistence, retries and service calls."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.smart_presence_notify.coordinator import (
    SmartPresenceNotifyCoordinator,
)
from custom_components.smart_presence_notify.models import PendingNotification
from tests.test_reliability import make_coordinator


async def test_cancel_key_after_restart_leaves_unrelated_messages(hass):
    coord = await make_coordinator(hass, queue_timeout_minutes=10)
    for key in ("garage", "garage", "Garage", None):
        await coord.async_send_notification("Same title", "Body", notification_key=key)
    entry = coord.config_entry
    await coord.async_shutdown()
    restored = SmartPresenceNotifyCoordinator(hass, entry)
    await restored.async_initialize()
    await hass.async_block_till_done()
    assert [item.notification_key for item in restored.data.queue] == [
        "garage", "garage", "Garage", None
    ]
    await restored.async_cancel_pending(notification_key="garage")
    remaining = list(restored.data.queue)
    assert [item.notification_key for item in remaining] == ["Garage", None]
    assert await restored._store.async_load() == remaining
    assert set(restored._timeout_unsubs) == {item.id for item in remaining}
    await restored.async_cancel_pending(notification_key="garage")
    assert restored.data.queue == remaining
    await restored.async_shutdown()


async def test_cancel_key_removes_failed_delivery_without_recalling_success(hass):
    coord = await make_coordinator(hass, target_mode="caller_decides")
    deliver = AsyncMock()
    hass.services.async_register("notify", "working", deliver)
    await coord.async_send_notification(
        "Garage", "Open", targets=["notify.working", "notify.missing"],
        notification_key="garage",
    )
    await coord.async_send_pending(coord.data.queue[0].id)
    assert coord.data.queue[0].targets == ["notify.missing"]
    await coord.async_cancel_pending(notification_key="garage")
    assert not coord.data.queue
    assert not coord._timeout_unsubs
    assert coord.data.last_error is None
    deliver.assert_awaited_once()
    await coord.async_shutdown()


async def test_cancel_key_busy_and_storage_failure_are_atomic(hass):
    coord = await make_coordinator(hass)
    for _ in range(2):
        await coord.async_send_notification("Garage", "Open", notification_key="garage")
    items = list(coord.data.queue)
    lock = coord._item_locks.setdefault(items[1].id, asyncio.Lock())
    async with lock:
        with pytest.raises(ServiceValidationError, match="processed"):
            await coord.async_cancel_pending(notification_key="garage")
    assert coord.data.queue == items
    with patch.object(coord._store, "async_save", side_effect=OSError("disk full")):
        with pytest.raises(HomeAssistantError, match="persist"):
            await coord.async_cancel_pending(notification_key="garage")
    assert coord.data.queue == items
    await coord.async_shutdown()


async def test_key_service_roundtrip_and_invalid_selectors(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coord = mock_config_entry.runtime_data.coordinator
    await hass.services.async_call(
        "smart_presence_notify", "send",
        {"title": "Garage", "message": "Open", "notification_key": "garage"},
        blocking=True,
    )
    assert coord.data.queue[0].notification_key == "garage"
    for data in (
        {},
        {"notification_id": coord.data.queue[0].id, "notification_key": "garage"},
        {"notification_key": ""},
        {"notification_key": "*"},
        {"notification_key": "a" * 65},
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                "smart_presence_notify", "cancel_pending", data, blocking=True
            )
        assert len(coord.data.queue) == 1
    await hass.services.async_call(
        "smart_presence_notify", "cancel_pending",
        {"notification_key": "garage"}, blocking=True,
    )
    assert not coord.data.queue


async def test_old_storage_and_invalid_key_validation(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("Old", "Body")
    serialized = coord.data.queue[0].to_dict()
    serialized.pop("notification_key")
    assert PendingNotification.from_dict(serialized).notification_key is None
    for key in ("", " ", "*", "a" * 65, 12):
        with pytest.raises(ServiceValidationError):
            await coord.async_send_notification("Invalid", "Body", notification_key=key)
        with pytest.raises(vol.Invalid):
            PendingNotification.from_dict({**serialized, "notification_key": key})
    assert len(coord.data.queue) == 1
    await coord.async_shutdown()
