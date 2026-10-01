"""Shared notification destination validation."""

from __future__ import annotations

import re

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_TARGET_RE = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")


def notification_target(value: str, hass: HomeAssistant | None = None) -> str:
    """Normalize a service or notify entity and reject recursive destinations."""
    if not isinstance(value, str):
        raise vol.Invalid("A notification destination must be a string")
    value = value.strip().lower()
    if not _TARGET_RE.fullmatch(value):
        raise vol.Invalid("Use domain.service or a notify entity ID")
    if value.startswith(f"{DOMAIN}.") or value == "notify.send_message":
        raise vol.Invalid("Choose a destination, not the notification routing service")
    if hass is not None:
        entity = er.async_get(hass).async_get(value)
        if entity is not None and entity.platform == DOMAIN:
            raise vol.Invalid("This integration's notify entities cannot be destinations")
    return value


def mobile_target(value: str, hass: HomeAssistant) -> str:
    """Accept Companion App services and registered Companion notify entities."""
    value = notification_target(value)
    entity = er.async_get(hass).async_get(value)
    if entity is not None:
        if entity.domain == "notify" and entity.platform == "mobile_app":
            return value
        raise vol.Invalid("Choose a Companion App notification destination")
    if not value.startswith("notify.mobile_app_"):
        raise vol.Invalid("Choose a Companion App notification destination")
    return value
