"""Present Companion phones once and resolve their best forwarding destination."""

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .validation import mobile_target


class UnsupportedNotificationDestination(ServiceValidationError):
    """The chosen channel cannot represent the requested notification."""


def _destinations(hass: HomeAssistant):
    """Link services to entities only using the Companion registration identity."""
    services = {
        f"notify.{name}"
        for name in hass.services.async_services_for_domain("notify")
        if name.startswith("mobile_app_")
    }
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    registrations = {}
    labels = {}
    for entry in hass.config_entries.async_entries("mobile_app"):
        name = entry.data.get("device_name")
        if isinstance(name, str) and name:
            service = f"notify.{slugify('mobile_app_' + name)}"
            registrations.setdefault(service, []).append(entry.entry_id)
            labels[service] = entry.title or name
    entities = {}
    targets = set(services)
    for entity in registry.entities.values():
        if (
            entity.domain != "notify"
            or entity.platform != "mobile_app"
            or entity.disabled_by is not None
            or hass.states.get(entity.entity_id) is None
        ):
            continue
        # Never merge separate registrations just because their names match.
        key = entity.config_entry_id or entity.entity_id
        entities.setdefault(key, []).append(entity.entity_id)
        targets.add(entity.entity_id)
        device = devices.async_get(entity.device_id) if entity.device_id else None
        state = hass.states.get(entity.entity_id)
        labels[entity.entity_id] = (
            (device.name_by_user or device.name) if device else None
        ) or state.name
    aliases = {}
    routes = {}
    for service, entries in registrations.items():
        if len(entries) != 1:
            continue
        matching = entities.get(entries[0], [])
        if len(matching) != 1:
            continue
        entity = matching[0]
        preferred = service if service in services else entity
        aliases[service] = preferred
        aliases[entity] = preferred
        labels[preferred] = labels[entity]
        routes[service] = routes[entity] = (
            entity,
            service if service in services else None,
        )
    return aliases, labels, targets, routes


def mobile_targets(hass: HomeAssistant, values: list[str]) -> list[str]:
    """Prefer available Companion services and deduplicate each linked phone."""
    aliases, _, _, _ = _destinations(hass)
    result = []
    for value in values:
        value = mobile_target(value, hass)
        target = aliases.get(value, value)
        if target not in result:
            result.append(target)
    return result


def mobile_options(hass: HomeAssistant, selected: list[str]):
    """Build readable phone choices, retaining existing offline destinations."""
    aliases, labels, targets, _ = _destinations(hass)
    targets.update(selected)
    options = {}
    for target in targets:
        value = aliases.get(target, target)
        options[value] = {
            "value": value,
            "label": labels.get(
                value, value.removeprefix("notify.mobile_app_").replace("_", " ")
            ),
        }
    return sorted(
        options.values(),
        key=lambda option: (option["label"].casefold(), option["value"]),
    )


def resolve_destination(hass: HomeAssistant, target: str, advanced: bool) -> str:
    """Choose a linked phone's channel without discarding advanced payloads."""
    _, _, _, routes = _destinations(hass)
    if route := routes.get(target):
        entity, service = route
        if not advanced:
            return entity
        if service is None:
            raise UnsupportedNotificationDestination(
                f"{target} requires a Companion App service for advanced/live notifications"
            )
        return service
    return target
