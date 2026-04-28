"""Sensor entities for Smart Presence Notify."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartPresenceNotifyCoordinator
from .models import CoordinatorData, SNPRuntimeData


@dataclass(frozen=True, kw_only=True)
class SNPSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], StateType]
    extra_fn: Callable[[CoordinatorData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[SNPSensorDescription, ...] = (
    SNPSensorDescription(
        key="queue_count",
        name="Queue Count",
        icon="mdi:bell-badge",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="notifications",
        value_fn=lambda data: len(data.queue),
        extra_fn=lambda data: {
            "queue": [
                {
                    "id": n.id,
                    "title": n.title,
                    "priority": n.priority,
                    "expires_at": n.expires_at.isoformat() if n.expires_at else None,
                }
                for n in data.queue
            ]
        },
    ),
    SNPSensorDescription(
        key="last_sent",
        name="Last Sent",
        icon="mdi:bell-check",
        value_fn=lambda data: data.last_sent.title if data.last_sent else None,
        extra_fn=lambda data: (
            {
                "sent_at": data.last_sent.sent_at.isoformat(),
                "recipients": data.last_sent.recipients,
                "priority": data.last_sent.priority,
            }
            if data.last_sent
            else {}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: SNPRuntimeData = entry.runtime_data
    async_add_entities(
        SNPSensorEntity(runtime.coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    )


class SNPSensorEntity(CoordinatorEntity[SmartPresenceNotifyCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: SNPSensorDescription

    def __init__(
        self,
        coordinator: SmartPresenceNotifyCoordinator,
        description: SNPSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get("name", "Smart Presence Notify"),
            manufacturer="Smart Presence Notify",
        )

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_fn:
            return self.entity_description.extra_fn(self.coordinator.data)
        return None
