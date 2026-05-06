"""Smart Presence Notify integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import SmartPresenceNotifyCoordinator
from .models import SNPRuntimeData
from .services import async_register_services, unregister_services

type SNPConfigEntry = ConfigEntry[SNPRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    coordinator = SmartPresenceNotifyCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = SNPRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_services(hass, entry)
    entry.async_on_unload(
        entry.add_update_listener(_async_reload_presence_on_update)
    )
    return True


async def _async_reload_presence_on_update(
    hass: HomeAssistant, entry: SNPConfigEntry
) -> None:
    """Rebuild the presence listener when options-flow saves new persons."""
    entry.runtime_data.coordinator.async_reload_presence_listener()


async def async_unload_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator: SmartPresenceNotifyCoordinator = entry.runtime_data.coordinator
        await coordinator.async_shutdown()
        unregister_services(hass)
    return ok
