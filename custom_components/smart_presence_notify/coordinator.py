"""Presence routing with durable, per-destination delivery checkpoints."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    STATE_HOME,
)
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_FALLBACK_MODE,
    CONF_FALLBACK_SERVICE,
    CONF_IS_ADMIN,
    CONF_NOTIFY_SERVICES,
    CONF_PERSONS,
    CONF_QUEUE_LIMIT,
    CONF_QUEUE_MODE,
    CONF_QUEUE_TIMEOUT,
    CONF_TARGET_MODE,
    DEFAULT_QUEUE_LIMIT,
    DOMAIN,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
    EVENT_RESPONSE,
    MAX_DELIVERY_ATTEMPTS,
    MAX_RESPONSE_TOKENS,
    RESPONSE_PRESET_YES_NO,
    RESPONSE_TIMEOUT_HOURS,
    RETRY_BASE_SECONDS,
    SERVICE_TIMEOUT_SECONDS,
    FallbackMode,
    Priority,
    QueueMode,
    TargetMode,
)
from .mobile import UnsupportedNotificationDestination, resolve_destination
from .models import (
    CoordinatorData,
    NotificationRecord,
    PendingNotification,
    ResponseToken,
    _validate_json,
)
from .sources import NotificationSources
from .store import SNPStore
from .validation import notification_target

_LOGGER = logging.getLogger(__name__)
_RESPONSE_ACTION_RE = re.compile(r"SNP_(YES|NO)_([a-f0-9]{32})\.([A-Za-z0-9_-]+)")
_RESPONSE_TITLES = {
    "de": ("Ja", "Nein"),
    "en": ("Yes", "No"),
    "es": ("Sí", "No"),
    "fr": ("Oui", "Non"),
    "it": ("Sì", "No"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _track_delivery(method):
    """Include caller-owned service tasks in unload cancellation."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        task = asyncio.current_task()
        owned = task not in self._tasks
        if owned:
            self._tasks.add(task)
        try:
            return await method(self, *args, **kwargs)
        finally:
            if owned:
                self._tasks.discard(task)

    return wrapped


class SmartPresenceNotifyCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Route notifications and retain only destinations that still need delivery."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self._store = SNPStore(hass)
        self.notification_sources = NotificationSources(hass, entry.entry_id)
        self._timeout_unsubs: dict[str, Callable[[], None]] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._presence_unsub: Callable[[], None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._item_locks: dict[str, asyncio.Lock] = {}
        self._save_lock = asyncio.Lock()
        self._response_tokens: dict[str, ResponseToken] = {}
        self._drain_in_progress = False
        self._stopped = False

    async def async_initialize(self) -> None:
        queue = await self._store.async_load()
        await self.notification_sources.async_initialize()
        home, persons = self._get_presence()
        self.async_set_updated_data(CoordinatorData(queue, None, home, persons))
        for item in queue:
            self._restore_response_token(item.extra_data)
        self._register_presence_listener()
        from .bridge import NotificationForwarder

        self._forwarder = NotificationForwarder(self)
        self._unsubs.append(self._forwarder.async_start())
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_MOBILE_APP_NOTIFICATION_ACTION,
                self._handle_notification_action,
            )
        )
        if self.hass.state is CoreState.running:
            self._start_task(self._async_reconcile())
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    self._handle_started,
                )
            )

    @callback
    def _handle_started(self, event: Event) -> None:
        self._start_task(self._async_reconcile())

    def _start_task(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        if self._stopped:
            coroutine.close()
            return
        task = self.hass.async_create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def async_shutdown(self) -> None:
        self._stopped = True
        if self._presence_unsub:
            self._presence_unsub()
            self._presence_unsub = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._timeout_unsubs.values():
            unsub()
        self._timeout_unsubs.clear()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.notification_sources.async_shutdown()

    @callback
    def _register_presence_listener(self) -> None:
        if self._presence_unsub:
            self._presence_unsub()
        configured = frozenset(self.config_entry.data.get(CONF_PERSONS, {}))

        @callback
        def event_filter(data: dict[str, Any]) -> bool:
            return data.get("entity_id") in configured

        self._presence_unsub = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._handle_state_changed,
            event_filter=event_filter,
        )

    @callback
    def async_reload_presence_listener(self) -> None:
        self._register_presence_listener()
        self._refresh_presence()
        self._start_task(self._async_reconcile())

    def _get_presence(self) -> tuple[bool, list[str]]:
        persons = [
            entity_id
            for entity_id in self.config_entry.data.get(CONF_PERSONS, {})
            if (state := self.hass.states.get(entity_id)) is not None
            and state.state == STATE_HOME
        ]
        return bool(persons), persons

    def _refresh_presence(self) -> None:
        home, persons = self._get_presence()
        if (home, persons) != (self.data.someone_home, self.data.home_persons):
            self.async_set_updated_data(
                replace(self.data, someone_home=home, home_persons=persons)
            )

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        self._refresh_presence()
        for item in self.data.queue:
            self._schedule_timeout(item)
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if (
            new is not None
            and new.state == STATE_HOME
            and (old is None or old.state != STATE_HOME)
        ):
            self._start_task(self._async_drain_queue(event.data["entity_id"]))

    async def _async_reconcile(self) -> None:
        if self._stopped:
            return
        self._refresh_presence()
        for item in list(self.data.queue):
            self._schedule_timeout(item)
            if item.expired or (item.expires_at and item.expires_at <= _now()):
                await self._async_expire_notification(item)
            elif not item.requires_presence:
                await self._process_one(item.id)
        if self.data.someone_home:
            await self._async_drain_queue(self.data.home_persons[0])

    def _find(self, notification_id: str) -> PendingNotification | None:
        return next(
            (item for item in self.data.queue if item.id == notification_id), None
        )

    def _update(self, item: PendingNotification) -> None:
        self.async_set_updated_data(
            replace(
                self.data,
                queue=[item if old.id == item.id else old for old in self.data.queue],
            )
        )

    def _remove(self, notification_id: str) -> None:
        item = self._find(notification_id)
        if unsub := self._timeout_unsubs.pop(notification_id, None):
            unsub()
        self.async_set_updated_data(
            replace(
                self.data,
                queue=[old for old in self.data.queue if old.id != notification_id],
            )
        )
        if item:
            self._forget_unsent_response(item.extra_data)
        self._item_locks.pop(notification_id, None)

    async def _persist(self) -> None:
        async with self._save_lock:
            try:
                await self._store.async_save(self.data.queue)
            except Exception as err:
                self._set_error(f"Queue persistence failed: {err}", [])
                raise HomeAssistantError(
                    "Unable to persist the notification queue"
                ) from err

    def _set_error(self, message: str, recipients: list[str]) -> None:
        _LOGGER.warning("%s", message)
        self.async_set_updated_data(
            replace(self.data, last_error=message[:255], failed_recipients=recipients)
        )

    def _record_sent(self, title: str, recipients: list[str], priority: str) -> None:
        if recipients:
            self.async_set_updated_data(
                replace(
                    self.data,
                    last_sent=NotificationRecord(
                        title, _now(), recipients, Priority(priority)
                    ),
                )
            )

    def _clear_resolved_error(self) -> None:
        if not any(item.attempts for item in self.data.queue):
            self.async_set_updated_data(
                replace(self.data, last_error=None, failed_recipients=[])
            )

    async def _async_update_data(self) -> CoordinatorData:
        return self.data

    def _get_notify_services_for_person(self, person_entity_id: str) -> list[str]:
        return (
            self.config_entry.data.get(CONF_PERSONS, {})
            .get(person_entity_id, {})
            .get(CONF_NOTIFY_SERVICES, [])
        )

    def _get_admin_person(self) -> str | None:
        return next(
            (
                person
                for person, settings in self.config_entry.data.get(
                    CONF_PERSONS, {}
                ).items()
                if settings.get(CONF_IS_ADMIN)
            ),
            None,
        )

    def _home_targets(self, priority: str) -> list[str]:
        persons = self.data.home_persons
        if not persons:
            return []
        mode = self.config_entry.data.get(CONF_TARGET_MODE, TargetMode.BROADCAST)
        if priority == Priority.HIGH:
            persons = persons[:1]
        elif mode == TargetMode.SINGLE_ADMIN:
            admin = self._get_admin_person()
            persons = [admin if admin in persons else persons[0]]
        return list(
            dict.fromkeys(
                target
                for person in persons
                for target in self._get_notify_services_for_person(person)
            )
        )

    async def _async_call_service(
        self, service_full: str, title: str, message: str, extra: dict[str, Any]
    ) -> None:
        try:
            target = notification_target(service_full, self.hass)
        except vol.Invalid as err:
            raise ServiceValidationError(str(err)) from err
        domain, service = target.split(".", 1)
        if (
            domain == "notify"
            and not self.hass.services.has_service(domain, service)
            and self.hass.states.get(target) is not None
        ):
            if extra:
                raise UnsupportedNotificationDestination(
                    f"{target} accepts only title/message; choose a compatible notify service for advanced/live data"
                )
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"title": title, "message": message},
                target={"entity_id": target},
                blocking=True,
            )
            return
        data: dict[str, Any] = {"title": title, "message": message}
        extra = deepcopy(extra)
        if not target.startswith("notify.mobile_app_") and self._has_response_actions(
            extra
        ):
            extra.pop("actions", None)
        if extra:
            data["data"] = extra
        await self.hass.services.async_call(domain, service, data, blocking=True)

    def _resolve_delivery(self, target, extra, priority, plain_bell):
        """Choose the channel using the payload and preserve requested features."""
        try:
            actual = resolve_destination(
                self.hass, target, bool(extra) or priority == Priority.HIGH
            )
        except UnsupportedNotificationDestination:
            if not plain_bell or set(extra) != {"tag"}:
                raise
            actual = resolve_destination(self.hass, target, False)
            extra = {}
        if plain_bell and set(extra) == {"tag"}:
            if (
                actual.startswith("notify.")
                and not self.hass.services.has_service(*actual.split(".", 1))
                and self.hass.states.get(actual) is not None
            ):
                # Bell replacement tags are optional on modern-only phones.
                extra = {}
        if extra.get("live_update") is True and not actual.startswith(
            "notify.mobile_app_"
        ):
            raise UnsupportedNotificationDestination(
                f"{target} cannot receive Companion Live Activities; choose a Companion phone"
            )
        return actual, self._delivery_data(extra, actual, priority)

    @staticmethod
    def _has_response_actions(extra: dict[str, Any]) -> bool:
        actions = extra.get("actions")
        return bool(
            isinstance(actions, list)
            and actions
            and all(
                isinstance(action, dict)
                and isinstance(action.get("action"), str)
                and _RESPONSE_ACTION_RE.fullmatch(action["action"])
                for action in actions
            )
        )

    def _purge_response_tokens(self) -> None:
        now = _now()
        self._response_tokens = {
            nonce: token
            for nonce, token in self._response_tokens.items()
            if token.expires_at is None or token.expires_at > now
        }

    def _restore_response_token(self, extra: dict[str, Any]) -> None:
        if not self._has_response_actions(extra):
            return
        match = _RESPONSE_ACTION_RE.fullmatch(extra["actions"][0]["action"])
        if match is None:
            return
        _, nonce, encoded = match.groups()
        try:
            response_id = base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            ).decode("utf-8")
        except (ValueError, UnicodeError):
            return
        self._purge_response_tokens()
        if len(self._response_tokens) < MAX_RESPONSE_TOKENS:
            self._response_tokens.setdefault(nonce, ResponseToken(response_id))

    def _forget_unsent_response(self, extra: dict[str, Any]) -> None:
        if self._has_response_actions(extra):
            match = _RESPONSE_ACTION_RE.fullmatch(extra["actions"][0]["action"])
            if (
                match
                and (token := self._response_tokens.get(match[2]))
                and not token.sent
            ):
                self._response_tokens.pop(match[2], None)

    def _activate_response(self, extra: dict[str, Any], target: str) -> None:
        if target.startswith("notify.mobile_app_") and self._has_response_actions(
            extra
        ):
            match = _RESPONSE_ACTION_RE.fullmatch(extra["actions"][0]["action"])
            if (
                match
                and (token := self._response_tokens.get(match[2]))
                and not token.sent
            ):
                token.sent = True
                token.expires_at = _now() + timedelta(hours=RESPONSE_TIMEOUT_HOURS)

    @callback
    def _handle_notification_action(self, event: Event) -> None:
        action = event.data.get("action")
        if not isinstance(action, str) or not (
            match := _RESPONSE_ACTION_RE.fullmatch(action)
        ):
            return
        self._purge_response_tokens()
        response, nonce, encoded = match.groups()
        token = self._response_tokens.get(nonce)
        if token is None or not token.sent or token.answered:
            return
        try:
            response_id = base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            ).decode("utf-8")
        except (ValueError, UnicodeError):
            return
        if response_id != token.response_id:
            return
        token.answered = True
        data = {"response_id": token.response_id, "response": response.lower()}
        if device_id := event.data.get("device_id"):
            data["device_id"] = device_id
        self.hass.bus.async_fire(EVENT_RESPONSE, data)

    def _with_response_preset(
        self,
        extra_data: dict[str, Any] | None,
        response_preset: str | None,
        response_id: str | None,
    ) -> dict[str, Any]:
        extra = deepcopy(extra_data or {})
        if response_preset != RESPONSE_PRESET_YES_NO or response_id is None:
            return extra
        self._purge_response_tokens()
        if len(self._response_tokens) >= MAX_RESPONSE_TOKENS:
            raise ServiceValidationError("Too many outstanding notification responses")
        encoded = (
            base64.urlsafe_b64encode(response_id.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        nonce = uuid.uuid4().hex
        yes, no = _RESPONSE_TITLES.get(
            self.hass.config.language, _RESPONSE_TITLES["en"]
        )
        extra["actions"] = [
            {"action": f"SNP_YES_{nonce}.{encoded}", "title": yes},
            {"action": f"SNP_NO_{nonce}.{encoded}", "title": no},
        ]
        self._response_tokens[nonce] = ResponseToken(response_id)
        return extra

    @staticmethod
    def _delivery_data(
        extra: dict[str, Any], target: str, priority: str
    ) -> dict[str, Any]:
        result = deepcopy(extra)
        if priority == Priority.HIGH and target.startswith("notify.mobile_app_"):
            result.setdefault("priority", "high")
            result.setdefault("ttl", 0)
            push = result.setdefault("push", {})
            if isinstance(push, dict):
                push.setdefault("interruption-level", "time-sensitive")
                push.setdefault("sound", "default")
        return result

    @_track_delivery
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
        if self._stopped:
            raise ServiceValidationError("The notification integration is unloading")
        self._refresh_presence()
        try:
            priority = Priority(priority)
            override = (
                notification_target(target_override, self.hass)
                if target_override
                else None
            )
            requested = (
                list(
                    dict.fromkeys(
                        notification_target(target, self.hass) for target in targets
                    )
                )
                if targets
                else None
            )
            _validate_json(extra_data or {})
            if extra_data and extra_data.get("live_update") is True:
                tag = extra_data.get("tag")
                if not isinstance(tag, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", tag
                ):
                    raise vol.Invalid(
                        "Live Activities require a stable tag of 1–64 letters, digits, hyphens or underscores"
                    )
        except (ValueError, vol.Invalid) as err:
            raise ServiceValidationError(str(err)) from err
        mode = self.config_entry.data.get(CONF_TARGET_MODE, TargetMode.BROADCAST)
        if mode == TargetMode.CALLER_DECIDES and not override and not requested:
            raise ServiceValidationError("targets are required in caller_decides mode")
        recipients = None
        requires_presence = True
        if override:
            recipients, requires_presence = [override], False
        elif mode == TargetMode.CALLER_DECIDES:
            recipients = requested
            requires_presence = priority != Priority.HIGH
        elif self.data.someone_home:
            recipients = self._home_targets(priority) or None
        elif (
            priority == Priority.HIGH
            and self.config_entry.data.get(CONF_FALLBACK_MODE)
            == FallbackMode.NOTIFY_FALLBACK
        ):
            fallback = self.config_entry.data.get(CONF_FALLBACK_SERVICE)
            if fallback:
                recipients, requires_presence = (
                    [notification_target(fallback, self.hass)],
                    False,
                )
        extra = self._with_response_preset(extra_data, response_preset, response_id)
        try:
            item = await self._enqueue(
                title,
                message,
                priority,
                extra,
                targets=recipients,
                requires_presence=requires_presence,
            )
        except BaseException:
            self._forget_unsent_response(extra)
            raise
        if not requires_presence or self.data.someone_home:
            await self._process_one(item.id)

    @_track_delivery
    async def async_forward_notification(
        self, title: str, message: str, targets: list[str], extra: dict[str, Any]
    ) -> None:
        if self._stopped:
            return
        # A new version replaces an older pending forward with the same mobile tag.
        # Wait for any in-flight attempt before removing its durable queue entry.
        for previous in list(self.data.queue):
            if (
                not previous.requires_presence
                and previous.extra_data.get("tag") == extra.get("tag")
                and extra.get("tag")
            ):
                lock = self._item_locks.setdefault(previous.id, asyncio.Lock())
                async with lock:
                    if self._find(previous.id) is not None:
                        self._remove(previous.id)
        item = await self._enqueue(
            title,
            message,
            Priority.NORMAL,
            extra,
            targets=targets,
            requires_presence=False,
            is_bell_forward=True,
        )
        await self._process_one(item.id)

    async def _enqueue(
        self,
        title: str,
        message: str,
        priority: str,
        extra: dict[str, Any],
        *,
        targets: list[str] | None = None,
        requires_presence: bool = True,
        is_bell_forward: bool = False,
    ) -> PendingNotification:
        if self._stopped:
            raise ServiceValidationError("The notification integration is unloading")
        limit = int(self.config_entry.data.get(CONF_QUEUE_LIMIT, DEFAULT_QUEUE_LIMIT))
        if (
            self.config_entry.data.get(CONF_QUEUE_MODE) == QueueMode.LAST_ONLY
            and requires_presence
            and not self.data.someone_home
        ):
            for old in list(self.data.queue):
                lock = self._item_locks.get(old.id)
                if (
                    old.attempts == 0
                    and old.requires_presence
                    and old.targets == targets
                    and not (lock and lock.locked())
                ):
                    self._remove(old.id)
        if len(self.data.queue) >= limit:
            self._set_error("Notification queue is full; new message was rejected", [])
            raise ServiceValidationError("Notification queue is full")
        minutes = int(self.config_entry.data.get(CONF_QUEUE_TIMEOUT, 0))
        now = _now()
        item = PendingNotification(
            str(uuid.uuid4()),
            title,
            message,
            Priority(priority),
            now,
            now + timedelta(minutes=minutes) if minutes else None,
            deepcopy(extra),
            targets=targets,
            requires_presence=requires_presence,
            is_bell_forward=is_bell_forward,
        )
        self.async_set_updated_data(replace(self.data, queue=self.data.queue + [item]))
        await self._persist()
        self._schedule_timeout(item)
        return item

    async def _process_one(
        self, notification_id: str, arrived_person: str | None = None
    ) -> None:
        if self._find(notification_id) is None:
            return
        lock = self._item_locks.setdefault(notification_id, asyncio.Lock())
        async with lock:
            item = self._find(notification_id)
            if item is None or self._stopped:
                return
            if not item.expired and item.expires_at and item.expires_at <= _now():
                await self._expire_locked(item)
                return
            if item.attempts >= MAX_DELIVERY_ATTEMPTS or (
                item.retry_at and item.retry_at > _now()
            ):
                self._schedule_timeout(item)
                return
            if item.requires_presence and not self.data.someone_home:
                self._schedule_timeout(item)
                return
            if item.targets is None:
                person = arrived_person or (
                    self.data.home_persons[0] if self.data.home_persons else None
                )
                recipients = (
                    self._get_notify_services_for_person(person) if person else []
                )
                if not recipients:
                    return
                item = replace(item, targets=list(dict.fromkeys(recipients)))
                self._update(item)
                await self._persist()
            await self._deliver_group_locked(
                [item], item.title, item.message, item.extra_data
            )

    async def _deliver_group_locked(
        self,
        items: list[PendingNotification],
        title: str,
        message: str,
        extra: dict[str, Any],
    ) -> None:
        for item in items:
            self._update(replace(item, attempts=item.attempts + 1, retry_at=None))
        await self._persist()
        recipients = list(
            dict.fromkeys(target for item in items for target in (item.targets or []))
        )
        successful, failed = [], []
        priority = (
            Priority.HIGH
            if any(item.priority == Priority.HIGH for item in items)
            else Priority.NORMAL
        )
        delivered_channels = set()
        for target in recipients:
            if self._stopped:
                return
            try:
                actual, payload = self._resolve_delivery(
                    target, extra, priority, all(item.is_bell_forward for item in items)
                )
                async with asyncio.timeout(SERVICE_TIMEOUT_SECONDS):
                    if actual not in delivered_channels:
                        await self._async_call_service(actual, title, message, payload)
                        delivered_channels.add(actual)
            except Exception as err:
                failed.append(target)
                detail = (
                    str(err)
                    if isinstance(err, UnsupportedNotificationDestination)
                    else type(err).__name__
                )
                self._set_error(
                    f"Delivery to {target} failed ({detail})", failed.copy()
                )
                continue
            successful.append(target)
            self._activate_response(extra, actual)
            for original in items:
                current = self._find(original.id)
                if current and target in (current.targets or []):
                    self._update(
                        replace(
                            current,
                            targets=[
                                pending
                                for pending in current.targets
                                if pending != target
                            ],
                            delivered_targets=list(
                                dict.fromkeys(current.delivered_targets + [target])
                            ),
                        )
                    )
            # Checkpoint each successful destination before attempting the next one.
            await self._persist()
        self._record_sent(title, successful, priority)
        for original in items:
            current = self._find(original.id)
            if current is None:
                continue
            if not current.targets:
                self._remove(current.id)
            else:
                delay = RETRY_BASE_SECONDS * 2 ** (current.attempts - 1)
                retry_at = (
                    _now() + timedelta(seconds=delay)
                    if current.attempts < MAX_DELIVERY_ATTEMPTS
                    else None
                )
                current = replace(current, retry_at=retry_at)
                self._update(current)
                self._schedule_timeout(current)
        await self._persist()
        self._clear_resolved_error()

    @_track_delivery
    async def _async_drain_queue(self, arrived_person: str) -> None:
        if self._drain_in_progress or self._stopped:
            return
        self._drain_in_progress = True
        try:
            ids = [item.id for item in self.data.queue]
            if self.config_entry.data.get(
                CONF_QUEUE_MODE
            ) == QueueMode.SUMMARY and not any(
                self._has_response_actions(item.extra_data) for item in self.data.queue
            ):
                await self._deliver_summary(ids, arrived_person)
            for index, notification_id in enumerate(ids):
                if self._stopped:
                    break
                await self._process_one(notification_id, arrived_person)
                if index < len(ids) - 1 and self._find(notification_id) is None:
                    await asyncio.sleep(1)
        finally:
            self._drain_in_progress = False

    async def _deliver_summary(self, ids: list[str], arrived_person: str) -> None:
        recipients = list(
            dict.fromkeys(self._get_notify_services_for_person(arrived_person))
        )
        if not recipients or not self.data.someone_home:
            return
        async with AsyncExitStack() as stack:
            items = []
            for notification_id in ids:
                lock = self._item_locks.setdefault(notification_id, asyncio.Lock())
                await stack.enter_async_context(lock)
                item = self._find(notification_id)
                if (
                    item
                    and item.targets is None
                    and item.attempts == 0
                    and not item.expired
                    and not self._has_response_actions(item.extra_data)
                    and (not item.expires_at or item.expires_at > _now())
                ):
                    item = replace(item, targets=recipients)
                    self._update(item)
                    items.append(item)
            if items:
                await self._deliver_group_locked(
                    items,
                    "Missed notifications",
                    f"{len(items)} messages while you were away: "
                    + ", ".join(item.title for item in items),
                    {},
                )

    def _schedule_timeout(self, notification: PendingNotification) -> None:
        if unsub := self._timeout_unsubs.pop(notification.id, None):
            unsub()
        if self._stopped:
            return
        dates = []
        if notification.expires_at and not notification.expired:
            dates.append(notification.expires_at)
        if notification.retry_at and (
            not notification.requires_presence or self.data.someone_home
        ):
            dates.append(notification.retry_at)
        if not dates:
            return

        @callback
        def wakeup(now: datetime) -> None:
            self._timeout_unsubs.pop(notification.id, None)
            self._start_task(self._process_one(notification.id))

        self._timeout_unsubs[notification.id] = async_track_point_in_time(
            self.hass, wakeup, min(dates)
        )

    async def _expire_locked(self, item: PendingNotification) -> None:
        if unsub := self._timeout_unsubs.pop(item.id, None):
            unsub()
        fallback = self.config_entry.data.get(CONF_FALLBACK_SERVICE, "")
        if (
            self.config_entry.data.get(CONF_FALLBACK_MODE)
            != FallbackMode.NOTIFY_FALLBACK
            or not fallback
        ):
            self._remove(item.id)
            await self._persist()
            return
        try:
            fallback = notification_target(fallback, self.hass)
        except vol.Invalid as err:
            self._set_error(f"Invalid fallback destination: {err}", [fallback])
            return
        if fallback in item.delivered_targets:
            self._remove(item.id)
            await self._persist()
            return
        item = replace(
            item,
            expired=True,
            targets=[fallback],
            delivered_targets=[],
            requires_presence=False,
            attempts=0,
            retry_at=None,
        )
        self._update(item)
        await self._deliver_group_locked(
            [item], item.title, item.message, item.extra_data
        )

    @_track_delivery
    async def _async_expire_notification(
        self, notification: PendingNotification
    ) -> None:
        lock = self._item_locks.setdefault(notification.id, asyncio.Lock())
        async with lock:
            item = self._find(notification.id)
            if item is None or self._stopped:
                return
            if item.expired:
                if item.attempts < MAX_DELIVERY_ATTEMPTS and (
                    not item.retry_at or item.retry_at <= _now()
                ):
                    await self._deliver_group_locked(
                        [item], item.title, item.message, item.extra_data
                    )
            else:
                await self._expire_locked(item)

    @_track_delivery
    async def async_retry_pending(self) -> None:
        for original in list(self.data.queue):
            lock = self._item_locks.setdefault(original.id, asyncio.Lock())
            async with lock:
                if item := self._find(original.id):
                    self._update(replace(item, attempts=0, retry_at=None))
        await self._persist()
        await self._async_reconcile()
