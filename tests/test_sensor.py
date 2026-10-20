"""Tests for sensor entities."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_queue_count_sensor_initial_zero(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.smart_presence_notify_queue_count")
    assert state is not None
    assert state.state == "0"


async def test_queue_count_sensor_updates(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    await coordinator.async_send_notification("Test", "Body")

    state = hass.states.get("sensor.smart_presence_notify_queue_count")
    assert state.state == "1"
    assert state.attributes["queue"][0]["title"] == "Test"


async def test_last_sent_sensor_unknown_initially(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.smart_presence_notify_last_sent")
    assert state is not None
    assert state.state == "unknown"


async def test_delivery_history_full_content_and_renamed_sensor(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity(
        "sensor.smart_presence_notify_last_sent",
        new_entity_id="sensor.notification_history",
    )
    await hass.async_block_till_done()
    events = []
    hass.bus.async_listen("logbook_entry", events.append)

    async def delivered(call):
        pass

    for name in ("mobile_app_mario", "mobile_app_lucia"):
        hass.services.async_register("notify", name, delivered)
    coordinator = mock_config_entry.runtime_data.coordinator
    title = "Titolo " * 50
    message = "Testo completo\nSeconda riga 🔔 " * 30
    for _ in range(2):
        await coordinator.async_send_notification(title, message)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.notification_history")
    assert state.state == title[:255]
    assert state.attributes["title"] == title
    assert state.attributes["message"] == message
    assert state.attributes["recipients"] == [
        "notify.mobile_app_mario", "notify.mobile_app_lucia"
    ]
    assert len(events) == 2
    for event in events:
        assert event.data["entity_id"] == "sensor.notification_history"
        assert event.data["message"] == (
            f"{title} → notify.mobile_app_mario, notify.mobile_app_lucia: {message}"
        )
