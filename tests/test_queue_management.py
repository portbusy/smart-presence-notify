"""Queue controls preserve persistence and per-destination delivery checkpoints."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from tests.test_reliability import make_coordinator


async def test_cancel_persists_removal_and_cancels_timer(hass):
    coord = await make_coordinator(hass, queue_timeout_minutes=10)
    await coord.async_send_notification("First", "Body")
    await coord.async_send_notification("Second", "Body")
    first, second = coord.data.queue
    await coord.async_cancel_pending(first.id)
    assert coord.data.queue == [second]
    assert first.id not in coord._timeout_unsubs
    assert [item.id for item in await coord._store.async_load()] == [second.id]
    await coord.async_shutdown()


@pytest.mark.parametrize("clear_all", [False, True])
async def test_failed_cancel_save_keeps_queue_and_timer(hass, clear_all):
    coord = await make_coordinator(hass, queue_timeout_minutes=10)
    await coord.async_send_notification("First", "Body")
    item = coord.data.queue[0]
    with patch.object(coord._store, "async_save", side_effect=OSError("disk full")):
        with pytest.raises(HomeAssistantError, match="persist"):
            await coord.async_cancel_pending(None if clear_all else item.id)
    assert coord.data.queue == [item]
    assert item.id in coord._timeout_unsubs
    await coord.async_shutdown()


async def test_clear_rejects_busy_queue_without_partial_removal(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("First", "Body")
    await coord.async_send_notification("Second", "Body")
    items = list(coord.data.queue)
    lock = coord._item_locks.setdefault(items[1].id, asyncio.Lock())
    async with lock:
        with pytest.raises(ServiceValidationError, match="processed"):
            await coord.async_cancel_pending()
    assert coord.data.queue == items
    await coord.async_cancel_pending()
    assert not coord.data.queue
    assert not await coord._store.async_load()
    await coord.async_shutdown()


async def test_send_pending_requires_destination_when_away(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("First", "Body")
    item = coord.data.queue[0]
    with pytest.raises(ServiceValidationError, match="specify targets"):
        await coord.async_send_pending(item.id)
    assert coord.data.queue == [item]
    deliver = AsyncMock()
    hass.services.async_register("notify", "phone", deliver)
    await coord.async_send_pending(item.id, ["notify.phone"])
    assert deliver.call_count == 1
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_send_pending_only_retries_failed_destinations(hass):
    coord = await make_coordinator(hass, target_mode="caller_decides")
    working = AsyncMock()
    hass.services.async_register("notify", "working", working)
    await coord.async_send_notification(
        "First", "Body", targets=["notify.working", "notify.missing"]
    )
    item_id = coord.data.queue[0].id
    await coord.async_send_pending(item_id)
    assert working.call_count == 1
    pending = coord.data.queue[0]
    assert pending.targets == ["notify.missing"]
    assert not pending.requires_presence
    assert pending.retry_at is not None
    with pytest.raises(ServiceValidationError, match="already assigned"):
        await coord.async_send_pending(item_id, ["notify.working"])
    recovered = AsyncMock()
    hass.services.async_register("notify", "missing", recovered)
    await coord.async_send_pending(item_id)
    assert working.call_count == 1
    assert recovered.call_count == 1
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_send_pending_save_failure_does_not_send_or_mutate(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("First", "Body")
    item = coord.data.queue[0]
    with (
        patch.object(coord._store, "async_save", side_effect=OSError("disk full")),
        patch.object(coord, "_async_call_service") as send,
    ):
        with pytest.raises(HomeAssistantError, match="persist"):
            await coord.async_send_pending(item.id, ["notify.phone"])
        send.assert_not_called()
    assert coord.data.queue == [item]
    await coord.async_shutdown()


async def test_send_pending_rejects_expired_missing_and_busy(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("First", "Body")
    item = coord.data.queue[0]
    lock = coord._item_locks.setdefault(item.id, asyncio.Lock())
    async with lock:
        with pytest.raises(ServiceValidationError, match="processed"):
            await coord.async_send_pending(item.id, ["notify.phone"])
    coord._update(replace(item, expires_at=item.created_at - timedelta(seconds=1)))
    with pytest.raises(ServiceValidationError, match="expired"):
        await coord.async_send_pending(item.id, ["notify.phone"])
    with pytest.raises(ServiceValidationError, match="not found"):
        await coord.async_send_pending("missing")
    with pytest.raises(ServiceValidationError, match="not found"):
        await coord.async_cancel_pending("missing")
    await coord.async_shutdown()


async def test_queue_services_and_unload(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coord = mock_config_entry.runtime_data.coordinator
    for service, method, data, args in [
        ("cancel_pending", "async_cancel_pending", {"notification_id": "one"}, ("one",)),
        ("clear_queue", "async_cancel_pending", {}, ()),
        ("send_pending", "async_send_pending",
         {"notification_id": "one", "targets": ["notify.phone"]},
         ("one", ["notify.phone"])),
    ]:
        with patch.object(coord, method) as handler:
            await hass.services.async_call(
                "smart_presence_notify", service, data, blocking=True
            )
            handler.assert_awaited_once_with(*args)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    for service in ("cancel_pending", "clear_queue", "send_pending"):
        assert not hass.services.has_service("smart_presence_notify", service)


async def test_cancel_during_delivery_does_not_claim_to_recall(hass):
    coord = await make_coordinator(hass)
    started, finish = asyncio.Event(), asyncio.Event()

    async def deliver(call):
        started.set()
        await finish.wait()

    hass.services.async_register("notify", "phone", deliver)
    await coord.async_send_notification("First", "Body")
    item_id = coord.data.queue[0].id
    task = hass.async_create_task(
        coord.async_send_pending(item_id, ["notify.phone"])
    )
    await started.wait()
    with pytest.raises(ServiceValidationError, match="processed"):
        await coord.async_cancel_pending(item_id)
    with pytest.raises(ServiceValidationError, match="processed"):
        await coord.async_cancel_pending()
    finish.set()
    await task
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_send_pending_uses_home_routing(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("First", "Body")
    item_id = coord.data.queue[0].id
    delivered = AsyncMock()
    hass.services.async_register("notify", "mobile_app_mario", delivered)
    # Supply the freshly observed presence without triggering automatic draining.
    with patch.object(coord, "_get_presence", return_value=(True, ["person.mario"])):
        await coord.async_send_pending(item_id)
    delivered.assert_awaited_once()
    assert not coord.data.queue
    await coord.async_shutdown()
