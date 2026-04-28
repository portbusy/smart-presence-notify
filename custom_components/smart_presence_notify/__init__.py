"""Smart Presence Notify integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import SmartPresenceNotifyCoordinator
from .models import SNPRuntimeData
from .services import async_register_services, async_unregister_services

type SNPConfigEntry = ConfigEntry[SNPRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    coordinator = SmartPresenceNotifyCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = SNPRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_services(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    coordinator: SmartPresenceNotifyCoordinator = entry.runtime_data.coordinator
    await coordinator.async_shutdown()
    async_unregister_services(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
