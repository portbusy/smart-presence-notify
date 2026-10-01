"""Shared notification destination validation."""

from __future__ import annotations

import re

import voluptuous as vol

from .const import DOMAIN

_TARGET_RE = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")


def notification_target(value: str) -> str:
    """Normalize a service or notify entity and reject recursive destinations."""
    if not isinstance(value, str):
        raise vol.Invalid("A notification destination must be a string")
    value = value.strip().lower()
    if not _TARGET_RE.fullmatch(value):
        raise vol.Invalid("Use domain.service or a notify entity ID")
    if value.startswith(f"{DOMAIN}.") or value == "notify.send_message":
        raise vol.Invalid("Choose a destination, not the notification routing service")
    return value


def mobile_target(value: str) -> str:
    """Only direct Companion App services may receive forwarded notifications."""
    value = notification_target(value)
    if not value.startswith("notify.mobile_app_"):
        raise vol.Invalid("Choose a notify.mobile_app_* service")
    return value
