"""Constants for Smart Presence Notify."""
from __future__ import annotations

from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "smart_presence_notify"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

STORE_KEY = "smart_presence_notify"
STORE_VERSION = 1

# Config entry keys
CONF_TARGET_MODE = "target_mode"
CONF_QUEUE_MODE = "queue_mode"
CONF_QUEUE_TIMEOUT = "queue_timeout_minutes"
CONF_FALLBACK_MODE = "fallback_mode"
CONF_FALLBACK_SERVICE = "fallback_service"
CONF_PERSONS = "persons"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_IS_ADMIN = "is_admin"
CONF_ADMIN_PERSON = "admin_person"


class TargetMode(StrEnum):
    BROADCAST = "broadcast"
    SINGLE_ADMIN = "single_admin"
    CALLER_DECIDES = "caller_decides"


class QueueMode(StrEnum):
    LAST_ONLY = "last_only"
    FIFO = "fifo"
    SUMMARY = "summary"


class FallbackMode(StrEnum):
    DISCARD = "discard"
    NOTIFY_FALLBACK = "notify_fallback"


class Priority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
