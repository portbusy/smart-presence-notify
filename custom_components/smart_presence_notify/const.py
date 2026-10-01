"""Constants for Smart Presence Notify."""
from __future__ import annotations

from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "smart_presence_notify"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

EVENT_MOBILE_APP_NOTIFICATION_ACTION = "mobile_app_notification_action"
EVENT_RESPONSE = f"{DOMAIN}_response"

RESPONSE_PRESET_YES_NO = "yes_no"

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
CONF_QUEUE_LIMIT = "queue_limit"
CONF_FORWARD_SOURCES = "forward_sources"
CONF_FORWARD_ENABLED = "forward_enabled"
CONF_FORWARD_TARGETS = "forward_targets"
CONF_FORWARD_ID_PATTERNS = "forward_id_patterns"
CONF_FORWARD_TEXT = "forward_text"
CONF_FORWARD_UPDATES = "forward_updates"

DEFAULT_QUEUE_LIMIT = 100
MAX_QUEUE_LIMIT = 1000
QUEUE_PREVIEW_LIMIT = 20
MAX_DELIVERY_ATTEMPTS = 5
RETRY_BASE_SECONDS = 30
SERVICE_TIMEOUT_SECONDS = 30
RESPONSE_TIMEOUT_HOURS = 24
MAX_RESPONSE_TOKENS = 4096


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
