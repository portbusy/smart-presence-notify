"""Service registration for Smart Presence Notify."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, Priority
from .models import SNPRuntimeData

SERVICE_SEND = "send"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("priority", default=Priority.NORMAL): vol.In(
            [p.value for p in Priority]
        ),
        vol.Optional("target_override"): cv.string,
        vol.Optional("targets"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("data"): dict,
    }
)


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND):
        return

    async def handle_send(call: ServiceCall) -> None:
        runtime: SNPRuntimeData = entry.runtime_data
        coordinator = runtime.coordinator
        await coordinator.async_send_notification(
            title=call.data["title"],
            message=call.data["message"],
            priority=call.data.get("priority", Priority.NORMAL),
            target_override=call.data.get("target_override"),
            targets=call.data.get("targets"),
            extra_data=call.data.get("data"),
        )

    hass.services.async_register(DOMAIN, SERVICE_SEND, handle_send, SERVICE_SCHEMA)


def unregister_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_SEND)
