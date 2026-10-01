"""Verified notification sources and a bounded catalogue of observed IDs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import CONF_FORWARD_ID_PATTERNS, CONF_FORWARD_SOURCES, DOMAIN

MAX_OBSERVED_SOURCES = 200
MAX_NOTIFICATION_ID_LENGTH = 200
SAVE_DELAY_SECONDS = 15


@dataclass(frozen=True)
class KnownSource:
    name: str
    patterns: tuple[str, ...] = ()
    uses_entry_id: bool = False


# Only add mappings supported by the source integration's notification code.
# Tasshack/dreame-vacuum: coordinator.py, _create_persistent_notification.
# HA homekit/util.py: async_show_setup_message uses the config entry ID.
KNOWN_SOURCES = {
    "dreame_vacuum": KnownSource("Dreame Vacuum", ("dreame_vacuum_*",)),
    "homekit": KnownSource("HomeKit Bridge", uses_entry_id=True),
}
_LABELS = {
    "en": ("Observed notification", "not detected", "All bell notifications"),
    "it": ("Notifica osservata", "non rilevata", "Tutte le notifiche della campanella"),
    "de": (
        "Beobachtete Benachrichtigung",
        "nicht erkannt",
        "Alle persistenten Benachrichtigungen",
    ),
    "es": (
        "Notificación observada",
        "no detectada",
        "Todas las notificaciones persistentes",
    ),
    "fr": (
        "Notification observée",
        "non détectée",
        "Toutes les notifications persistantes",
    ),
}


def notification_source(value: str) -> str:
    """Validate a verified integration, an exact notification ID, or explicit all."""
    if not isinstance(value, str):
        raise vol.Invalid("Invalid notification source")
    if value == "all":
        return value
    kind, separator, identifier = value.partition(":")
    if separator and kind == "integration" and identifier in KNOWN_SOURCES:
        return value
    if (
        separator
        and kind == "notification"
        and 0 < len(identifier) <= MAX_NOTIFICATION_ID_LENGTH
    ):
        return value
    raise vol.Invalid("Select a known integration or an observed notification ID")


def forwarding_defaults(
    hass: HomeAssistant, settings: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Migrate legacy wildcard choices without broadening notification matching."""
    if CONF_FORWARD_SOURCES in settings:
        return list(settings[CONF_FORWARD_SOURCES]), list(
            settings.get(CONF_FORWARD_ID_PATTERNS, [])
        )
    if CONF_FORWARD_ID_PATTERNS not in settings:
        installed = {
            entry.domain for entry in hass.config_entries.async_entries()
        } | set(hass.config.components)
        return (
            ["integration:dreame_vacuum"] if "dreame_vacuum" in installed else []
        ), []
    patterns = list(settings[CONF_FORWARD_ID_PATTERNS])
    if not patterns:
        return ["all"], []
    sources = []
    for domain, source in KNOWN_SOURCES.items():
        if source.patterns and all(pattern in patterns for pattern in source.patterns):
            sources.append(f"integration:{domain}")
            patterns = [
                pattern for pattern in patterns if pattern not in source.patterns
            ]
    return sources, patterns


class NotificationSources:
    """Collect IDs through callbacks, without guessing origins from arbitrary prefixes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._observed: OrderedDict[str, None] = OrderedDict()
        self._store: Store[list[str]] = Store(hass, 1, f"{DOMAIN}.sources.{entry_id}")
        self._dirty = False

    async def async_initialize(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, list):
            for identifier in data:
                if (
                    isinstance(identifier, str)
                    and 0 < len(identifier) <= MAX_NOTIFICATION_ID_LENGTH
                ):
                    self._observed[identifier] = None
                    if len(self._observed) > MAX_OBSERVED_SOURCES:
                        self._observed.popitem(last=False)

    @callback
    def async_observe(self, identifiers: Iterable[str]) -> None:
        changed = False
        for identifier in identifiers:
            if (
                not isinstance(identifier, str)
                or not 0 < len(identifier) <= MAX_NOTIFICATION_ID_LENGTH
            ):
                continue
            if identifier in self._observed:
                continue
            self._observed[identifier] = None
            changed = True
            if len(self._observed) > MAX_OBSERVED_SOURCES:
                self._observed.popitem(last=False)
        if changed:
            self._dirty = True
            self._store.async_delay_save(
                lambda: list(self._observed), SAVE_DELAY_SECONDS
            )

    async def async_shutdown(self) -> None:
        if self._dirty:
            await self._store.async_save(list(self._observed))
            self._dirty = False

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def _installed_domains(self) -> set[str]:
        return {entry.domain for entry in self.hass.config_entries.async_entries()} | {
            component.split(".", 1)[0] for component in self.hass.config.components
        }

    def _matches_integration(self, domain: str, identifier: str) -> bool:
        source = KNOWN_SOURCES.get(domain)
        if source is None:
            return False
        return any(fnmatchcase(identifier, pattern) for pattern in source.patterns) or (
            source.uses_entry_id
            and any(
                entry.entry_id == identifier
                for entry in self.hass.config_entries.async_entries(domain)
            )
        )

    def matches(self, identifier: str, settings: dict[str, Any]) -> bool:
        """Combine selected sources and advanced filters with OR; empty new choices match nothing."""
        if CONF_FORWARD_SOURCES not in settings:
            patterns = settings.get(CONF_FORWARD_ID_PATTERNS, ["dreame_vacuum_*"])
            return not patterns or any(
                fnmatchcase(identifier, pattern) for pattern in patterns
            )
        for selected in settings[CONF_FORWARD_SOURCES]:
            if selected == "all":
                return True
            kind, _, value = selected.partition(":")
            if kind == "notification" and identifier == value:
                return True
            if kind == "integration" and self._matches_integration(value, identifier):
                return True
        return any(
            fnmatchcase(identifier, pattern)
            for pattern in settings.get(CONF_FORWARD_ID_PATTERNS, [])
        )

    def options(self, selected: list[str]) -> list[dict[str, str]]:
        observed_label, unavailable_label, all_label = _LABELS.get(
            self.hass.config.language, _LABELS["en"]
        )
        installed = self._installed_domains()
        options = {}
        for domain, source in KNOWN_SOURCES.items():
            value = f"integration:{domain}"
            if domain in installed or value in selected:
                options[value] = (
                    source.name
                    if domain in installed
                    else f"{source.name} ({unavailable_label})"
                )
        identifiers = list(self._observed)
        identifiers.extend(
            value.removeprefix("notification:")
            for value in selected
            if value.startswith("notification:")
        )
        for identifier in identifiers:
            value = f"notification:{identifier}"
            if value in selected or not any(
                self._matches_integration(domain, identifier)
                for domain in installed & KNOWN_SOURCES.keys()
            ):
                options[value] = f"{observed_label}: {identifier}"
        return [
            {"value": value, "label": label} for value, label in options.items()
        ] + [{"value": "all", "label": all_label}]
