"""Source discovery, migration and automatic selection regressions."""

from unittest.mock import patch

import pytest
from homeassistant.components import persistent_notification
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import (
    CONF_FORWARD_ID_PATTERNS,
    CONF_FORWARD_SOURCES,
)
from custom_components.smart_presence_notify.sources import (
    MAX_OBSERVED_SOURCES,
    NotificationSources,
    forwarding_defaults,
)
from tests.test_reliability import make_coordinator


async def test_options_offer_only_verified_installed_integrations(hass):
    sources = NotificationSources(hass, "test")
    dreame = MockConfigEntry(domain="dreame_vacuum")
    dreame.add_to_hass(hass)
    unknown = MockConfigEntry(domain="unknown_vacuum")
    unknown.add_to_hass(hass)
    sources.async_observe(["unknown_vacuum_error", "dreame_vacuum_mac_error"])
    options = {option["value"]: option["label"] for option in sources.options([])}
    assert options["integration:dreame_vacuum"] == "Dreame Vacuum"
    assert "integration:homekit" not in options
    assert "integration:unknown_vacuum" not in options
    assert "notification:unknown_vacuum_error" in options
    assert "notification:dreame_vacuum_mac_error" not in options
    await sources.async_shutdown()


async def test_homekit_matches_config_entry_ids_not_arbitrary_prefixes(hass):
    sources = NotificationSources(hass, "test")
    homekit = MockConfigEntry(domain="homekit")
    homekit.add_to_hass(hass)
    settings = {CONF_FORWARD_SOURCES: ["integration:homekit"]}
    assert sources.matches(homekit.entry_id, settings)
    assert not sources.matches("homekit_something", settings)
    sources.async_observe([homekit.entry_id, "homekit_something"])
    options = [option["value"] for option in sources.options([])]
    assert "integration:homekit" in options
    assert f"notification:{homekit.entry_id}" not in options
    assert "notification:homekit_something" in options
    await sources.async_shutdown()


async def test_discovery_observes_while_disabled_and_survives_restart(hass):
    coord = await make_coordinator(hass, forward_enabled=False)
    persistent_notification.async_create(
        hass, "Sensitive body", "Sensitive title", "unknown_source_error"
    )
    await hass.async_block_till_done()
    assert "notification:unknown_source_error" in [
        o["value"] for o in coord.notification_sources.options([])
    ]
    assert not coord.data.queue
    persistent_notification.async_dismiss(hass, "unknown_source_error")
    await hass.async_block_till_done()
    await coord.async_shutdown()
    restored = NotificationSources(hass, coord.config_entry.entry_id)
    await restored.async_initialize()
    assert await restored._store.async_load() == ["unknown_source_error"]
    assert "notification:unknown_source_error" in [
        o["value"] for o in restored.options([])
    ]


async def test_exact_observed_id_does_not_expand_wildcards(hass):
    sources = NotificationSources(hass, "test")
    settings = {CONF_FORWARD_SOURCES: ["notification:my[*]id"]}
    assert sources.matches("my[*]id", settings)
    assert not sources.matches("my*id", settings)
    assert not sources.matches("myanythingid", settings)
    assert not sources.matches("dreame_vacuum_error", {CONF_FORWARD_SOURCES: []})
    assert sources.matches("other", {CONF_FORWARD_SOURCES: ["all"]})
    assert sources.matches(
        "additional_error",
        {CONF_FORWARD_SOURCES: [], CONF_FORWARD_ID_PATTERNS: ["additional_*"]},
    )


@pytest.mark.parametrize(
    "patterns", [[], ["dreame_vacuum_*"], ["custom_*"], ["dreame_vacuum_*", "custom_*"]]
)
async def test_legacy_migration_preserves_matches(hass, patterns):
    sources = NotificationSources(hass, "test")
    legacy = {CONF_FORWARD_ID_PATTERNS: patterns}
    selected, remaining = forwarding_defaults(hass, legacy)
    migrated = {CONF_FORWARD_SOURCES: selected, CONF_FORWARD_ID_PATTERNS: remaining}
    for identifier in [
        "dreame_vacuum_mac_error",
        "custom_error",
        "other",
        "dreame_vacuum_sponsor",
    ]:
        assert sources.matches(identifier, legacy) == sources.matches(
            identifier, migrated
        )


async def test_observations_are_bounded_and_selected_ids_remain_visible(hass):
    sources = NotificationSources(hass, "test")
    sources.async_observe([f"source_{i}" for i in range(MAX_OBSERVED_SOURCES + 10)])
    selected = ["notification:source_0", "integration:dreame_vacuum"]
    options = {o["value"]: o["label"] for o in sources.options(selected)}
    assert "notification:source_0" in options
    assert "notification:source_1" not in options
    assert "integration:dreame_vacuum" in options
    await sources.async_shutdown()
    assert len(await sources._store.async_load()) == MAX_OBSERVED_SOURCES


async def test_malformed_observation_storage_is_skipped(hass):
    sources = NotificationSources(hass, "test")
    with patch.object(
        sources._store, "async_load", return_value=["valid", None, {}, "", "x" * 201]
    ):
        await sources.async_initialize()
    assert [o["value"] for o in sources.options([])] == ["notification:valid", "all"]


async def test_named_sources_and_exact_ids_forward_to_multiple_phones(hass):
    coord = await make_coordinator(
        hass,
        forward_enabled=True,
        forward_sources=["integration:dreame_vacuum", "notification:other[*]"],
        forward_targets=["notify.mobile_app_a", "notify.mobile_app_b"],
    )
    calls = []

    async def phone(call):
        calls.append((call.service, call.data["message"]))

    for name in ["mobile_app_a", "mobile_app_b"]:
        hass.services.async_register("notify", name, phone)
    persistent_notification.async_create(
        hass, "Dreame", "Vacuum", "dreame_vacuum_mac_error"
    )
    persistent_notification.async_create(hass, "Exact", "Other", "other[*]")
    persistent_notification.async_create(hass, "Skip", "Other", "other_random")
    await hass.async_block_till_done()
    assert sorted(calls) == sorted(
        [
            (service, message)
            for service in ["mobile_app_a", "mobile_app_b"]
            for message in ["Dreame", "Exact"]
        ]
    )
    await coord.async_shutdown()


async def forwarding_form(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "forwarding"}
    )


async def test_options_show_runtime_observations_and_save_multiple_selection(
    hass, mock_config_entry
):
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    dreame = MockConfigEntry(domain="dreame_vacuum")
    dreame.add_to_hass(hass)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    persistent_notification.async_create(hass, "Body", "Other", "some_notification")
    await hass.async_block_till_done()
    form = await forwarding_form(hass, mock_config_entry)
    source_selector = form["data_schema"].schema[CONF_FORWARD_SOURCES]
    values = [option["value"] for option in source_selector.config["options"]]
    assert "integration:dreame_vacuum" in values
    assert "notification:some_notification" in values
    assert source_selector.config["multiple"] is True
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={
            "forward_enabled": True,
            "forward_targets": ["notify.mobile_app_phone"],
            "forward_sources": [
                "integration:dreame_vacuum",
                "notification:some_notification",
            ],
            "forward_id_patterns": [],
            "forward_text": "",
            "forward_updates": True,
        },
    )
    assert result["type"] == "create_entry"
    assert mock_config_entry.data["forward_sources"] == [
        "integration:dreame_vacuum",
        "notification:some_notification",
    ]
    assert mock_config_entry.data["forward_id_patterns"] == []


async def test_no_selection_cannot_enable_all_implicitly(hass, mock_config_entry):
    hass.services.async_register("notify", "mobile_app_phone", lambda call: None)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    form = await forwarding_form(hass, mock_config_entry)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={
            "forward_enabled": True,
            "forward_targets": ["notify.mobile_app_phone"],
            "forward_sources": [],
            "forward_id_patterns": [],
            "forward_text": "",
            "forward_updates": True,
        },
    )
    assert result["type"] == "form"
    assert result["errors"]["forward_sources"] == "sources_required"


async def test_removing_integration_clears_its_discovery_catalogue(
    hass, mock_config_entry
):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    persistent_notification.async_create(hass, "Body", "Title", "observed_to_remove")
    await hass.async_block_till_done()
    sources = mock_config_entry.runtime_data.coordinator.notification_sources
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    assert await sources._store.async_load() is None
