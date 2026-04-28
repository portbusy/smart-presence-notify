"""Tests for SmartPresenceNotifyCoordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN
from custom_components.smart_presence_notify.coordinator import (
    SmartPresenceNotifyCoordinator,
)


@pytest.fixture
async def coordinator(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    return coord


async def test_someone_home_when_person_is_home(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is True
    assert "person.mario" in coord.data.home_persons


async def test_nobody_home_when_all_away(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is False
    assert coord.data.home_persons == []


async def test_presence_updates_on_state_change(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    assert coord.data.someone_home is False
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert coord.data.someone_home is True
