"""Persistent queue storage for Smart Presence Notify."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION
from .models import PendingNotification

_LOGGER = logging.getLogger(__name__)


class SNPStore:
    """Wraps HA Store for PendingNotification queue."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[list[dict[str, Any]]] = Store(hass, STORE_VERSION, STORE_KEY)

    async def async_load(self) -> list[PendingNotification]:
        data = await self._store.async_load()
        if not data:
            return []
        if not isinstance(data, list):
            _LOGGER.warning("Ignoring malformed notification queue in storage")
            return []
        loaded: list[PendingNotification] = []
        seen = set()
        for item in data:
            try:
                notification = PendingNotification.from_dict(item)
                if notification.id not in seen:
                    loaded.append(notification)
                    seen.add(notification.id)
            except (KeyError, ValueError, TypeError, vol.Invalid) as err:
                _LOGGER.warning("Skipping malformed notification in storage: %s", err)
        return loaded

    async def async_save(self, queue: list[PendingNotification]) -> None:
        await self._store.async_save([n.to_dict() for n in queue])

    async def async_remove(self) -> None:
        await self._store.async_remove()
