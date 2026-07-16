"""Tests for smart_presence_notify.send service."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


async def test_service_send_calls_coordinator(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(coordinator, "async_send_notification") as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "send",
            {"title": "Test", "message": "Hello", "priority": "normal"},
            blocking=True,
        )
        mock_send.assert_called_once_with(
            title="Test",
            message="Hello",
            priority="normal",
            target_override=None,
            targets=None,
            extra_data=None,
            response_preset=None,
            response_id=None,
        )


async def test_service_send_missing_title_raises(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN,
            "send",
            {"message": "no title"},
            blocking=True,
        )


async def test_service_send_with_target_override(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(coordinator, "async_send_notification") as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "send",
            {
                "title": "Alert",
                "message": "Body",
                "priority": "high",
                "target_override": "notify.telegram",
            },
            blocking=True,
        )
        mock_send.assert_called_once_with(
            title="Alert",
            message="Body",
            priority="high",
            target_override="notify.telegram",
            targets=None,
            extra_data=None,
            response_preset=None,
            response_id=None,
        )


async def test_service_send_with_yes_no_preset(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(coordinator, "async_send_notification") as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "send",
            {
                "title": "Garage",
                "message": "Close it?",
                "response_preset": "yes_no",
                "response_id": "close_garage",
            },
            blocking=True,
        )
        mock_send.assert_called_once_with(
            title="Garage",
            message="Close it?",
            priority="normal",
            target_override=None,
            targets=None,
            extra_data=None,
            response_preset="yes_no",
            response_id="close_garage",
        )


@pytest.mark.parametrize(
    "service_data",
    [
        {"response_preset": "yes_no"},
        {"response_id": "question"},
        {
            "response_preset": "yes_no",
            "response_id": "question",
            "data": {"actions": []},
        },
    ],
)
async def test_service_rejects_invalid_response_fields(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    service_data: dict,
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN,
            "send",
            {"title": "Question", "message": "Answer?", **service_data},
            blocking=True,
        )
