"""Service stubs — implemented later."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    pass


def unregister_services(hass: HomeAssistant) -> None:
    pass
