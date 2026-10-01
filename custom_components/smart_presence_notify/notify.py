"""Standard notify entry point for presence-aware delivery."""

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([PresenceNotifyEntity(entry.runtime_data.coordinator)])


class PresenceNotifyEntity(CoordinatorEntity, NotifyEntity):
    """Route standard title/message notifications through this configuration."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_notify"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Smart Presence Notify",
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        await self.coordinator.async_send_notification(
            title if title is not None else self.coordinator.config_entry.title,
            message,
        )
