"""Sensor entities for Smart Presence Notify."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_DELIVERY_ATTEMPTS, QUEUE_PREVIEW_LIMIT
from .coordinator import SmartPresenceNotifyCoordinator
from .models import CoordinatorData
from .runtime import SNPRuntimeData
from .queue_status import explain_queue_item


@dataclass(frozen=True, kw_only=True)
class SNPSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], StateType]
    extra_fn: Callable[[CoordinatorData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[SNPSensorDescription, ...] = (
    SNPSensorDescription(
        key="delivery_status",
        translation_key="delivery_status",
        icon="mdi:bell-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["ready", "waiting", "retrying", "failed"],
        value_fn=lambda data: (
            "failed"
            if any(n.attempts >= MAX_DELIVERY_ATTEMPTS for n in data.queue)
            else "retrying"
            if any(n.attempts for n in data.queue)
            else "waiting"
            if data.queue
            else "ready"
        ),
        extra_fn=lambda data: {
            "last_error": data.last_error,
            "failed_recipients": data.failed_recipients,
            "last_test": data.last_test,
            "silence_reason": data.silence_reason,
        },
    ),
    SNPSensorDescription(
        key="home_persons",
        translation_key="home_persons",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="persons",
        value_fn=lambda data: len(data.home_persons),
        extra_fn=lambda data: {"persons": data.home_persons},
    ),
    SNPSensorDescription(
        key="queue_count",
        translation_key="queue_count",
        icon="mdi:bell-badge",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="notifications",
        value_fn=lambda data: len(data.queue),
        extra_fn=lambda data: {
            "queue": [
                {
                    "id": n.id,
                    "notification_key": n.notification_key,
                    "title": n.title[:255],
                    "pending_targets": n.targets,
                    "attempts": n.attempts,
                    "retry_at": n.retry_at.isoformat() if n.retry_at else None,
                    "priority": n.priority,
                    "expires_at": n.expires_at.isoformat() if n.expires_at else None,
                }
                for n in data.queue[:QUEUE_PREVIEW_LIMIT]
            ],
            "preview_truncated": len(data.queue) > QUEUE_PREVIEW_LIMIT,
        },
    ),
    SNPSensorDescription(
        key="last_sent",
        translation_key="last_sent",
        icon="mdi:bell-check",
        state_class=None,
        value_fn=lambda data: data.last_sent.title[:255] if data.last_sent else None,
        extra_fn=lambda data: (
            {
                "sent_at": data.last_sent.sent_at.isoformat(),
                "title": data.last_sent.title,
                "message": data.last_sent.message,
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
            name=entry.title,
            manufacturer="Smart Presence Notify",
        )

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self.entity_description.extra_fn is None:
            return None
        attributes = self.entity_description.extra_fn(self.coordinator.data)
        if self.entity_description.key in ("queue_count", "delivery_status"):
            settings = self.coordinator.config_entry.data
            attributes.update({
                "paused_until": settings.get("paused_until"),
                "quiet_hours_enabled": settings.get("quiet_hours_enabled", False),
                "quiet_hours_start": settings.get("quiet_hours_start", "22:00:00"),
                "quiet_hours_end": settings.get("quiet_hours_end", "08:00:00"),
                "high_priority_bypasses_silence": self.coordinator.data.high_priority_bypasses_silence,
            })
        if self.entity_description.key == "queue_count":
            now = dt_util.utcnow()
            for preview, item in zip(
                attributes["queue"], self.coordinator.data.queue[:QUEUE_PREVIEW_LIMIT]
            ):
                preview.update(explain_queue_item(
                    item, self.coordinator.data, now, self.hass.config.language
                ))
        return attributes
