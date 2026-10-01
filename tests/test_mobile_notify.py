"""Companion notify entities in the bell-forwarding selector and delivery path."""

import pytest
import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import CONF_FORWARD_TARGETS
from custom_components.smart_presence_notify.mobile import (
    mobile_options,
    mobile_targets,
)
from custom_components.smart_presence_notify.validation import mobile_target
from tests.test_reliability import make_coordinator
from tests.test_sources import forwarding_form


def register_notify_entity(hass, platform="mobile_app", name="renamed_phone"):
    entity = er.async_get(hass).async_get_or_create(
        "notify", platform, name, suggested_object_id=name
    )
    hass.states.async_set(entity.entity_id, "unknown")
    return entity.entity_id


async def test_forwarding_selector_accepts_renamed_companion_entity(
    hass, mock_config_entry
):
    phone = register_notify_entity(hass)
    other = register_notify_entity(hass, "file", "other_provider")
    hass.services.async_register("notify", "mobile_app_old_phone", lambda call: None)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    form = await forwarding_form(hass, mock_config_entry)
    options = [
        option["value"]
        for option in form["data_schema"].schema[CONF_FORWARD_TARGETS].config["options"]
    ]
    assert phone in options
    assert "notify.mobile_app_old_phone" in options
    assert other not in options
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={
            "forward_enabled": True,
            "forward_targets": [phone, "notify.mobile_app_old_phone", phone],
            "forward_sources": ["all"],
            "forward_id_patterns": [],
            "forward_text": "",
            "forward_updates": True,
        },
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.data[CONF_FORWARD_TARGETS] == [
        phone,
        "notify.mobile_app_old_phone",
    ]


@pytest.mark.parametrize("name", ["other_phone", "mobile_app_impostor"])
async def test_registry_provider_rejects_other_notify_entities(hass, name):
    other = register_notify_entity(hass, "file", name)
    with pytest.raises(vol.Invalid):
        mobile_target(other, hass)
    with pytest.raises(vol.Invalid):
        mobile_target("notify.unregistered_phone", hass)


async def test_bell_forwards_to_modern_and_legacy_companion(hass):
    phone = register_notify_entity(hass)
    modern, legacy = [], []
    hass.services.async_register(
        "notify", "send_message", lambda call: modern.append(call.data)
    )
    hass.services.async_register(
        "notify", "mobile_app_old_phone", lambda call: legacy.append(call.data)
    )
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_sources=["all"],
        forward_targets=[phone, "notify.mobile_app_old_phone"],
    )
    persistent_notification.async_create(hass, "Body", "Vacuum", "dreame_error")
    await hass.async_block_till_done()
    assert modern == [{"title": "Vacuum", "message": "Body", "entity_id": phone}]
    assert legacy[0]["message"] == "Body"
    assert legacy[0]["data"]["tag"] == "smart_presence_notify_dreame_error"
    assert not coord.data.queue
    await coord.async_shutdown()


def registered_phone(hass, registration_name="Phone Davide", unique_id="davide"):
    entry = MockConfigEntry(
        domain="mobile_app",
        title=registration_name,
        data={"device_name": registration_name},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("mobile_app", unique_id)},
        name=registration_name,
    )
    dr.async_get(hass).async_update_device(device.id, name_by_user="Telefono personale")
    entity = er.async_get(hass).async_get_or_create(
        "notify",
        "mobile_app",
        unique_id,
        suggested_object_id=unique_id,
        config_entry=entry,
        device_id=device.id,
    )
    renamed = er.async_get(hass).async_update_entity(
        entity.entity_id, new_entity_id=f"notify.renamed_{unique_id}"
    )
    hass.states.async_set(renamed.entity_id, "unknown")
    return renamed.entity_id


async def test_phone_choice_prefers_service_and_deduplicates_aliases(hass):
    phone = registered_phone(hass)
    service = "notify.mobile_app_phone_davide"
    hass.services.async_register("notify", "mobile_app_phone_davide", lambda call: None)
    assert mobile_options(hass, [phone, service]) == [
        {"value": service, "label": "Telefono personale"}
    ]
    assert mobile_targets(hass, [phone, service, phone]) == [service]
    hass.services.async_remove("notify", "mobile_app_phone_davide")
    assert mobile_targets(hass, [service, phone]) == [phone]
    assert mobile_options(hass, [service]) == [
        {"value": phone, "label": "Telefono personale"}
    ]


async def test_ambiguous_registration_names_are_not_merged(hass):
    first = registered_phone(hass)
    second = registered_phone(hass, unique_id="second")
    service = "notify.mobile_app_phone_davide"
    hass.services.async_register("notify", "mobile_app_phone_davide", lambda call: None)
    assert mobile_targets(hass, [first, second, service]) == [first, second, service]
    assert {o["value"] for o in mobile_options(hass, [])} == {first, second, service}


async def test_saved_both_channels_forward_only_once_using_advanced_service(hass):
    phone = registered_phone(hass)
    modern, legacy = [], []
    hass.services.async_register(
        "notify", "send_message", lambda call: modern.append(call.data)
    )
    hass.services.async_register(
        "notify", "mobile_app_phone_davide", lambda call: legacy.append(call.data)
    )
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_sources=["all"],
        forward_targets=[phone, "notify.mobile_app_phone_davide"],
    )
    persistent_notification.async_create(hass, "Body", "Vacuum", "dreame_error")
    await hass.async_block_till_done()
    assert not modern
    assert len(legacy) == 1
    assert legacy[0]["data"]["tag"] == "smart_presence_notify_dreame_error"
    await coord.async_shutdown()


async def test_offline_saved_service_remains_selectable(hass):
    assert mobile_options(hass, ["notify.mobile_app_offline_phone"]) == [
        {"value": "notify.mobile_app_offline_phone", "label": "offline phone"}
    ]


async def test_form_migrates_saved_entity_to_one_named_phone(hass, mock_config_entry):
    phone = registered_phone(hass)
    service = "notify.mobile_app_phone_davide"
    hass.services.async_register("notify", "mobile_app_phone_davide", lambda call: None)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "forward_targets": [phone, service]},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    form = await forwarding_form(hass, mock_config_entry)
    marker = next(
        key for key in form["data_schema"].schema if key == CONF_FORWARD_TARGETS
    )
    assert marker.default() == [service]
    selector = form["data_schema"].schema[marker]
    assert selector.config["options"] == [
        {"value": service, "label": "Telefono personale"}
    ]
    assert selector.config["custom_value"] is False


async def test_saved_service_uses_modern_entity_if_service_is_absent(hass):
    phone = registered_phone(hass)
    calls = []
    hass.services.async_register(
        "notify", "send_message", lambda call: calls.append(call.data)
    )
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_sources=["all"],
        forward_targets=["notify.mobile_app_phone_davide"],
    )
    persistent_notification.async_create(hass, "Body", "Vacuum", "dreame_error")
    await hass.async_block_till_done()
    assert calls == [{"title": "Vacuum", "message": "Body", "entity_id": phone}]
    assert not coord.data.queue
    await coord.async_shutdown()


async def test_switch_can_enable_modern_companion_forwarding(hass, mock_config_entry):
    phone = register_notify_entity(hass)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **mock_config_entry.data,
            "forward_targets": [phone],
            "forward_sources": ["all"],
            "forward_enabled": False,
        },
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    switch = hass.states.async_entity_ids("switch")[0]
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    assert mock_config_entry.data["forward_enabled"] is True
    assert hass.states.get(switch).state == "on"


async def test_failed_modern_forward_is_retried_without_repeating_legacy(hass):
    phone = register_notify_entity(hass)
    legacy = []

    async def offline(call):
        raise HomeAssistantError("phone offline")

    hass.services.async_register("notify", "send_message", offline)
    hass.services.async_register(
        "notify", "mobile_app_old_phone", lambda call: legacy.append(call.data)
    )
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_sources=["all"],
        forward_targets=[phone, "notify.mobile_app_old_phone"],
    )
    persistent_notification.async_create(hass, "Body", "Vacuum", "dreame_error")
    await hass.async_block_till_done()
    assert coord.data.queue[0].targets == [phone]
    modern = []
    hass.services.async_register(
        "notify", "send_message", lambda call: modern.append(call.data)
    )
    await coord.async_retry_pending()
    assert modern == [{"title": "Vacuum", "message": "Body", "entity_id": phone}]
    assert len(legacy) == 1
    assert not coord.data.queue
    await coord.async_shutdown()
