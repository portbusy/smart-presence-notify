"""Regressions for confirmed delivery, per-recipient recovery and forwarding."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from homeassistant.components import persistent_notification
from homeassistant.exceptions import HomeAssistantError

from custom_components.smart_presence_notify.coordinator import (
    SmartPresenceNotifyCoordinator,
)
from tests.conftest import make_entry


async def make_coordinator(hass, **changes):
    entry = make_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, **changes})
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()
    await hass.async_block_till_done()
    return coord


async def test_failed_destination_does_not_block_or_duplicate_success(hass):
    hass.states.async_set("person.mario", "home")
    coord = await make_coordinator(
        hass,
        persons={
            "person.mario": {"notify_services": ["notify.missing", "notify.working"]}
        },
    )
    calls = []

    async def working(call):
        calls.append(call.data)

    hass.services.async_register("notify", "working", working)
    await coord.async_send_notification("Hello", "Body")
    assert len(calls) == 1
    assert coord.data.queue[0].targets == ["notify.missing"]
    assert coord.data.last_sent.recipients == ["notify.working"]
    hass.services.async_register("notify", "missing", working)
    await coord.async_retry_pending()
    assert len(calls) == 2
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_provider_failure_is_retained(hass):
    coord = await make_coordinator(hass)

    async def fail(call):
        raise HomeAssistantError("offline")

    hass.services.async_register("notify", "broken", fail)
    await coord.async_send_notification(
        "Hello", "Body", target_override="notify.broken"
    )
    assert coord.data.last_sent is None
    assert len(coord.data.queue) == 1
    assert coord.data.queue[0].retry_at is not None
    assert coord.data.last_error
    await coord.async_shutdown()


async def test_caller_targets_survive_waiting_for_presence(hass):
    hass.states.async_set("person.mario", "not_home")
    coord = await make_coordinator(hass, target_mode="caller_decides")
    calls = []

    async def target(call):
        calls.append(call.data)

    hass.services.async_register("notify", "specific", target)
    await coord.async_send_notification("Hello", "Body", targets=["notify.specific"])
    assert coord.data.queue[0].targets == ["notify.specific"]
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_restored_queue_delivered_when_already_home(hass):
    hass.states.async_set("person.mario", "not_home")
    coord = await make_coordinator(hass)
    await coord.async_send_notification("Restart", "Body")
    queued = coord.data.queue.copy()
    await coord.async_shutdown()
    calls = []

    async def target(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_mario", target)
    hass.states.async_set("person.mario", "home")
    restored = SmartPresenceNotifyCoordinator(hass, coord.config_entry)
    with patch.object(restored._store, "async_load", return_value=queued):
        await restored.async_initialize()
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert not restored.data.queue
    await restored.async_shutdown()


async def test_expired_item_not_sent_on_arrival(hass):
    hass.states.async_set("person.mario", "not_home")
    coord = await make_coordinator(hass)
    await coord.async_send_notification("Expired", "Body")
    coord._update(
        replace(
            coord.data.queue[0],
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    calls = []

    async def target(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_mario", target)
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert not calls
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_bridge_filters_updates_and_dismissals(hass):
    coord = await make_coordinator(
        hass, forward_enabled=True, forward_targets=["notify.mobile_app_phone"]
    )
    calls = []

    async def target(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_phone", target)
    persistent_notification.async_create(hass, "Ignored", "Other", "unrelated")
    persistent_notification.async_create(
        hass, "Error", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0]["message"] == "Error"
    persistent_notification.async_create(
        hass, "Error", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    persistent_notification.async_create(
        hass, "Fixed", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert calls[0]["data"]["tag"] == calls[1]["data"]["tag"]
    persistent_notification.async_dismiss(hass, "dreame_vacuum_mac_error")
    await hass.async_block_till_done()
    assert len(calls) == 2
    await coord.async_shutdown()
    persistent_notification.async_create(
        hass, "After unload", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_options_factory_and_mobile_settings(hass):
    coord = await make_coordinator(hass)
    result = await hass.config_entries.options.async_init(coord.config_entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "forwarding"}
    )
    assert result["step_id"] == "forwarding"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "forward_enabled": True,
            "forward_targets": ["notify.mobile_app_phone"],
            "forward_id_patterns": ["dreame_vacuum_*"],
            "forward_text": "",
            "forward_updates": True,
        },
    )
    assert result["type"] == "create_entry"
    assert coord.config_entry.data["forward_enabled"]
    await coord.async_shutdown()


async def test_unload_cancels_active_service_delivery(hass):
    import asyncio

    coord = await make_coordinator(hass)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(call):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    hass.services.async_register("notify", "blocked", blocked)
    task = asyncio.create_task(
        coord.async_send_notification("Hello", "Body", target_override="notify.blocked")
    )
    await started.wait()
    await coord.async_shutdown()
    assert task.cancelled()
    assert cancelled.is_set()
    assert len(coord.data.queue) == 1
    assert coord.data.last_sent is None


async def test_failed_expiry_fallback_can_retry(hass):
    coord = await make_coordinator(
        hass, fallback_mode="notify_fallback", fallback_service="notify.backup"
    )
    await coord.async_send_notification("Hello", "Body")
    await coord._async_expire_notification(coord.data.queue[0])
    assert coord.data.queue[0].expired
    assert coord.data.queue[0].targets == ["notify.backup"]
    assert coord.data.queue[0].retry_at
    calls = []

    async def backup(call):
        calls.append(call.data)

    hass.services.async_register("notify", "backup", backup)
    await coord.async_retry_pending()
    assert len(calls) == 1
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_queue_capacity_rejects_new_message(hass):
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    coord = await make_coordinator(hass, queue_limit=1)
    await coord.async_send_notification("First", "Body")
    with pytest.raises(ServiceValidationError, match="full"):
        await coord.async_send_notification("Second", "Body")
    assert [n.title for n in coord.data.queue] == ["First"]
    await coord.async_shutdown()


async def test_notification_entity_uses_send_message_target(hass):
    coord = await make_coordinator(hass)
    hass.states.async_set("notify.living_room", "unknown")
    calls = []

    async def send_message(call):
        calls.append(call.data)

    hass.services.async_register("notify", "send_message", send_message)
    await coord.async_send_notification(
        "Entity", "Body", target_override="notify.living_room"
    )
    assert calls == [
        {"title": "Entity", "message": "Body", "entity_id": "notify.living_room"}
    ]
    await coord.async_shutdown()


async def test_options_refresh_presence_immediately(hass):
    coord = await make_coordinator(hass)
    assert not coord.data.someone_home
    hass.states.async_set("person.other", "home")
    hass.config_entries.async_update_entry(
        coord.config_entry,
        data={
            **coord.config_entry.data,
            "persons": {"person.other": {"notify_services": ["notify.phone"]}},
        },
    )
    coord.async_reload_presence_listener()
    assert coord.data.home_persons == ["person.other"]
    await hass.async_block_till_done()
    await coord.async_shutdown()


async def test_unknown_and_replayed_response_tokens_are_ignored(hass):
    import base64
    import uuid

    import pytest
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.smart_presence_notify.const import EVENT_RESPONSE

    coord = await make_coordinator(hass)
    calls, responses = [], []

    async def phone(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_phone", phone)
    unsub = hass.bus.async_listen(
        EVENT_RESPONSE, lambda event: responses.append(event.data)
    )
    encoded = base64.urlsafe_b64encode(b"question").decode().rstrip("=")
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"SNP_YES_{uuid.uuid4().hex}.{encoded}"},
    )
    await hass.async_block_till_done()
    assert not responses
    with patch(
        "custom_components.smart_presence_notify.coordinator.MAX_RESPONSE_TOKENS", 2
    ):
        for response_id in ["first", "second"]:
            await coord.async_send_notification(
                "Question",
                "Body",
                target_override="notify.mobile_app_phone",
                response_preset="yes_no",
                response_id=response_id,
            )
        action = calls[0]["data"]["actions"][0]["action"]
        hass.bus.async_fire("mobile_app_notification_action", {"action": action})
        await hass.async_block_till_done()
        assert len(responses) == 1
        with pytest.raises(ServiceValidationError, match="outstanding"):
            await coord.async_send_notification(
                "Third",
                "Body",
                target_override="notify.mobile_app_phone",
                response_preset="yes_no",
                response_id="third",
            )
        hass.bus.async_fire("mobile_app_notification_action", {"action": action})
        await hass.async_block_till_done()
        assert len(responses) == 1
    unsub()
    await coord.async_shutdown()


async def test_high_priority_preserves_explicit_device_settings(hass):
    coord = await make_coordinator(hass)
    calls = []

    async def phone(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_phone", phone)
    await coord.async_send_notification(
        "High",
        "Body",
        priority="high",
        target_override="notify.mobile_app_phone",
        extra_data={"push": {"sound": "custom"}, "ttl": 60},
    )
    assert calls[0]["data"]["priority"] == "high"
    assert calls[0]["data"]["ttl"] == 60
    assert calls[0]["data"]["push"] == {
        "sound": "custom",
        "interruption-level": "time-sensitive",
    }
    await coord.async_shutdown()


async def test_bridge_replaces_failed_old_content_and_removes_base64_images(hass):
    coord = await make_coordinator(
        hass, forward_enabled=True, forward_targets=["notify.mobile_app_phone"]
    )
    persistent_notification.async_create(
        hass, "Old", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert coord.data.queue[0].message == "Old"
    calls = []

    async def phone(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_phone", phone)
    persistent_notification.async_create(
        hass,
        "New ![image](data:image/png;base64,AAAA)",
        "Vacuum",
        "dreame_vacuum_mac_error",
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0]["message"] == "New "
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_bridge_text_filter_and_updates_disabled(hass):
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_targets=["notify.mobile_app_phone"],
        forward_text="ERROR",
        forward_updates=False,
    )
    calls = []

    async def phone(call):
        calls.append(call.data)

    hass.services.async_register("notify", "mobile_app_phone", phone)
    persistent_notification.async_create(
        hass, "Cleaning done", "Vacuum", "dreame_vacuum_mac_ok"
    )
    persistent_notification.async_create(
        hass, "An error occurred", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    persistent_notification.async_create(
        hass, "Another error", "Vacuum", "dreame_vacuum_mac_error"
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    await coord.async_shutdown()


async def test_forwarding_switch_requires_destinations_and_persists(
    hass, mock_config_entry
):
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    switch_ids = hass.states.async_entity_ids("switch")
    assert len(switch_ids) == 1
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": switch_ids[0]}, blocking=True
        )
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "forward_targets": ["notify.mobile_app_phone"]},
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_ids[0]}, blocking=True
    )
    assert mock_config_entry.data["forward_enabled"]
    assert hass.states.get(switch_ids[0]).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch_ids[0]}, blocking=True
    )
    assert not mock_config_entry.data["forward_enabled"]
