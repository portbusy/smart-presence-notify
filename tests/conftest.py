"""Shared fixtures for Smart Presence Notify tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

DOMAIN = "smart_presence_notify"

_DEFAULT_PERSONS_MARIO_ONLY = {
    "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True},
}


def make_entry(
    *,
    queue_mode: str = "fifo",
    queue_timeout_minutes: int = 0,
    fallback_mode: str = "discard",
    fallback_service: str = "",
    target_mode: str = "broadcast",
    persons: dict | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": target_mode,
            "queue_mode": queue_mode,
            "queue_timeout_minutes": queue_timeout_minutes,
            "fallback_mode": fallback_mode,
            "fallback_service": fallback_service,
            "persons": persons if persons is not None else _DEFAULT_PERSONS_MARIO_ONLY,
        },
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Smart Presence Notify",
        data={
            "name": "Smart Presence Notify",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {
                    "notify_services": ["notify.mobile_app_mario"],
                    "is_admin": True,
                },
                "person.lucia": {
                    "notify_services": ["notify.mobile_app_lucia"],
                    "is_admin": False,
                },
            },
        },
    )


@pytest.fixture
def mock_notify_call(hass: HomeAssistant):
    """Patch hass.services.async_call and return the mock."""
    with patch.object(hass.services, "async_call") as mock_call:
        yield mock_call
