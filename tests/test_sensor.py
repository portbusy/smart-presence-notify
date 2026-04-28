"""Tests for sensor entities."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


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
    assert state.state in ("unknown", "unavailable", "")
