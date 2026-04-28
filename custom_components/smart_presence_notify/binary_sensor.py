"""Binary sensor entities for Smart Presence Notify."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartPresenceNotifyCoordinator
from .models import SNPRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: SNPRuntimeData = entry.runtime_data
    async_add_entities([SNPSomeoneHomeSensor(runtime.coordinator, entry)])


class SNPSomeoneHomeSensor(
    CoordinatorEntity[SmartPresenceNotifyCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_name = "Someone Home"
    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_icon = "mdi:home-account"

    def __init__(
        self,
        coordinator: SmartPresenceNotifyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_someone_home"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Smart Presence Notify",
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.someone_home

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return {"home_persons": self.coordinator.data.home_persons}
