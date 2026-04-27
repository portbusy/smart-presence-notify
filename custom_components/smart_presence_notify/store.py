"""Persistent queue storage for Smart Presence Notify."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION
from .models import PendingNotification

_LOGGER = logging.getLogger(__name__)


class SNPStore:
    """Wraps HA Store for PendingNotification queue."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)

    async def async_load(self) -> list[PendingNotification]:
        data = await self._store.async_load()
        if not data:
            return []
        loaded: list[PendingNotification] = []
        for item in data:
            try:
                loaded.append(PendingNotification.from_dict(item))
            except (KeyError, ValueError, TypeError) as err:
                _LOGGER.warning("Skipping malformed notification in storage: %s", err)
        return loaded

    async def async_save(self, queue: list[PendingNotification]) -> None:
        await self._store.async_save([n.to_dict() for n in queue])
