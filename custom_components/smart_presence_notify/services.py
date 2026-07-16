"""Service registration for Smart Presence Notify."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, RESPONSE_PRESET_YES_NO, Priority
from .models import SNPRuntimeData

SERVICE_SEND = "send"

def _validate_response_fields(data: dict) -> dict:
    """Validate the optional actionable-notification fields together."""
    preset = data.get("response_preset")
    response_id = data.get("response_id")
    extra_data = data.get("data", {})

    if preset and not response_id:
        raise vol.Invalid("response_id is required when response_preset is set")
    if response_id and not preset:
        raise vol.Invalid("response_preset is required when response_id is set")
    if preset and "actions" in extra_data:
        raise vol.Invalid(
            "data.actions cannot be combined with response_preset"
        )
    return data


SERVICE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("title"): cv.string,
            vol.Required("message"): cv.string,
            vol.Optional("priority", default=Priority.NORMAL): vol.In(
                [p.value for p in Priority]
            ),
            vol.Optional("target_override"): cv.string,
            vol.Optional("targets"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("data"): dict,
            vol.Optional("response_preset"): vol.In([RESPONSE_PRESET_YES_NO]),
            vol.Optional("response_id"): vol.All(
                cv.string, vol.Length(min=1, max=64)
            ),
        }
    ),
    _validate_response_fields,
)


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
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
            response_preset=call.data.get("response_preset"),
            response_id=call.data.get("response_id"),
        )

    hass.services.async_register(DOMAIN, SERVICE_SEND, handle_send, SERVICE_SCHEMA)


def unregister_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_SEND)
