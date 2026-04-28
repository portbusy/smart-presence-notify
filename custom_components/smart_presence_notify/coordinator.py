"""Coordinator for Smart Presence Notify."""
from __future__ import annotations

import asyncio
import logging
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
    FallbackMode,
    Priority,
    QueueMode,
    TargetMode,
)
from .models import CoordinatorData, NotificationRecord, PendingNotification
from .store import SNPStore

_LOGGER = logging.getLogger(__name__)


class SmartPresenceNotifyCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Manages presence-aware notification routing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self._store = SNPStore(hass)
        self._timeout_unsubs: dict[str, Callable[[], None]] = {}
        self._presence_unsub: Callable[[], None] | None = None

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
        self._presence_unsub = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._handle_state_changed
        )
        for notification in queue:
            if notification.expires_at:
                self._schedule_timeout(notification)

    async def async_shutdown(self) -> None:
        """Cancel listeners and timeout handles."""
        if self._presence_unsub:
            self._presence_unsub()
            self._presence_unsub = None
        for unsub in self._timeout_unsubs.values():
            unsub()
        self._timeout_unsubs.clear()

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

    async def _async_update_data(self) -> CoordinatorData:
        # Push-only coordinator: state updated exclusively via async_set_updated_data.
        return self.data

    def _get_notify_services_for_person(self, person_entity_id: str) -> list[str]:
        persons = self.config_entry.data.get(CONF_PERSONS, {})
        return persons.get(person_entity_id, {}).get(CONF_NOTIFY_SERVICES, [])

    async def _async_call_service(
        self, service_full: str, title: str, message: str, extra: dict[str, Any]
    ) -> None:
        domain, service = service_full.split(".", 1)
        data: dict[str, Any] = {"title": title, "message": message}
        if extra:
            data.update(extra)
        await self.hass.services.async_call(domain, service, data)

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
    ) -> None:
        """Route a notification based on presence and configuration."""
        extra: dict[str, Any] = extra_data or {}

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
        """Drain the pending queue for the person who just arrived."""
        current = self.data
        queue = current.queue
        if not queue:
            return

        queue_mode = self.config_entry.data.get(CONF_QUEUE_MODE, QueueMode.FIFO)
        recipients = self._get_notify_services_for_person(arrived_person)
        if not recipients:
            _LOGGER.debug(
                "Skipping queue drain: %s has no notify_services configured",
                arrived_person,
            )
            return

        if queue_mode == QueueMode.SUMMARY:
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

        for notif in queue:
            if notif.id in self._timeout_unsubs:
                self._timeout_unsubs.pop(notif.id)()

        self.async_set_updated_data(
            replace(
                current,
                queue=[],
                last_sent=NotificationRecord(
                    title=last_title,
                    sent_at=datetime.now(timezone.utc),
                    recipients=recipients,
                    priority=queue[-1].priority,
                ),
            )
        )
        await self._store.async_save([])

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
        current = self.data
        if not any(n.id == notification.id for n in current.queue):
            return
        new_queue = [n for n in current.queue if n.id != notification.id]
        fallback_mode = self.config_entry.data.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD)

        if fallback_mode == FallbackMode.NOTIFY_FALLBACK:
            await self._async_send_to_fallback(
                notification.title, notification.message, notification.extra_data
            )

        self.async_set_updated_data(replace(current, queue=new_queue))
        await self._store.async_save(new_queue)
