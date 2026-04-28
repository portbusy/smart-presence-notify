"""Tests for config flow."""
from __future__ import annotations

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


async def test_step2_no_persons_shows_error(hass: HomeAssistant):
    """Person step with no persons configured shows error."""
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    # No person entities in hass, so persons form is empty → error
    result = await hass.config_entries.flow.async_configure(flow_id, user_input={})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_persons"


async def test_full_flow_creates_entry(hass: HomeAssistant):
    """Full flow with person and notify service creates a config entry."""
    hass.states.async_set("person.mario", "home")
    # Register a fake notify service
    hass.services.async_register("notify", "mobile_app_mario", lambda call: None)

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Home Notifier",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 30,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={"person.mario__services": ["notify.mobile_app_mario"]},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["persons"]["person.mario"]["notify_services"] == [
        "notify.mobile_app_mario"
    ]
    assert result["data"]["queue_timeout_minutes"] == 30


async def test_single_admin_no_admin_selected_shows_error(hass: HomeAssistant):
    """Single admin mode without admin selected shows error."""
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    hass.services.async_register("notify", "mobile_app_mario", lambda call: None)
    hass.services.async_register("notify", "mobile_app_lucia", lambda call: None)

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Test",
            "target_mode": "single_admin",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    # Submit persons without admin_person field → no admin → error
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "person.mario__services": ["notify.mobile_app_mario"],
            "person.lucia__services": ["notify.mobile_app_lucia"],
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "admin_required"
