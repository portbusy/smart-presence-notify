"""Shared fixtures for Smart Presence Notify tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

DOMAIN = "smart_presence_notify"


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
