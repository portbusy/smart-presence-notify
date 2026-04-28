"""Tests for SmartPresenceNotifyCoordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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


async def test_send_broadcast_to_home_persons(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(coord, "_async_call_service", new_callable=AsyncMock) as mock_call:
        await coord.async_send_notification("Door", "Open", priority="normal")
        mock_call.assert_called_once_with(
            "notify.mobile_app_mario", "Door", "Open", {}
        )
    assert coord.data.last_sent.title == "Door"
    assert coord.data.last_sent.recipients == ["notify.mobile_app_mario"]


async def test_send_target_override(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(coord, "_async_call_service", new_callable=AsyncMock) as mock_call:
        await coord.async_send_notification(
            "Test", "Msg", target_override="notify.telegram"
        )
        mock_call.assert_called_once_with(
            "notify.telegram", "Test", "Msg", {}
        )


async def test_high_priority_bypasses_queue_sends_to_first_home(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(coord, "_async_call_service", new_callable=AsyncMock) as mock_call:
        await coord.async_send_notification("Alert", "Fire!", priority="high")
        mock_call.assert_called_once()
    assert coord.data.queue == []


async def test_normal_priority_nobody_home_enqueues(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(coord, "_async_call_service", new_callable=AsyncMock) as mock_call:
        await coord.async_send_notification("Door", "Open")
        mock_call.assert_not_called()
    assert len(coord.data.queue) == 1
    assert coord.data.queue[0].title == "Door"


async def test_high_priority_nobody_home_uses_fallback(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "notify_fallback",
            "fallback_service": "notify.telegram",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(coord, "_async_call_service", new_callable=AsyncMock) as mock_call:
        await coord.async_send_notification("Alert", "Fire!", priority="high")
        mock_call.assert_called_once_with(
            "notify.telegram", "Alert", "Fire!", {}
        )
