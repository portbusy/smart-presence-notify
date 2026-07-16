"""Coordinator for Smart Presence Notify."""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_HOME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_FALLBACK_MODE,
    CONF_FALLBACK_SERVICE,
    CONF_IS_ADMIN,
    CONF_NOTIFY_SERVICES,
    CONF_PERSONS,
    CONF_QUEUE_MODE,
    CONF_QUEUE_TIMEOUT,
    CONF_TARGET_MODE,
    DOMAIN,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
    EVENT_RESPONSE,
    FallbackMode,
    Priority,
    QueueMode,
    RESPONSE_PRESET_YES_NO,
    TargetMode,
)
from .models import CoordinatorData, NotificationRecord, PendingNotification
from .store import SNPStore

_LOGGER = logging.getLogger(__name__)

_RESPONSE_ACTION_RE = re.compile(
    r"^SNP_(YES|NO)_([a-f0-9]{32})\.([A-Za-z0-9_-]+)$"
)
_MAX_ANSWERED_RESPONSES = 256
_RESPONSE_TITLES = {
    "de": ("Ja", "Nein"),
    "en": ("Yes", "No"),
    "es": ("Sí", "No"),
    "fr": ("Oui", "Non"),
    "it": ("Sì", "No"),
}


class SmartPresenceNotifyCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Manages presence-aware notification routing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self._store = SNPStore(hass)
        self._timeout_unsubs: dict[str, Callable[[], None]] = {}
        self._presence_unsub: Callable[[], None] | None = None
        self._response_unsub: Callable[[], None] | None = None
        self._answered_response_nonces: dict[str, None] = {}
        self._drain_in_progress = False

    async def async_initialize(self) -> None:
        """Load queue from storage and start presence listener."""
        queue = await self._store.async_load()
        someone_home, home_persons = self._get_presence()
        self.async_set_updated_data(
            CoordinatorData(
                queue=queue,
                last_sent=None,
                someone_home=someone_home,
                home_persons=home_persons,
            )
        )
        self._register_presence_listener()
        self._response_unsub = self.hass.bus.async_listen(
            EVENT_MOBILE_APP_NOTIFICATION_ACTION,
            self._handle_notification_action,
        )
        for notification in queue:
            if notification.expires_at:
                self._schedule_timeout(notification)

    async def async_shutdown(self) -> None:
        """Cancel listeners and timeout handles."""
        if self._presence_unsub:
            self._presence_unsub()
            self._presence_unsub = None
        if self._response_unsub:
            self._response_unsub()
            self._response_unsub = None
        for unsub in self._timeout_unsubs.values():
            unsub()
        self._timeout_unsubs.clear()

    @callback
    def _register_presence_listener(self) -> None:
        """Register (or re-register) the state-change listener for configured persons.

        Uses EVENT_STATE_CHANGED with an event_filter so only person entities
        in config reach the handler — equivalent efficiency to
        async_track_state_change_event but with synchronous dispatch.
        """
        if self._presence_unsub:
            self._presence_unsub()
        configured_persons = frozenset(
            self.config_entry.data.get(CONF_PERSONS, {}).keys()
        )

        @callback
        def _filter(event_data: dict) -> bool:
            return event_data.get("entity_id") in configured_persons

        self._presence_unsub = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._handle_state_changed,
            event_filter=_filter,
        )

    @callback
    def async_reload_presence_listener(self) -> None:
        """Rebuild the presence listener after an options-flow update."""
        self._register_presence_listener()

    def _get_presence(self) -> tuple[bool, list[str]]:
        configured_persons = self.config_entry.data.get(CONF_PERSONS, {})
        home_persons = [
            entity_id
            for entity_id in configured_persons
            if (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_HOME
        ]
        return bool(home_persons), home_persons

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        entity_id: str = event.data.get("entity_id", "")
        if not entity_id.startswith("person."):
            return
        configured_persons = self.config_entry.data.get(CONF_PERSONS, {})
        if entity_id not in configured_persons:
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        home_persons = [
            eid for eid in configured_persons
            if (s := self.hass.states.get(eid)) is not None and s.state == STATE_HOME
        ]
        someone_home = bool(home_persons)

        current = self.data
        if someone_home != current.someone_home or home_persons != current.home_persons:
            self.async_set_updated_data(
                replace(current, someone_home=someone_home, home_persons=home_persons)
            )

        arrived = (
            new_state is not None
            and new_state.state == STATE_HOME
            and (old_state is None or old_state.state != STATE_HOME)
        )
        if arrived and current.queue:
            self.hass.async_create_task(self._async_drain_queue(entity_id))

    @callback
    def _handle_notification_action(self, event: Event) -> None:
        """Translate a Companion App action into an integration response event."""
        action = event.data.get("action")
        if not isinstance(action, str) or not (
            match := _RESPONSE_ACTION_RE.match(action)
        ):
            return

        response, nonce, encoded_response_id = match.groups()
        if nonce in self._answered_response_nonces:
            return

        try:
            padding = "=" * (-len(encoded_response_id) % 4)
            response_id = base64.urlsafe_b64decode(
                encoded_response_id + padding
            ).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            _LOGGER.warning("Ignoring malformed notification response action")
            return

        if len(self._answered_response_nonces) >= _MAX_ANSWERED_RESPONSES:
            self._answered_response_nonces.pop(
                next(iter(self._answered_response_nonces))
            )
        self._answered_response_nonces[nonce] = None

        response_data = {
            "response_id": response_id,
            "response": response.lower(),
        }
        if device_id := event.data.get("device_id"):
            response_data["device_id"] = device_id
        self.hass.bus.async_fire(EVENT_RESPONSE, response_data)

    async def _async_update_data(self) -> CoordinatorData:
        # Push-only coordinator: state updated exclusively via async_set_updated_data.
        return self.data

    def _get_notify_services_for_person(self, person_entity_id: str) -> list[str]:
        persons = self.config_entry.data.get(CONF_PERSONS, {})
        return persons.get(person_entity_id, {}).get(CONF_NOTIFY_SERVICES, [])

    async def _async_call_service(
        self, service_full: str, title: str, message: str, extra: dict[str, Any]
    ) -> None:
        if "." not in service_full:
            _LOGGER.error(
                "Invalid service %r: expected 'domain.service' format", service_full
            )
            return
        domain, service = service_full.split(".", 1)
        data: dict[str, Any] = {"title": title, "message": message}
        service_extra = extra
        if (
            not service_full.startswith("notify.mobile_app_")
            and self._has_response_actions(extra)
        ):
            # Companion App actions are not portable to arbitrary providers.
            # Preserve any other provider-specific notification data.
            service_extra = {
                key: value for key, value in extra.items() if key != "actions"
            }
        if service_extra:
            data["data"] = service_extra
        await self.hass.services.async_call(domain, service, data)

    @staticmethod
    def _has_response_actions(extra: dict[str, Any]) -> bool:
        """Return whether data contains actions generated by this integration."""
        actions = extra.get("actions")
        return bool(
            isinstance(actions, list)
            and actions
            and all(
                isinstance(action, dict)
                and isinstance(action.get("action"), str)
                and _RESPONSE_ACTION_RE.match(action["action"])
                for action in actions
            )
        )

    def _with_response_preset(
        self,
        extra_data: dict[str, Any] | None,
        response_preset: str | None,
        response_id: str | None,
    ) -> dict[str, Any]:
        """Return notification data with unique Companion App response actions."""
        extra = dict(extra_data or {})
        if response_preset != RESPONSE_PRESET_YES_NO or response_id is None:
            return extra

        encoded_response_id = base64.urlsafe_b64encode(
            response_id.encode("utf-8")
        ).decode("ascii").rstrip("=")
        nonce = uuid.uuid4().hex
        yes_title, no_title = _RESPONSE_TITLES.get(
            self.hass.config.language, _RESPONSE_TITLES["en"]
        )
        extra["actions"] = [
            {
                "action": f"SNP_YES_{nonce}.{encoded_response_id}",
                "title": yes_title,
            },
            {
                "action": f"SNP_NO_{nonce}.{encoded_response_id}",
                "title": no_title,
            },
        ]
        return extra

    async def _async_notify_person(
        self, person_entity_id: str, title: str, message: str, extra: dict[str, Any]
    ) -> list[str]:
        services = self._get_notify_services_for_person(person_entity_id)
        recipients: list[str] = []
        for service_full in services:
            await self._async_call_service(service_full, title, message, extra)
            recipients.append(service_full)
        return recipients

    def _get_admin_person(self) -> str | None:
        persons = self.config_entry.data.get(CONF_PERSONS, {})
        return next(
            (eid for eid, cfg in persons.items() if cfg.get(CONF_IS_ADMIN)), None
        )

    async def _async_send_to_fallback(
        self, title: str, message: str, extra: dict[str, Any]
    ) -> str | None:
        """Send to fallback service if configured. Returns service name or None."""
        fallback = self.config_entry.data.get(CONF_FALLBACK_SERVICE, "")
        if fallback:
            await self._async_call_service(fallback, title, message, extra)
            return fallback
        return None

    def _record_sent(
        self, title: str, recipients: list[str], priority: str
    ) -> None:
        self.async_set_updated_data(
            replace(
                self.data,
                last_sent=NotificationRecord(
                    title=title,
                    sent_at=datetime.now(timezone.utc),
                    recipients=recipients,
                    priority=priority,
                ),
            )
        )

    async def async_send_notification(
        self,
        title: str,
        message: str,
        priority: str = Priority.NORMAL,
        target_override: str | None = None,
        targets: list[str] | None = None,
        extra_data: dict[str, Any] | None = None,
        response_preset: str | None = None,
        response_id: str | None = None,
    ) -> None:
        """Route a notification based on presence and configuration."""
        extra = self._with_response_preset(extra_data, response_preset, response_id)

        if target_override:
            await self._async_call_service(target_override, title, message, extra)
            self._record_sent(title, [target_override], priority)
            return

        home_persons = self.data.home_persons
        someone_home = self.data.someone_home

        if priority == Priority.HIGH:
            if someone_home:
                recipients = await self._async_notify_person(
                    home_persons[0], title, message, extra
                )
                self._record_sent(title, recipients, priority)
            elif self.config_entry.data.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK:
                fallback = await self._async_send_to_fallback(title, message, extra)
                if fallback:
                    self._record_sent(title, [fallback], priority)
            else:
                await self._enqueue(title, message, priority, extra)
            return

        if someone_home:
            target_mode = self.config_entry.data.get(CONF_TARGET_MODE, TargetMode.BROADCAST)
            recipients: list[str] = []

            if target_mode == TargetMode.BROADCAST:
                for person in home_persons:
                    recipients.extend(
                        await self._async_notify_person(person, title, message, extra)
                    )
            elif target_mode == TargetMode.SINGLE_ADMIN:
                admin = self._get_admin_person()
                person = admin if (admin and admin in home_persons) else home_persons[0]
                recipients = await self._async_notify_person(person, title, message, extra)
            elif target_mode == TargetMode.CALLER_DECIDES:
                for service_full in (targets or []):
                    await self._async_call_service(service_full, title, message, extra)
                    recipients.append(service_full)

            if recipients:
                self._record_sent(title, recipients, priority)
            return

        await self._enqueue(title, message, priority, extra)

    async def _enqueue(
        self, title: str, message: str, priority: str, extra: dict[str, Any]
    ) -> None:
        timeout_minutes = int(self.config_entry.data.get(CONF_QUEUE_TIMEOUT, 0))
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=timeout_minutes) if timeout_minutes > 0 else None
        notif = PendingNotification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            priority=priority,
            created_at=now,
            expires_at=expires_at,
            extra_data=extra,
        )
        new_queue = self.data.queue + [notif]
        self.async_set_updated_data(replace(self.data, queue=new_queue))
        await self._store.async_save(new_queue)
        if expires_at:
            self._schedule_timeout(notif)

    async def _async_drain_queue(self, arrived_person: str) -> None:
        """Drain the pending queue for the person who just arrived.

        The flag prevents two concurrent arrivals from triggering duplicate
        sends. HA's event loop is single-threaded, so the flag is set
        synchronously before the first await; any second drain task sees it
        and exits early without sending duplicates.
        """
        if self._drain_in_progress:
            return
        self._drain_in_progress = True
        try:
            queue = self.data.queue
            if not queue:
                return

            drain_ids = {n.id for n in queue}
            queue_mode = self.config_entry.data.get(CONF_QUEUE_MODE, QueueMode.FIFO)
            recipients = self._get_notify_services_for_person(arrived_person)
            if not recipients:
                _LOGGER.debug(
                    "Skipping queue drain: %s has no notify_services configured",
                    arrived_person,
                )
                return

            # A summary cannot retain per-notification action buttons. Fall back
            # to FIFO whenever at least one queued notification is actionable.
            has_actions = any(self._has_response_actions(n.extra_data) for n in queue)
            if queue_mode == QueueMode.SUMMARY and not has_actions:
                titles = ", ".join(n.title for n in queue)
                summary_msg = f"{len(queue)} messages while you were away: {titles}"
                for service_full in recipients:
                    await self._async_call_service(
                        service_full, "Missed notifications", summary_msg, {}
                    )
                last_title = "Missed notifications"
            elif queue_mode == QueueMode.LAST_ONLY:
                notif = queue[-1]
                for service_full in recipients:
                    await self._async_call_service(
                        service_full, notif.title, notif.message, notif.extra_data
                    )
                last_title = notif.title
            else:  # FIFO
                for i, notif in enumerate(queue):
                    for service_full in recipients:
                        await self._async_call_service(
                            service_full, notif.title, notif.message, notif.extra_data
                        )
                    if i < len(queue) - 1:
                        await asyncio.sleep(1)
                last_title = queue[-1].title

            for nid in drain_ids:
                if (unsub := self._timeout_unsubs.pop(nid, None)):
                    unsub()

            # Re-read self.data after the awaits above: new notifications may have
            # been enqueued via _enqueue while service calls were in flight.
            # Using the stale snapshot would overwrite those additions.
            fresh = self.data
            new_queue = [n for n in fresh.queue if n.id not in drain_ids]
            self.async_set_updated_data(
                replace(
                    fresh,
                    queue=new_queue,
                    last_sent=NotificationRecord(
                        title=last_title,
                        sent_at=datetime.now(timezone.utc),
                        recipients=recipients,
                        priority=queue[-1].priority,
                    ),
                )
            )
            await self._store.async_save(new_queue)
        finally:
            self._drain_in_progress = False

    def _schedule_timeout(self, notification: PendingNotification) -> None:
        @callback
        def _on_timeout(now: datetime) -> None:
            self._timeout_unsubs.pop(notification.id, None)
            self.hass.async_create_task(
                self._async_expire_notification(notification)
            )

        unsub = async_track_point_in_time(
            self.hass, _on_timeout, notification.expires_at
        )
        self._timeout_unsubs[notification.id] = unsub

    async def _async_expire_notification(
        self, notification: PendingNotification
    ) -> None:
        # Usually removed by the scheduled callback before this coroutine runs.
        # Also cancel it here for direct/manual expiry calls.
        if unsub := self._timeout_unsubs.pop(notification.id, None):
            unsub()
        if not any(n.id == notification.id for n in self.data.queue):
            return
        fallback_mode = self.config_entry.data.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD)

        if fallback_mode == FallbackMode.NOTIFY_FALLBACK:
            await self._async_send_to_fallback(
                notification.title, notification.message, notification.extra_data
            )

        # Re-read self.data after the potential await: notifications added
        # concurrently during the fallback call must not be overwritten.
        fresh = self.data
        new_queue = [n for n in fresh.queue if n.id != notification.id]
        self.async_set_updated_data(replace(fresh, queue=new_queue))
        await self._store.async_save(new_queue)
