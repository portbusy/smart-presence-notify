"""Tests for SmartPresenceNotifyCoordinator."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.smart_presence_notify.const import DOMAIN
from custom_components.smart_presence_notify.coordinator import (
    SmartPresenceNotifyCoordinator,
)


@pytest.fixture
async def coordinator(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    return coord


async def test_someone_home_when_person_is_home(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is True
    assert "person.mario" in coord.data.home_persons


async def test_nobody_home_when_all_away(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is False
    assert coord.data.home_persons == []


async def test_presence_updates_on_state_change(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    assert coord.data.someone_home is False
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert coord.data.someone_home is True


async def test_send_broadcast_to_home_persons(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    # Register mock service for mario
    calls = async_mock_service(hass, "notify", "mobile_app_mario")

    await coord.async_send_notification("Door", "Open", priority="normal")

    # Verify service was called with correct data
    assert len(calls) == 1
    assert calls[0].data["title"] == "Door"
    assert calls[0].data["message"] == "Open"

    # Verify coordinator recorded the sent notification
    assert coord.data.last_sent.title == "Door"
    assert coord.data.last_sent.recipients == ["notify.mobile_app_mario"]


async def test_send_target_override(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    # Register mock service for telegram
    calls = async_mock_service(hass, "notify", "telegram")

    await coord.async_send_notification(
        "Test", "Msg", target_override="notify.telegram"
    )

    # Verify service was called with correct data
    assert len(calls) == 1
    assert calls[0].data["title"] == "Test"
    assert calls[0].data["message"] == "Msg"


async def test_high_priority_bypasses_queue_sends_to_first_home(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    # Register mock service for mario
    calls = async_mock_service(hass, "notify", "mobile_app_mario")

    await coord.async_send_notification("Alert", "Fire!", priority="high")

    # Verify service was called
    assert len(calls) == 1
    assert calls[0].data["title"] == "Alert"
    assert calls[0].data["message"] == "Fire!"

    # Verify queue is empty (high priority bypasses queue)
    assert coord.data.queue == []


async def test_normal_priority_nobody_home_enqueues(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    # Register mock services (to verify they are NOT called)
    mario_calls = async_mock_service(hass, "notify", "mobile_app_mario")
    lucia_calls = async_mock_service(hass, "notify", "mobile_app_lucia")

    await coord.async_send_notification("Door", "Open")

    # Verify no services were called (nobody home, normal priority enqueues)
    assert len(mario_calls) == 0
    assert len(lucia_calls) == 0

    # Verify notification was enqueued
    assert len(coord.data.queue) == 1
    assert coord.data.queue[0].title == "Door"


async def test_high_priority_nobody_home_uses_fallback(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "notify_fallback",
            "fallback_service": "notify.telegram",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    # Register mock service for telegram fallback
    calls = async_mock_service(hass, "notify", "telegram")

    await coord.async_send_notification("Alert", "Fire!", priority="high")

    # Verify fallback service was called with correct data
    assert len(calls) == 1
    assert calls[0].data["title"] == "Alert"
    assert calls[0].data["message"] == "Fire!"
    # High priority + fallback must NOT enqueue
    assert coord.data.queue == []
    assert coord.data.last_sent is not None
    assert coord.data.last_sent.recipients == ["notify.telegram"]


async def test_drain_fifo_on_arrival(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    # Enqueue two notifications
    await coord.async_send_notification("Msg1", "Body1")
    await coord.async_send_notification("Msg2", "Body2")
    assert len(coord.data.queue) == 2

    # Register notify service for mario
    calls = async_mock_service(hass, "notify", "mobile_app_mario")

    # Mario arrives home — should drain FIFO
    with patch("asyncio.sleep", new_callable=AsyncMock):
        hass.states.async_set("person.mario", "home")
        await hass.async_block_till_done()

    assert coord.data.queue == []
    assert len(calls) == 2
    assert calls[0].data["title"] == "Msg1"
    assert calls[1].data["title"] == "Msg2"


async def test_drain_last_only_on_arrival(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "last_only",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    await coord.async_send_notification("First", "B1")
    await coord.async_send_notification("Last", "B2")

    calls = async_mock_service(hass, "notify", "mobile_app_mario")

    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["title"] == "Last"
    assert calls[0].data["message"] == "B2"
    assert coord.data.queue == []
    assert coord.data.last_sent is not None
    assert coord.data.last_sent.title == "Last"


async def test_drain_summary_on_arrival(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "summary",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    await coord.async_send_notification("Door", "Open")
    await coord.async_send_notification("Window", "Open")

    calls = async_mock_service(hass, "notify", "mobile_app_mario")

    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert "2 messages" in calls[0].data["message"]
    assert "Door" in calls[0].data["message"]
    assert "Window" in calls[0].data["message"]
    assert calls[0].data["title"] == "Missed notifications"
    assert coord.data.queue == []
    assert coord.data.last_sent is not None
    assert coord.data.last_sent.title == "Missed notifications"


async def test_notification_expires_discard(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 60,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    await coord.async_send_notification("Temp", "Body")
    assert len(coord.data.queue) == 1
    notif = coord.data.queue[0]
    assert notif.expires_at is not None

    # Directly trigger expiry (bypasses time-based scheduling)
    await coord._async_expire_notification(notif)

    assert coord.data.queue == []
    # Discard mode must NOT record a last_sent
    assert coord.data.last_sent is None


async def test_notification_expires_with_fallback(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 60,
            "fallback_mode": "notify_fallback",
            "fallback_service": "notify.telegram",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    await coord.async_send_notification("Alert", "Body")
    notif = coord.data.queue[0]

    calls = async_mock_service(hass, "notify", "telegram")
    await coord._async_expire_notification(notif)

    assert len(calls) == 1
    assert calls[0].data["title"] == "Alert"
    assert calls[0].data["message"] == "Body"
    assert coord.data.queue == []


async def test_drain_skipped_when_arrived_person_has_no_notify_services(hass):
    """Queue must not be drained when arrived person has no notify_services."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                # Mario has notify services, Guest is configured but has none
                "person.mario": {
                    "notify_services": ["notify.mobile_app_mario"],
                    "is_admin": True,
                },
                "person.guest": {"notify_services": [], "is_admin": False},
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.guest", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    await coord.async_send_notification("Door", "Open")
    assert len(coord.data.queue) == 1

    # Guest arrives — must NOT drain (no notify services)
    mario_calls = async_mock_service(hass, "notify", "mobile_app_mario")
    hass.states.async_set("person.guest", "home")
    await hass.async_block_till_done()

    assert len(mario_calls) == 0
    assert len(coord.data.queue) == 1


async def test_queue_persists_across_reinit(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)

    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    await coord.async_send_notification("Persist", "Me")
    assert len(coord.data.queue) == 1

    # Simulate restart by creating a new coordinator with same hass/entry
    coord2 = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord2.async_initialize()

    assert len(coord2.data.queue) == 1
    assert coord2.data.queue[0].title == "Persist"
