"""Tests for binary sensor entities."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


async def test_someone_home_off_when_all_away(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["home_persons"] == []


async def test_someone_home_on_when_person_home(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "on"
    assert "person.mario" in state.attributes["home_persons"]


async def test_someone_home_updates_on_arrival(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "off"

    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "on"
