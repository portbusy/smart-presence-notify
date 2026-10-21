"""Service registration for Smart Presence Notify."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, RESPONSE_PRESET_YES_NO, Priority
from .runtime import SNPRuntimeData
from .validation import notification_key, notification_target

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
        raise vol.Invalid("data.actions cannot be combined with response_preset")
    return data


SERVICE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("title"): cv.string,
            vol.Required("message"): cv.string,
            vol.Optional("priority", default=Priority.NORMAL): vol.In(
                [p.value for p in Priority]
            ),
            vol.Optional("target_override"): notification_target,
            vol.Optional("targets"): vol.All(cv.ensure_list, [notification_target]),
            vol.Optional("data"): dict,
            vol.Optional("response_preset"): vol.In([RESPONSE_PRESET_YES_NO]),
            vol.Optional("response_id"): vol.All(cv.string, vol.Length(min=1, max=64)),
            vol.Optional("notification_key"): notification_key,
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
            notification_key=call.data.get("notification_key"),
        )

    async def handle_retry(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_retry_pending()

    async def handle_pause(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_pause(call.data["minutes"])

    async def handle_resume(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_resume()

    async def handle_test(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_test_notification(call.data.get("targets"))

    async def handle_cancel(call: ServiceCall) -> None:
        if "notification_key" in call.data:
            await entry.runtime_data.coordinator.async_cancel_pending(
                notification_key=call.data["notification_key"]
            )
        else:
            await entry.runtime_data.coordinator.async_cancel_pending(
                call.data["notification_id"]
            )

    async def handle_clear(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_cancel_pending()

    async def handle_send_pending(call: ServiceCall) -> None:
        await entry.runtime_data.coordinator.async_send_pending(
            call.data["notification_id"], call.data.get("targets")
        )

    hass.services.async_register(DOMAIN, SERVICE_SEND, handle_send, SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, "retry_pending", handle_retry, vol.Schema({}))
    hass.services.async_register(DOMAIN, "pause", handle_pause, vol.Schema({
        vol.Optional("minutes", default=60): vol.All(cv.positive_int, vol.Range(min=1, max=10080)),
    }))
    hass.services.async_register(DOMAIN, "resume", handle_resume, vol.Schema({}))
    hass.services.async_register(
        DOMAIN, "test_notification", handle_test, vol.Schema({
            vol.Optional("targets"): vol.All(
                cv.ensure_list, [notification_target], vol.Length(min=1)
            ),
        })
    )
    id_schema = {vol.Required("notification_id"): vol.All(cv.string, vol.Length(min=1))}
    hass.services.async_register(
        DOMAIN, "cancel_pending", handle_cancel, vol.All(
            vol.Schema({
                vol.Optional("notification_id"): vol.All(cv.string, vol.Length(min=1)),
                vol.Optional("notification_key"): notification_key,
            }),
            vol.Length(min=1, max=1),
        )
    )
    hass.services.async_register(DOMAIN, "clear_queue", handle_clear, vol.Schema({}))
    hass.services.async_register(
        DOMAIN,
        "send_pending",
        handle_send_pending,
        vol.Schema({
            **id_schema,
            vol.Optional("targets"): vol.All(
                cv.ensure_list, [notification_target], vol.Length(min=1)
            ),
        }),
    )


def unregister_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_SEND)
    hass.services.async_remove(DOMAIN, "retry_pending")
    for service in ("cancel_pending", "clear_queue", "send_pending", "test_notification", "pause", "resume"):
        hass.services.async_remove(DOMAIN, service)
