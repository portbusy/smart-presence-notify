"""Forward selected persistent notifications through the public HA callback."""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from hashlib import sha256
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_FORWARD_ENABLED,
    CONF_FORWARD_TARGETS,
    CONF_FORWARD_TEXT,
    CONF_FORWARD_UPDATES,
)
from .validation import mobile_target

if TYPE_CHECKING:
    from .coordinator import SmartPresenceNotifyCoordinator


class NotificationForwarder:
    """Observe added/updated notifications; never replay existing notifications."""

    def __init__(self, coordinator: SmartPresenceNotifyCoordinator) -> None:
        self.coordinator = coordinator
        self._seen: OrderedDict[str, bytes] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_users: dict[str, int] = {}

    def async_start(self):
        return persistent_notification.async_register_callback(
            self.coordinator.hass, self._handle_update
        )

    @callback
    def _handle_update(self, update_type, notifications) -> None:
        kind = update_type.value
        if kind == "removed":
            for notification_id in notifications:
                self._seen.pop(notification_id, None)
            return
        if kind not in ("added", "updated", "current"):
            return
        self.coordinator.notification_sources.async_observe(notifications)
        if kind == "current":
            return
        settings = self.coordinator.config_entry.data
        if not settings.get(CONF_FORWARD_ENABLED, False):
            return
        try:
            targets = list(
                dict.fromkeys(
                    mobile_target(t) for t in settings.get(CONF_FORWARD_TARGETS, [])
                )
            )
        except vol.Invalid:
            self.coordinator._set_error(
                "Invalid mobile notification forwarding destination", []
            )
            return
        if not targets:
            return
        text = settings.get(CONF_FORWARD_TEXT, "").casefold()
        for notification_id, notification in notifications.items():
            title, message = (
                notification.get("title") or "Home Assistant",
                notification["message"],
            )
            fingerprint = sha256((title + "\0" + message).encode()).digest()
            previous = self._seen.get(notification_id)
            if (
                previous == fingerprint
                or (previous is not None or kind == "updated")
                and not settings.get(CONF_FORWARD_UPDATES, True)
            ):
                continue
            if not self.coordinator.notification_sources.matches(
                notification_id, settings
            ):
                continue
            if text and text not in (title + "\n" + message).casefold():
                continue
            self._seen[notification_id] = fingerprint
            self._seen.move_to_end(notification_id)
            while len(self._seen) > 500:
                self._seen.popitem(last=False)
            self.coordinator._start_task(
                self._forward(notification_id, title, message, fingerprint, targets)
            )

    async def _forward(
        self,
        notification_id: str,
        title: str,
        message: str,
        fingerprint: bytes,
        targets: list[str],
    ) -> None:
        lock = self._locks.setdefault(notification_id, asyncio.Lock())
        self._lock_users[notification_id] = self._lock_users.get(notification_id, 0) + 1
        try:
            async with lock:
                # Dreame embeds base64 images; these cannot fit a mobile push payload.
                message = re.sub(r"!\[[^\]]*\]\(data:[^)]*\)", "", message)
                message = message.encode()[:3000].decode("utf-8", errors="ignore")
                title = title.encode()[:255].decode("utf-8", errors="ignore")
                await self.coordinator.async_forward_notification(
                    title,
                    message,
                    targets,
                    {"tag": "smart_presence_notify_" + notification_id},
                )
        except HomeAssistantError:
            if self._seen.get(notification_id) == fingerprint:
                self._seen.pop(notification_id, None)
        finally:
            self._lock_users[notification_id] -= 1
            if not self._lock_users[notification_id]:
                self._lock_users.pop(notification_id)
                self._locks.pop(notification_id)
