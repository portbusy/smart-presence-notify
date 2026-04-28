"""Config flow for Smart Presence Notify."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_ADMIN_PERSON,
    CONF_FALLBACK_MODE,
    CONF_FALLBACK_SERVICE,
    CONF_IS_ADMIN,
    CONF_NOTIFY_SERVICES,
    CONF_PERSONS,
    CONF_QUEUE_MODE,
    CONF_QUEUE_TIMEOUT,
    CONF_TARGET_MODE,
    DOMAIN,
    FallbackMode,
    QueueMode,
    TargetMode,
)


def _build_global_schema(defaults: dict | None = None) -> vol.Schema:
    """Build global settings schema with optional defaults."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "Smart Presence Notify")): str,
            vol.Required(CONF_TARGET_MODE, default=d.get(CONF_TARGET_MODE, TargetMode.BROADCAST)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[m.value for m in TargetMode])
            ),
            vol.Required(CONF_QUEUE_MODE, default=d.get(CONF_QUEUE_MODE, QueueMode.FIFO)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[m.value for m in QueueMode])
            ),
            vol.Required(CONF_QUEUE_TIMEOUT, default=d.get(CONF_QUEUE_TIMEOUT, 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-1, max=10080, step=1, mode="box")
            ),
            vol.Required(CONF_FALLBACK_MODE, default=d.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[m.value for m in FallbackMode])
            ),
            vol.Optional(CONF_FALLBACK_SERVICE, default=d.get(CONF_FALLBACK_SERVICE, "")): str,
        }
    )


def _validate_global_settings(user_input: dict) -> dict[str, str]:
    """Validate global settings form input. Returns errors dict."""
    errors: dict[str, str] = {}
    timeout = user_input.get(CONF_QUEUE_TIMEOUT, 0)
    if int(timeout) < 0:
        errors[CONF_QUEUE_TIMEOUT] = "invalid_timeout"
    elif (
        user_input.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK
        and not user_input.get(CONF_FALLBACK_SERVICE, "").strip()
    ):
        errors[CONF_FALLBACK_SERVICE] = "fallback_service_required"
    return errors


def _validate_persons(persons: dict, target_mode: str | None) -> dict[str, str]:
    """Validate persons form input. Returns errors dict."""
    errors: dict[str, str] = {}
    if not persons:
        errors["base"] = "no_persons"
    elif target_mode == TargetMode.SINGLE_ADMIN:
        admin_count = sum(1 for p in persons.values() if p.get(CONF_IS_ADMIN))
        if admin_count != 1:
            errors["base"] = "admin_required"
    return errors


class SNPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Smart Presence Notify."""

    VERSION = 1
    _global_data: dict

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_global_settings(user_input)

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(user_input.get(CONF_QUEUE_TIMEOUT, 0))
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_global_schema(),
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        person_entities = list(self.hass.states.async_entity_ids("person"))
        notify_options = list(self.hass.services.async_services_for_domain("notify"))
        notify_service_options = [f"notify.{s}" for s in notify_options]

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
        self._global_data: dict = {}

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_global_settings(user_input)

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(user_input.get(CONF_QUEUE_TIMEOUT, 0))
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_global_schema(self.config_entry.data),
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        person_entities = list(self.hass.states.async_entity_ids("person"))
        notify_options = list(self.hass.services.async_services_for_domain("notify"))
        notify_service_options = [f"notify.{s}" for s in notify_options]

        if user_input is not None:
            persons = _parse_persons_input(user_input, person_entities)
            target_mode = self._global_data.get(CONF_TARGET_MODE)
            errors = _validate_persons(persons, target_mode)

            if not errors:
                new_data = {**self.config_entry.data, **self._global_data, CONF_PERSONS: persons}
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                return self.async_create_entry(title="", data={})

        schema = _build_persons_schema(
            person_entities,
            notify_service_options,
            self._global_data.get(CONF_TARGET_MODE),
            defaults=self.config_entry.data.get(CONF_PERSONS, {}),
        )
        return self.async_show_form(
            step_id="persons",
            data_schema=schema,
            errors=errors,
        )


def _build_persons_schema(
    person_entities: list[str],
    notify_service_options: list[str],
    target_mode: str | None,
    defaults: dict | None = None,
) -> vol.Schema:
    """Build a dynamic schema with one row per person entity."""
    defaults = defaults or {}
    schema: dict = {}

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
        schema[vol.Required(CONF_ADMIN_PERSON, default=current_admin)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=person_entities,
                multiple=False,
            )
        )

    return vol.Schema(schema)


def _parse_persons_input(user_input: dict, person_entities: list[str]) -> dict:
    """Convert flat form data into nested persons dict."""
    admin_person = user_input.get(CONF_ADMIN_PERSON)
    persons: dict = {}
    for entity_id in person_entities:
        key = f"{entity_id}__services"
        services = user_input.get(key, [])
        if services:
            persons[entity_id] = {
                CONF_NOTIFY_SERVICES: services,
                CONF_IS_ADMIN: entity_id == admin_person,
            }
    return persons
