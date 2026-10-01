"""Configuration switch for mobile forwarding of bell notifications."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FORWARD_ENABLED,
    CONF_FORWARD_ID_PATTERNS,
    CONF_FORWARD_SOURCES,
    CONF_FORWARD_TARGETS,
    DOMAIN,
)
from .validation import mobile_target


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([ForwardingSwitch(entry.runtime_data.coordinator)])


class ForwardingSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "forward_notifications"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bell-arrow-right"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_forward_notifications"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Smart Presence Notify",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.config_entry.data.get(CONF_FORWARD_ENABLED, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        settings = self.coordinator.config_entry.data
        targets = settings.get(CONF_FORWARD_TARGETS, [])
        try:
            if not targets:
                raise vol.Invalid(
                    "Configure at least one mobile destination in integration options"
                )
            if (
                CONF_FORWARD_SOURCES in settings
                and not settings[CONF_FORWARD_SOURCES]
                and not settings.get(CONF_FORWARD_ID_PATTERNS)
            ):
                raise vol.Invalid(
                    "Select at least one notification source in integration options"
                )
            for target in targets:
                mobile_target(target, self.hass)
        except vol.Invalid as err:
            raise ServiceValidationError(str(err)) from err
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FORWARD_ENABLED: enabled}
        )
        self.async_write_ha_state()
