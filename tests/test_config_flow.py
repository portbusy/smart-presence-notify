"""Tests for config flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smart_presence_notify.const import DOMAIN


async def test_step1_form_shown(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step1_invalid_timeout(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        hass.config_entries.flow.async_progress()[0]["flow_id"],
        user_input={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": -1,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert "queue_timeout_minutes" in result["errors"]


async def test_step1_proceeds_to_step2(hass: HomeAssistant):
    hass.states.async_set("person.mario", "home")
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        hass.config_entries.flow.async_progress()[0]["flow_id"],
        user_input={
            "name": "My Notifier",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "persons"
