"""Diagnostic tests must never replace or retry real queued notifications."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.smart_presence_notify.const import DOMAIN
from tests.test_reliability import make_coordinator


async def test_diagnostic_does_not_replace_last_only_queue(hass):
    coord = await make_coordinator(hass, queue_mode="last_only")
    await coord.async_send_notification("Real alert", "Body", notification_key="garage")
    original = list(coord.data.queue)
    deliver = AsyncMock()
    hass.services.async_register("notify", "phone", deliver)
    await coord.async_test_notification(["notify.phone", "notify.phone"])
    deliver.assert_awaited_once()
    assert coord.data.queue == original
    assert await coord._store.async_load() == original
    assert coord.data.last_test["result"] == "provider_accepted"
    assert coord.data.last_test["successful_targets"] == ["notify.phone"]
    await coord.async_shutdown()


async def test_diagnostic_partial_failure_is_reported_without_retry(hass):
    coord = await make_coordinator(hass)
    deliver = AsyncMock()
    hass.services.async_register("notify", "phone", deliver)
    with pytest.raises(HomeAssistantError, match="notify.missing"):
        await coord.async_test_notification(["notify.phone", "notify.missing"])
    assert coord.data.last_test["result"] == "partial"
    assert coord.data.last_test["failed_targets"] == ["notify.missing"]
    assert coord.data.last_sent.recipients == ["notify.phone"]
    assert not coord.data.queue
    assert not coord._timeout_unsubs
    with pytest.raises(HomeAssistantError):
        await coord.async_test_notification(["notify.missing"])
    assert coord.data.last_test["result"] == "failed"
    await coord.async_shutdown()


async def test_diagnostic_without_targets_requires_presence_and_configured_mode(hass):
    coord = await make_coordinator(hass)
    with pytest.raises(ServiceValidationError, match="No home recipients"):
        await coord.async_test_notification()
    assert not coord.data.queue
    await coord.async_shutdown()
    coord = await make_coordinator(hass, target_mode="caller_decides")
    with pytest.raises(ServiceValidationError, match="Caller-defined"):
        await coord.async_test_notification()
    await coord.async_shutdown()


async def test_button_service_and_localized_waiting_explanation(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coord = mock_config_entry.runtime_data.coordinator
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{mock_config_entry.entry_id}_test_notification"
    )
    assert button_id
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "button", "press", {"entity_id": button_id}, blocking=True
        )
    deliver = AsyncMock()
    hass.services.async_register("notify", "mobile_app_mario", deliver)
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
    deliver.assert_awaited_once()
    status = hass.states.get("sensor.smart_presence_notify_delivery_status")
    assert status.attributes["last_test"]["result"] == "provider_accepted"
    hass.states.async_set("person.mario", "not_home")
    await hass.async_block_till_done()
    hass.config.language = "it"
    await coord.async_send_notification("Garage", "Open")
    queue = hass.states.get("sensor.smart_presence_notify_queue_count")
    assert queue.attributes["queue"][0]["reason"] == "waiting_for_presence"
    assert "rientri" in queue.attributes["queue"][0]["explanation"]
    assert hass.states.get("sensor.smart_presence_notify_delivery_status").state == "waiting"
    await hass.services.async_call(
        DOMAIN, "test_notification", {"targets": ["notify.mobile_app_mario"]}, blocking=True
    )
    assert deliver.call_count == 2
    assert len(coord.data.queue) == 1
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert hass.states.get(button_id).state == "unavailable"
    assert not hass.services.has_service(DOMAIN, "test_notification")
