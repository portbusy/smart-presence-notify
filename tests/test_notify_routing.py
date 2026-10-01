"""Central notify entity and payload-aware Companion routing regressions."""

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.config_flow import _notify_options
from custom_components.smart_presence_notify.models import PendingNotification
from tests.test_mobile_notify import registered_phone
from tests.test_reliability import make_coordinator


async def test_standard_notify_entity_queues_and_delivers_on_arrival(
    hass, mock_config_entry
):
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_mario", lambda call: calls.append(call.data)
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    central = hass.states.async_entity_ids("notify")[0]
    assert central not in _notify_options(hass)
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": central, "title": "Laundry", "message": "Done"},
        blocking=True,
    )
    coord = mock_config_entry.runtime_data.coordinator
    assert not calls
    assert len(coord.data.queue) == 1
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert calls == [{"title": "Laundry", "message": "Done"}]
    assert not coord.data.queue
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": central, "message": "No title"},
        blocking=True,
    )
    assert calls[-1]["title"] == mock_config_entry.title
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert hass.states.get(central).state == "unavailable"
    sent = len(calls)
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": central, "message": "Unloaded"},
        blocking=True,
    )
    assert len(calls) == sent


async def test_renamed_central_entity_cannot_be_a_routing_destination(
    hass, mock_config_entry
):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    central = hass.states.async_entity_ids("notify")[0]
    er.async_get(hass).async_update_entity(
        central, new_entity_id="notify.renamed_router"
    )
    await hass.async_block_till_done()
    coord = mock_config_entry.runtime_data.coordinator
    with pytest.raises(ServiceValidationError, match="cannot be destinations"):
        await coord.async_send_notification(
            "Loop", "Body", target_override="notify.renamed_router"
        )
    assert not coord.data.queue


@pytest.mark.parametrize("selected", ["entity", "service", "both"])
async def test_plain_notification_prefers_modern_channel_and_sends_once(hass, selected):
    phone = registered_phone(hass)
    modern, legacy = [], []
    hass.services.async_register(
        "notify", "send_message", lambda call: modern.append(call.data)
    )
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: legacy.append(call.data)
    )
    targets = {
        "entity": [phone],
        "service": ["notify.mobile_app_phone_davide"],
        "both": [phone, "notify.mobile_app_phone_davide"],
    }[selected]
    coord = await make_coordinator(hass, target_mode="caller_decides")
    hass.states.async_set("person.mario", "home")
    await coord.async_send_notification("Simple", "Body", targets=targets)
    assert modern == [{"title": "Simple", "message": "Body", "entity_id": phone}]
    assert not legacy
    await coord.async_shutdown()


async def test_central_entities_keep_their_own_configuration(hass):
    calls = []
    entries = []
    for person in ["mario", "lucia"]:
        entry = MockConfigEntry(
            domain="smart_presence_notify",
            title=person,
            data={
                "target_mode": "broadcast",
                "queue_mode": "fifo",
                "persons": {
                    f"person.{person}": {
                        "notify_services": [f"notify.mobile_app_{person}"]
                    }
                },
            },
        )
        entry.add_to_hass(hass)
        hass.states.async_set(f"person.{person}", "home")
        hass.services.async_register(
            "notify", f"mobile_app_{person}", lambda call: calls.append(call.service)
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        entity = next(
            e.entity_id
            for e in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
            if e.domain == "notify"
        )
        entries.append((entry, entity))
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": entity, "message": "Own route"},
            blocking=True,
        )
    assert calls == ["mobile_app_mario", "mobile_app_lucia"]
    assert await hass.config_entries.async_unload(entries[0][0].entry_id)
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": entries[1][1], "message": "Still active"},
        blocking=True,
    )
    assert calls[-1] == "mobile_app_lucia"


async def test_live_payload_cannot_be_sent_to_an_unrelated_provider(hass):
    calls = []
    hass.services.async_register(
        "notify", "telegram", lambda call: calls.append(call.data)
    )
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Live",
        "Body",
        target_override="notify.telegram",
        extra_data={"live_update": True, "tag": "vacuum"},
    )
    assert not calls
    assert "cannot receive Companion Live Activities" in coord.data.last_error
    assert coord.data.queue
    await coord.async_shutdown()


@pytest.mark.parametrize(
    "extra",
    [
        {"tag": "replace"},
        {"live_update": True, "tag": "vacuum", "progress": 40, "progress_max": 100},
        {"actions": [{"action": "PAUSE", "title": "Pause"}]},
        {"image": "/local/vacuum.png"},
    ],
)
async def test_advanced_payload_uses_linked_legacy_channel_unchanged(hass, extra):
    phone = registered_phone(hass)
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: calls.append(call.data)
    )
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Advanced", "Body", target_override=phone, extra_data=extra
    )
    assert calls == [{"title": "Advanced", "message": "Body", "data": extra}]
    await coord.async_shutdown()


async def test_high_priority_and_response_buttons_work_with_entity_selection(hass):
    phone = registered_phone(hass)
    calls = []
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: calls.append(call.data)
    )
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Question",
        "Done?",
        priority="high",
        target_override=phone,
        response_preset="yes_no",
        response_id="vacuum",
    )
    assert calls[0]["data"]["priority"] == "high"
    assert calls[0]["data"]["actions"]
    assert all(token.sent for token in coord._response_tokens.values())
    await coord.async_shutdown()


async def test_missing_advanced_channel_reports_failure_and_can_be_retried(hass):
    phone = registered_phone(hass)
    modern, legacy = [], []
    hass.services.async_register(
        "notify", "send_message", lambda call: modern.append(call.data)
    )
    coord = await make_coordinator(hass)
    extra = {"live_update": True, "tag": "vacuum"}
    await coord.async_send_notification(
        "Live", "Cleaning", target_override=phone, extra_data=extra
    )
    assert not modern
    assert coord.data.queue[0].extra_data == extra
    assert "requires a Companion App service" in coord.data.last_error
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: legacy.append(call.data)
    )
    await coord.async_retry_pending()
    assert legacy[0]["data"] == extra
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_generic_notify_entity_does_not_silently_drop_advanced_data(hass):
    hass.states.async_set("notify.generic", "unknown")
    coord = await make_coordinator(hass)
    await coord.async_send_notification(
        "Advanced",
        "Body",
        target_override="notify.generic",
        extra_data={"tag": "required"},
    )
    assert "accepts only title/message" in coord.data.last_error
    assert len(coord.data.queue) == 1
    await coord.async_shutdown()


async def test_bell_marker_survives_storage_without_changing_old_items(hass):
    coord = await make_coordinator(hass)
    item = await coord._enqueue(
        "Bell", "Body", "normal", {"tag": "bell"}, is_bell_forward=True
    )
    saved = item.to_dict()
    assert PendingNotification.from_dict(saved).is_bell_forward
    saved.pop("is_bell_forward")
    assert not PendingNotification.from_dict(saved).is_bell_forward
    await coord.async_shutdown()


@pytest.mark.parametrize("tag", [None, "", "has spaces", "x" * 65])
async def test_live_activity_requires_valid_identity_before_queueing(hass, tag):
    coord = await make_coordinator(hass)
    with pytest.raises(ServiceValidationError, match="stable tag"):
        await coord.async_send_notification(
            "Live",
            "Body",
            target_override="notify.mobile_app_phone",
            extra_data={"live_update": True, "tag": tag},
        )
    assert not coord.data.queue
    await coord.async_shutdown()
