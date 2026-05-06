"""Tests for integration setup and teardown."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN
from custom_components.smart_presence_notify.models import SNPRuntimeData
from tests.conftest import make_entry


async def test_setup_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "LOADED"
    assert isinstance(mock_config_entry.runtime_data, SNPRuntimeData)
    assert mock_config_entry.runtime_data.coordinator is not None


async def test_unload_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "NOT_LOADED"


async def test_second_config_entry_is_rejected(hass: HomeAssistant):
    """single_config_entry:true must block a second entry from loading."""
    first = make_entry()
    first.add_to_hass(hass)
    await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    assert first.state is ConfigEntryState.LOADED

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"
