"""Durable acceptance, payload preservation and unavailable destination recovery."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.components.notify import (
    DATA_COMPONENT,
    NotifyEntity,
    NotifyEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.smart_presence_notify import async_remove_entry
from custom_components.smart_presence_notify.store import SNPStore
from tests.test_mobile_notify import registered_phone
from tests.test_reliability import make_coordinator


async def test_unavailable_entity_stays_queued_until_recovery(hass):
    calls = []

    class RecoveringNotify(NotifyEntity):
        _attr_name = "Offline phone"
        _attr_available = False
        _attr_supported_features = NotifyEntityFeature.TITLE

        async def async_send_message(self, message, title=None):
            calls.append((title, message))

    await async_setup_component(hass, "notify", {})
    phone = RecoveringNotify()
    await hass.data[DATA_COMPONENT].async_add_entities([phone])
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Important", "Body", target_override=phone.entity_id
    )
    assert not calls
    assert len(coord.data.queue) == 1
    assert coord.data.last_sent is None
    phone._attr_available = True
    phone.async_write_ha_state()
    await coord.async_retry_pending()
    assert calls == [("Important", "Body")]
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_entity_disappearing_during_service_call_stays_queued(hass):
    hass.states.async_set("notify.phone", "unknown")
    hass.services.async_register(
        "notify",
        "send_message",
        lambda call: hass.states.async_remove("notify.phone"),
    )
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Important", "Body", target_override="notify.phone"
    )
    assert len(coord.data.queue) == 1
    assert coord.data.last_sent is None
    await coord.async_shutdown()


async def test_unavailable_companion_entity_uses_available_service(hass):
    phone = registered_phone(hass)
    hass.states.async_set(phone, "unavailable")
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: calls.append(call.data)
    )
    coord = await make_coordinator(hass)
    await coord.async_send_notification("Important", "Body", target_override=phone)
    assert calls == [{"title": "Important", "message": "Body"}]
    assert not coord.data.queue
    await coord.async_shutdown()


@pytest.mark.parametrize(
    "extra",
    [
        {"tag": "replace"},
        {"live_update": True, "tag": "vacuum", "progress": 40},
        {"actions": [{"action": "PAUSE", "title": "Pause"}]},
        {"image": "/local/image.png"},
    ],
)
async def test_summary_preserves_advanced_messages_alongside_plain_summary(hass, extra):
    coord = await make_coordinator(hass, queue_mode="summary")
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_mario", lambda c: calls.append(c.data)
    )
    await coord.async_send_notification("Plain", "Plain body")
    await coord.async_send_notification("Advanced", "Advanced body", extra_data=extra)
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert calls[0]["title"] == "Missed notifications"
    assert "Plain" in calls[0]["message"]
    assert "Advanced" not in calls[0]["message"]
    assert calls[1] == {"title": "Advanced", "message": "Advanced body", "data": extra}
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_rejected_enqueue_is_not_delivered_after_storage_recovers(hass):
    coord = await make_coordinator(hass)
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_mario", lambda c: calls.append(c.data)
    )
    with (
        patch.object(coord._store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError),
    ):
        await coord.async_send_notification("Rejected", "Body")
    assert not coord.data.queue
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert not calls
    await coord.async_shutdown()


@pytest.mark.parametrize("mode", ["last_only", "bell"])
async def test_failed_replacement_preserves_previous_durable_message(hass, mode):
    coord = await make_coordinator(hass, queue_mode="last_only")

    async def send(title):
        if mode == "bell":
            await coord.async_forward_notification(
                title, "Body", ["notify.mobile_app_phone"], {"tag": "bell"}
            )
        else:
            await coord.async_send_notification(title, "Body")

    await send("Accepted")
    with (
        patch.object(coord._store, "async_save", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError),
    ):
        await send("Rejected")
    assert [n.title for n in coord.data.queue] == ["Accepted"]
    assert [n.title for n in await coord._store.async_load()] == ["Accepted"]
    await coord.async_shutdown()


async def test_concurrent_last_only_enqueues_retain_only_latest(hass):
    coord = await make_coordinator(hass, queue_mode="last_only")
    started, release = asyncio.Event(), asyncio.Event()
    save = coord._store.async_save

    async def blocked_save(queue):
        if queue[-1].title == "First":
            started.set()
            await release.wait()
        await save(queue)

    with patch.object(coord._store, "async_save", side_effect=blocked_save):
        first = asyncio.create_task(coord.async_send_notification("First", "Body"))
        await started.wait()
        second = asyncio.create_task(coord.async_send_notification("Second", "Body"))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
    assert [n.title for n in coord.data.queue] == ["Second"]
    assert [n.title for n in await coord._store.async_load()] == ["Second"]
    await coord.async_shutdown()


async def test_concurrent_enqueue_respects_capacity(hass):
    coord = await make_coordinator(hass, queue_limit=1)
    results = await asyncio.gather(
        coord.async_send_notification("First", "Body"),
        coord.async_send_notification("Second", "Body"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ServiceValidationError) for result in results) == 1
    assert len(coord.data.queue) == 1
    assert len(await coord._store.async_load()) == 1
    await coord.async_shutdown()


async def test_enqueue_preserves_delivery_checkpoint_changed_during_save(hass):
    coord = await make_coordinator(hass)
    sending, finish_delivery = asyncio.Event(), asyncio.Event()
    saving, finish_save, checkpointed = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def phone(call):
        sending.set()
        await finish_delivery.wait()

    hass.services.async_register("notify", "mobile_app_phone", phone)
    delivery = asyncio.create_task(
        coord.async_send_notification(
            "In flight", "Body", target_override="notify.mobile_app_phone"
        )
    )
    await sending.wait()
    save, persist = coord._store.async_save, coord._persist

    async def blocked_save(queue):
        if queue[-1].title == "New" and not finish_save.is_set():
            saving.set()
            await finish_save.wait()
        await save(queue)

    async def observe_checkpoint():
        if any(n.delivered_targets for n in coord.data.queue):
            checkpointed.set()
        await persist()

    with (
        patch.object(coord._store, "async_save", side_effect=blocked_save),
        patch.object(coord, "_persist", side_effect=observe_checkpoint),
    ):
        enqueue = asyncio.create_task(coord._enqueue("New", "Body", "normal", {}))
        await saving.wait()
        finish_delivery.set()
        await checkpointed.wait()
        finish_save.set()
        await asyncio.gather(delivery, enqueue)
    assert [n.title for n in coord.data.queue] == ["New"]
    assert [n.title for n in await coord._store.async_load()] == ["New"]
    await coord.async_shutdown()


async def test_removal_clears_queue_but_unload_preserves_it(hass):
    coord = await make_coordinator(hass)
    await coord.async_send_notification("Old message", "Body")
    await coord.async_shutdown()
    assert len(await SNPStore(hass).async_load()) == 1
    await async_remove_entry(hass, coord.config_entry)
    assert not await SNPStore(hass).async_load()


async def test_bell_replacement_preserves_direct_message_with_same_tag(hass):
    coord = await make_coordinator(hass)
    tag = "smart_presence_notify_dreame_vacuum_error"
    await coord.async_send_notification(
        "Direct",
        "Body",
        target_override="notify.mobile_app_phone",
        extra_data={"tag": tag, "live_update": True},
    )
    original = coord.data.queue[0].id
    await coord.async_forward_notification(
        "Bell", "Body", ["notify.mobile_app_phone"], {"tag": tag}
    )
    assert original in [n.id for n in coord.data.queue]
    assert len(coord.data.queue) == 2
    await coord.async_shutdown()
