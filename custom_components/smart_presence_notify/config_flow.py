"""Config flow for Smart Presence Notify."""

from __future__ import annotations

from math import isfinite
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_ADMIN_PERSON,
    CONF_FALLBACK_MODE,
    CONF_FALLBACK_SERVICE,
    CONF_FORWARD_ENABLED,
    CONF_FORWARD_ID_PATTERNS,
    CONF_FORWARD_SOURCES,
    CONF_FORWARD_TARGETS,
    CONF_FORWARD_TEXT,
    CONF_FORWARD_UPDATES,
    CONF_IS_ADMIN,
    CONF_NOTIFY_SERVICES,
    CONF_PERSONS,
    CONF_QUEUE_LIMIT,
    CONF_QUEUE_MODE,
    CONF_QUEUE_TIMEOUT,
    CONF_TARGET_MODE,
    DEFAULT_QUEUE_LIMIT,
    DOMAIN,
    MAX_QUEUE_LIMIT,
    FallbackMode,
    QueueMode,
    TargetMode,
)
from .mobile import mobile_options, mobile_targets
from .sources import (
    MAX_OBSERVED_SOURCES,
    NotificationSources,
    forwarding_defaults,
    notification_source,
)
from .validation import notification_target


def _notify_options(hass):
    return sorted(
        {
            f"notify.{name}"
            for name in hass.services.async_services_for_domain("notify")
            if name != "send_message"
        }
        | {
            entity_id
            for entity_id in hass.states.async_entity_ids("notify")
            if (entity := er.async_get(hass).async_get(entity_id)) is None
            or entity.platform != DOMAIN
        }
    )


def _build_global_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build global settings schema with optional defaults."""
    d: dict[str, Any] = dict(defaults) if defaults else {}
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "Smart Presence Notify")): str,
            vol.Required(
                CONF_TARGET_MODE, default=d.get(CONF_TARGET_MODE, TargetMode.BROADCAST)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        TargetMode.BROADCAST,
                        TargetMode.SINGLE_ADMIN,
                        TargetMode.CALLER_DECIDES,
                    ],
                    translation_key="target_mode",
                )
            ),
            vol.Required(
                CONF_QUEUE_MODE, default=d.get(CONF_QUEUE_MODE, QueueMode.FIFO)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[QueueMode.FIFO, QueueMode.LAST_ONLY, QueueMode.SUMMARY],
                    translation_key="queue_mode",
                )
            ),
            # min=-1 instead of 0: HA 2026.x enforces NumberSelector min at schema level,
            # which would reject -1 before our validator runs. Our handler validates >= 0.
            vol.Required(
                CONF_QUEUE_TIMEOUT, default=d.get(CONF_QUEUE_TIMEOUT, 0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-1, max=10080, step=1, mode="box")
            ),
            vol.Required(
                CONF_QUEUE_LIMIT, default=d.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=MAX_QUEUE_LIMIT, step=1, mode="box"
                )
            ),
            vol.Required(
                CONF_FALLBACK_MODE,
                default=d.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[FallbackMode.DISCARD, FallbackMode.NOTIFY_FALLBACK],
                    translation_key="fallback_mode",
                )
            ),
            vol.Optional(
                CONF_FALLBACK_SERVICE, default=d.get(CONF_FALLBACK_SERVICE, "")
            ): str,
        }
    )


def _validate_global_settings(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate global settings form input. Returns errors dict."""
    errors: dict[str, str] = {}
    timeout = user_input.get(CONF_QUEUE_TIMEOUT, 0)
    if (
        not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout < 0
        or timeout > 10080
        or timeout != int(timeout)
    ):
        errors[CONF_QUEUE_TIMEOUT] = "invalid_timeout"
    elif (
        user_input.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK
        and not user_input.get(CONF_FALLBACK_SERVICE, "").strip()
    ):
        errors[CONF_FALLBACK_SERVICE] = "fallback_service_required"
    limit = user_input.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT)
    if (
        not isinstance(limit, (int, float))
        or not isfinite(limit)
        or not 1 <= limit <= MAX_QUEUE_LIMIT
        or limit != int(limit)
    ):
        errors[CONF_QUEUE_LIMIT] = "invalid_queue_limit"
    fallback = user_input.get(CONF_FALLBACK_SERVICE, "").strip()
    if fallback:
        try:
            user_input[CONF_FALLBACK_SERVICE] = notification_target(fallback)
        except vol.Invalid:
            errors[CONF_FALLBACK_SERVICE] = "invalid_service_format"
    return errors


def _validate_persons(
    persons: dict[str, Any], target_mode: str | None
) -> dict[str, str]:
    """Validate persons form input. Returns errors dict."""
    errors: dict[str, str] = {}
    if not persons:
        errors["base"] = "no_persons"
        return errors
    for cfg in persons.values():
        for svc in cfg.get(CONF_NOTIFY_SERVICES, []):
            try:
                notification_target(svc)
            except vol.Invalid:
                errors["base"] = "invalid_service_format"
                return errors
    if target_mode == TargetMode.SINGLE_ADMIN:
        admin_count = sum(1 for p in persons.values() if p.get(CONF_IS_ADMIN))
        if admin_count != 1:
            errors["base"] = "admin_required"
    return errors


class SNPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Smart Presence Notify."""

    VERSION = 1
    _global_data: dict[str, Any]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_global_settings(user_input)

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(
                    user_input.get(CONF_QUEUE_TIMEOUT, 0)
                )
                self._global_data[CONF_QUEUE_LIMIT] = int(
                    user_input.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT)
                )
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_global_schema(user_input),
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        person_entities = list(self.hass.states.async_entity_ids("person"))
        notify_service_options = _notify_options(self.hass)

        if user_input is not None:
            persons = _parse_persons_input(user_input, person_entities)
            target_mode = self._global_data.get(CONF_TARGET_MODE)
            errors = _validate_persons(persons, target_mode)

            if not errors:
                return self.async_create_entry(
                    title=self._global_data.get("name", "Smart Presence Notify"),
                    data={**self._global_data, CONF_PERSONS: persons},
                )

        schema = _build_persons_schema(
            person_entities,
            notify_service_options,
            self._global_data.get(CONF_TARGET_MODE),
        )
        return self.async_show_form(
            step_id="persons",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SNPOptionsFlow:
        return SNPOptionsFlow()


class SNPOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow (same as config flow)."""

    def __init__(self) -> None:
        self._global_data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["user", "forwarding"])

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_global_settings(user_input)

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(
                    user_input.get(CONF_QUEUE_TIMEOUT, 0)
                )
                self._global_data[CONF_QUEUE_LIMIT] = int(
                    user_input.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT)
                )
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_global_schema(user_input or self.config_entry.data),
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        person_entities = list(self.hass.states.async_entity_ids("person"))
        notify_service_options = _notify_options(self.hass)

        if user_input is not None:
            persons = _parse_persons_input(user_input, person_entities)
            target_mode = self._global_data.get(CONF_TARGET_MODE)
            errors = _validate_persons(persons, target_mode)

            if not errors:
                new_data = {
                    **self.config_entry.data,
                    **self._global_data,
                    CONF_PERSONS: persons,
                }
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                    title=new_data.get("name", self.config_entry.title),
                )
                return self.async_create_entry(title="", data={})

        schema = _build_persons_schema(
            person_entities,
            notify_service_options,
            self._global_data.get(CONF_TARGET_MODE),
            defaults=_parse_persons_input(user_input, person_entities)
            if user_input is not None
            else self.config_entry.data.get(CONF_PERSONS, {}),
        )
        return self.async_show_form(
            step_id="persons",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_forwarding(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure forwarding of new bell notifications to mobile devices."""
        errors = {}
        if user_input is not None:
            try:
                user_input[CONF_FORWARD_TARGETS] = mobile_targets(
                    self.hass, user_input.get(CONF_FORWARD_TARGETS, [])
                )
            except vol.Invalid:
                errors[CONF_FORWARD_TARGETS] = "invalid_mobile_target"
            if user_input.get(CONF_FORWARD_ENABLED) and not user_input.get(
                CONF_FORWARD_TARGETS
            ):
                errors[CONF_FORWARD_TARGETS] = "mobile_targets_required"
            try:
                user_input[CONF_FORWARD_SOURCES] = list(
                    dict.fromkeys(
                        notification_source(source)
                        for source in user_input.get(CONF_FORWARD_SOURCES, [])
                    )
                )
                if len(user_input[CONF_FORWARD_SOURCES]) > MAX_OBSERVED_SOURCES:
                    raise vol.Invalid("Too many sources")
            except vol.Invalid:
                errors[CONF_FORWARD_SOURCES] = "invalid_sources"
            patterns = user_input.get(CONF_FORWARD_ID_PATTERNS, [])
            if (
                user_input.get(CONF_FORWARD_ENABLED)
                and not user_input.get(CONF_FORWARD_SOURCES)
                and not patterns
            ):
                errors[CONF_FORWARD_SOURCES] = "sources_required"
            if len(patterns) > 20 or any(
                len(p) > 200 or not p.strip() for p in patterns
            ):
                errors[CONF_FORWARD_ID_PATTERNS] = "invalid_patterns"
            if not errors:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**self.config_entry.data, **user_input}
                )
                return self.async_create_entry(title="", data={})
        d = user_input or self.config_entry.data
        destinations = d.get(CONF_FORWARD_TARGETS, [])
        try:
            destinations = mobile_targets(self.hass, destinations)
        except vol.Invalid:
            pass  # Keep invalid saved choices visible so they can be repaired.
        selected, patterns = forwarding_defaults(self.hass, d)
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is not None:
            discovery = runtime.coordinator.notification_sources
        else:
            discovery = NotificationSources(self.hass, self.config_entry.entry_id)
            await discovery.async_initialize()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FORWARD_ENABLED, default=d.get(CONF_FORWARD_ENABLED, False)
                ): bool,
                vol.Required(
                    CONF_FORWARD_TARGETS, default=destinations
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=mobile_options(self.hass, destinations),
                        multiple=True,
                        custom_value=False,
                    )
                ),
                vol.Required(
                    CONF_FORWARD_SOURCES, default=selected
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=discovery.options(selected), multiple=True
                    )
                ),
                vol.Required(
                    CONF_FORWARD_ID_PATTERNS,
                    default=patterns,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[], multiple=True, custom_value=True
                    )
                ),
                vol.Optional(
                    CONF_FORWARD_TEXT, default=d.get(CONF_FORWARD_TEXT, "")
                ): vol.All(str, vol.Length(max=1000)),
                vol.Required(
                    CONF_FORWARD_UPDATES, default=d.get(CONF_FORWARD_UPDATES, True)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="forwarding", data_schema=schema, errors=errors
        )


def _build_persons_schema(
    person_entities: list[str],
    notify_service_options: list[str],
    target_mode: str | None,
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build a dynamic schema with one row per person entity."""
    defaults = defaults or {}
    schema: dict[Any, Any] = {}

    for entity_id in person_entities:
        key = f"{entity_id}__services"
        person_defaults = defaults.get(entity_id, {})
        default_services = person_defaults.get(CONF_NOTIFY_SERVICES, [])
        schema[vol.Required(key, default=default_services)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=notify_service_options,
                multiple=True,
                custom_value=True,
            )
        )

    if target_mode == TargetMode.SINGLE_ADMIN:
        current_admin = next(
            (eid for eid, p in defaults.items() if p.get(CONF_IS_ADMIN)), None
        )
        if current_admin:
            schema[vol.Optional(CONF_ADMIN_PERSON, default=current_admin)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=person_entities,
                        multiple=False,
                    )
                )
            )
        else:
            schema[vol.Optional(CONF_ADMIN_PERSON)] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=person_entities,
                    multiple=False,
                )
            )

    return vol.Schema(schema)


def _parse_persons_input(
    user_input: dict[str, Any], person_entities: list[str]
) -> dict[str, dict[str, Any]]:
    """Convert flat form data into nested persons dict."""
    admin_person = user_input.get(CONF_ADMIN_PERSON)
    persons: dict[str, dict[str, Any]] = {}
    for entity_id in person_entities:
        key = f"{entity_id}__services"
        services = user_input.get(key, [])
        if services:
            persons[entity_id] = {
                CONF_NOTIFY_SERVICES: [s.strip().lower() for s in services],
                CONF_IS_ADMIN: entity_id == admin_person,
            }
    return persons
