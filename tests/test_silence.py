"""Quiet periods retain deliveries and resume without consuming retries."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.smart_presence_notify.coordinator import SmartPresenceNotifyCoordinator
from custom_components.smart_presence_notify.silence import silence_reason
from tests.test_reliability import make_coordinator


async def test_local_quiet_hours_and_dst(hass):
    await hass.config.async_set_time_zone("Europe/Rome")
    settings = {"quiet_hours_enabled": True, "quiet_hours_start": "22:00", "quiet_hours_end": "08:00"}
    assert silence_reason(settings, datetime(2026, 10, 20, 20, tzinfo=timezone.utc)) == "quiet_hours"
    assert silence_reason(settings, datetime(2026, 10, 20, 6, tzinfo=timezone.utc)) is None
    # Both occurrences of 02:30 during the autumn clock change remain quiet.
    for hour in (0, 1):
        assert silence_reason(settings, datetime(2026, 10, 25, hour, 30, tzinfo=timezone.utc)) == "quiet_hours"
    assert silence_reason(settings, datetime(2026, 10, 25, 7, tzinfo=timezone.utc)) is None
    daytime = {**settings, "quiet_hours_start": "12:00", "quiet_hours_end": "14:00"}
    assert silence_reason(daytime, datetime(2026, 10, 20, 11, tzinfo=timezone.utc)) == "quiet_hours"
    assert silence_reason(daytime, datetime(2026, 10, 20, 12, tzinfo=timezone.utc)) is None


async def test_pause_retains_messages_and_releases_on_timer(hass):
    with freeze_time("2026-10-20 12:00:00+00:00", real_asyncio=True) as clock:
        hass.states.async_set("person.mario", "home")
        coord = await make_coordinator(hass)
        deliver = AsyncMock()
        hass.services.async_register("notify", "mobile_app_mario", deliver)
        await coord.async_pause(1)
        await coord.async_send_notification("Normal", "Body")
        assert coord.data.silence_reason == "paused"
        assert coord.data.queue[0].attempts == 0
        deliver.assert_not_called()
        clock.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        deliver.assert_awaited_once()
        assert not coord.data.queue
        assert coord.data.silence_reason is None
        await coord.async_shutdown()


@pytest.mark.parametrize("bypass", [False, True])
async def test_high_priority_policy(hass, bypass):
    hass.states.async_set("person.mario", "home")
    coord = await make_coordinator(hass, high_priority_bypasses_silence=bypass)
    deliver = AsyncMock()
    hass.services.async_register("notify", "mobile_app_mario", deliver)
    await coord.async_pause(60)
    await coord.async_send_notification("Urgent", "Body", priority="high")
    assert deliver.call_count == int(bypass)
    assert len(coord.data.queue) == int(not bypass)
    await coord.async_shutdown()


async def test_forwarding_retry_and_expiry_respect_pause(hass):
    coord = await make_coordinator(hass, fallback_mode="notify_fallback", fallback_service="notify.phone")
    deliver = AsyncMock()
    hass.services.async_register("notify", "phone", deliver)
    await coord.async_pause(60)
    await coord.async_forward_notification("Bell", "Body", ["notify.phone"], {})
    item = coord.data.queue[0]
    coord._update(replace(item, expires_at=item.created_at - timedelta(seconds=1)))
    await coord._process_one(item.id)
    assert coord.data.queue[0].expired
    assert coord.data.queue[0].attempts == 0
    assert (await coord._store.async_load())[0].expired
    deliver.assert_not_called()
    await coord.async_retry_pending()
    deliver.assert_not_called()
    await coord.async_resume()
    deliver.assert_awaited_once()
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_pause_restores_and_manual_send_is_blocked(hass):
    coord = await make_coordinator(hass)
    await coord.async_pause(60)
    await coord.async_send_notification("Waiting", "Body")
    entry = coord.config_entry
    await coord.async_shutdown()
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()
    await hass.async_block_till_done()
    assert coord.data.silence_reason == "paused"
    with pytest.raises(ServiceValidationError, match="silenced"):
        await coord.async_send_pending(coord.data.queue[0].id, ["notify.phone"])
    assert coord.data.queue[0].attempts == 0
    await coord.async_shutdown()
    assert coord._pause_unsub is None


async def test_summary_does_not_bypass_quiet_hours_and_resume_keeps_schedule(hass):
    await hass.config.async_set_time_zone("Europe/Rome")
    with freeze_time("2026-10-20 21:00:00+00:00", tick=True) as clock:
        coord = await make_coordinator(hass, queue_mode="summary", quiet_hours_enabled=True,
                                       quiet_hours_start="22:00", quiet_hours_end="08:00")
        await coord.async_send_notification("First", "Body")
        await coord.async_send_notification("Second", "Body")
        hass.states.async_set("person.mario", "home")
        deliver = AsyncMock()
        hass.services.async_register("notify", "mobile_app_mario", deliver)
        await hass.async_block_till_done()
        await coord.async_pause(60)
        await coord.async_resume()
        assert coord.data.silence_reason == "quiet_hours"
        deliver.assert_not_called()
        clock.move_to("2026-10-21 06:00:00+00:00")
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        deliver.assert_awaited_once()
        assert "2 messages" in deliver.call_args.args[0].data["message"]
        assert not coord.data.queue
        await coord.async_shutdown()


async def test_quiet_hours_options_and_pause_services(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "quiet_hours"})
    settings = {"quiet_hours_enabled": True, "quiet_hours_start": "22:00:00", "quiet_hours_end": "22:00:00", "high_priority_bypasses_silence": False}
    invalid = await hass.config_entries.options.async_configure(flow["flow_id"], settings)
    assert invalid["errors"]["base"] == "invalid_quiet_hours"
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {**settings, "quiet_hours_end": "08:00:00"})
    assert result["type"] == "create_entry"
    await hass.services.async_call("smart_presence_notify", "pause", {"minutes": 30}, blocking=True)
    assert mock_config_entry.data["paused_until"]
    assert mock_config_entry.data["quiet_hours_enabled"]
    await hass.services.async_call("smart_presence_notify", "resume", {}, blocking=True)
    assert mock_config_entry.data["paused_until"] is None
    assert mock_config_entry.data["quiet_hours_enabled"]
