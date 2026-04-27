# Smart Presence Notify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-compatible HA custom integration that routes mobile notifications based on household presence, with queue, priority, and timeout support.

**Architecture:** Push-based `DataUpdateCoordinator` (no polling) driven by `state_changed` events on `person.*` entities. Queue persisted via HA `Store`. Config 100% UI-driven through ConfigFlow + OptionsFlow.

**Tech Stack:** Python 3.12+, `pytest-homeassistant-custom-component`, `freezegun`, HA 2026.1+

---

## File Map

| File | Responsibility |
|---|---|
| `custom_components/smart_presence_notify/const.py` | Domain, config keys, enums |
| `custom_components/smart_presence_notify/models.py` | PendingNotification, NotificationRecord, CoordinatorData |
| `custom_components/smart_presence_notify/store.py` | Queue persistence via HA Store |
| `custom_components/smart_presence_notify/coordinator.py` | Presence logic, send/drain/timeout |
| `custom_components/smart_presence_notify/__init__.py` | Entry setup/unload, SNPRuntimeData, SNPConfigEntry |
| `custom_components/smart_presence_notify/config_flow.py` | ConfigFlow (2 steps) + OptionsFlow |
| `custom_components/smart_presence_notify/sensor.py` | queue_count, last_sent entities |
| `custom_components/smart_presence_notify/binary_sensor.py` | someone_home entity |
| `custom_components/smart_presence_notify/services.py` | Service registration + handler |
| `custom_components/smart_presence_notify/services.yaml` | Service UI schema |
| `custom_components/smart_presence_notify/strings.json` | Config flow strings |
| `custom_components/smart_presence_notify/translations/en.json` | English translations |
| `custom_components/smart_presence_notify/translations/it.json` | Italian translations |
| `tests/conftest.py` | Fixtures shared across all tests |
| `tests/test_config_flow.py` | Config flow + options flow tests |
| `tests/test_store.py` | Store serialization/load tests |
| `tests/test_coordinator.py` | All coordinator logic tests |
| `tests/test_sensor.py` | Sensor entity state tests |
| `tests/test_binary_sensor.py` | Binary sensor entity state tests |
| `tests/test_services.py` | Service call + schema tests |
| `pyproject.toml` | Project metadata + test config |
| `.github/workflows/tests.yml` | CI matrix |

---

## Task 1: Test Infrastructure

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `custom_components/smart_presence_notify/__init__.py` (stub)
- Create: `custom_components/smart_presence_notify/__init_stub_marker__` (deleted in Task 10)

- [ ] **Step 1: Create pyproject.toml**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.pytest]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create requirements_test.txt**

```
pytest-homeassistant-custom-component>=2024.6.0
pytest-asyncio>=0.23
freezegun>=1.4
```

- [ ] **Step 3: Create tests/__init__.py (empty)**

```python
```

- [ ] **Step 4: Create stub __init__.py so HA can discover the integration**

```python
"""Smart Presence Notify integration."""
```

- [ ] **Step 5: Create tests/conftest.py**

```python
"""Shared fixtures for Smart Presence Notify tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

DOMAIN = "smart_presence_notify"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Smart Presence Notify",
        data={
            "name": "Smart Presence Notify",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {
                    "notify_services": ["notify.mobile_app_mario"],
                    "is_admin": True,
                },
                "person.lucia": {
                    "notify_services": ["notify.mobile_app_lucia"],
                    "is_admin": False,
                },
            },
        },
    )


@pytest.fixture
def mock_notify_call(hass: HomeAssistant):
    """Patch hass.services.async_call and return the mock."""
    with patch.object(hass.services, "async_call") as mock_call:
        yield mock_call
```

- [ ] **Step 6: Verify test infrastructure loads**

```bash
pip install -r requirements_test.txt
pytest tests/ --collect-only
```

Expected: `no tests ran` (0 errors, 0 failures — just no tests yet)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements_test.txt tests/ custom_components/smart_presence_notify/__init__.py
git commit -m "Add test infrastructure and project scaffold"
```

---

## Task 2: const.py + models.py

**Files:**
- Create: `custom_components/smart_presence_notify/const.py`
- Create: `custom_components/smart_presence_notify/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for model serialization**

```python
# tests/test_models.py
"""Tests for data models."""
from __future__ import annotations

from datetime import datetime, timezone

from custom_components.smart_presence_notify.models import (
    CoordinatorData,
    NotificationRecord,
    PendingNotification,
)


def test_pending_notification_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    expires = datetime(2026, 4, 27, 13, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="abc-123",
        title="Test",
        message="Hello",
        priority="normal",
        created_at=now,
        expires_at=expires,
        extra_data={"push": {"sound": "default"}},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.id == "abc-123"
    assert restored.title == "Test"
    assert restored.priority == "normal"
    assert restored.created_at == now
    assert restored.expires_at == expires
    assert restored.extra_data == {"push": {"sound": "default"}}


def test_pending_notification_no_expiry_roundtrip():
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    notif = PendingNotification(
        id="xyz",
        title="T",
        message="M",
        priority="high",
        created_at=now,
        expires_at=None,
        extra_data={},
    )
    d = notif.to_dict()
    restored = PendingNotification.from_dict(d)
    assert restored.expires_at is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'custom_components.smart_presence_notify.models'`

- [ ] **Step 3: Create const.py**

```python
"""Constants for Smart Presence Notify."""
from __future__ import annotations

from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "smart_presence_notify"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

STORE_KEY = "smart_presence_notify"
STORE_VERSION = 1

# Config entry keys
CONF_TARGET_MODE = "target_mode"
CONF_QUEUE_MODE = "queue_mode"
CONF_QUEUE_TIMEOUT = "queue_timeout_minutes"
CONF_FALLBACK_MODE = "fallback_mode"
CONF_FALLBACK_SERVICE = "fallback_service"
CONF_PERSONS = "persons"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_IS_ADMIN = "is_admin"
CONF_ADMIN_PERSON = "admin_person"


class TargetMode(StrEnum):
    BROADCAST = "broadcast"
    SINGLE_ADMIN = "single_admin"
    CALLER_DECIDES = "caller_decides"


class QueueMode(StrEnum):
    LAST_ONLY = "last_only"
    FIFO = "fifo"
    SUMMARY = "summary"


class FallbackMode(StrEnum):
    DISCARD = "discard"
    NOTIFY_FALLBACK = "notify_fallback"


class Priority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
```

- [ ] **Step 4: Create models.py**

```python
"""Data models for Smart Presence Notify."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .coordinator import SmartPresenceNotifyCoordinator


@dataclass
class PendingNotification:
    id: str
    title: str
    message: str
    priority: Literal["normal", "high"]
    created_at: datetime
    expires_at: datetime | None
    extra_data: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "extra_data": self.extra_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PendingNotification:
        return cls(
            id=data["id"],
            title=data["title"],
            message=data["message"],
            priority=data["priority"],
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
            extra_data=data.get("extra_data", {}),
        )


@dataclass
class NotificationRecord:
    title: str
    sent_at: datetime
    recipients: list[str]
    priority: Literal["normal", "high"]


@dataclass
class CoordinatorData:
    queue: list[PendingNotification]
    last_sent: NotificationRecord | None
    someone_home: bool
    home_persons: list[str]


@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add custom_components/smart_presence_notify/const.py custom_components/smart_presence_notify/models.py tests/test_models.py
git commit -m "Add const.py and data models with serialization"
```

---

## Task 3: Store (Persistence Layer)

**Files:**
- Create: `custom_components/smart_presence_notify/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
"""Tests for SNPStore persistence."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smart_presence_notify.models import PendingNotification
from custom_components.smart_presence_notify.store import SNPStore


@pytest.fixture
async def store(hass: HomeAssistant) -> SNPStore:
    return SNPStore(hass)


async def test_load_empty(store: SNPStore):
    result = await store.async_load()
    assert result == []


async def test_save_and_load(store: SNPStore):
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    notifs = [
        PendingNotification(
            id="a1",
            title="Door",
            message="Open",
            priority="normal",
            created_at=now,
            expires_at=None,
            extra_data={},
        )
    ]
    await store.async_save(notifs)
    loaded = await store.async_load()
    assert len(loaded) == 1
    assert loaded[0].id == "a1"
    assert loaded[0].title == "Door"


async def test_save_empty_clears(store: SNPStore):
    now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)
    notifs = [
        PendingNotification(
            id="b1", title="T", message="M", priority="normal",
            created_at=now, expires_at=None, extra_data={}
        )
    ]
    await store.async_save(notifs)
    await store.async_save([])
    loaded = await store.async_load()
    assert loaded == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named ...store`

- [ ] **Step 3: Create store.py**

```python
"""Persistent queue storage for Smart Presence Notify."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORE_KEY, STORE_VERSION
from .models import PendingNotification


class SNPStore:
    """Wraps HA Store for PendingNotification queue."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORE_VERSION, STORE_KEY)

    async def async_load(self) -> list[PendingNotification]:
        data = await self._store.async_load()
        if not data:
            return []
        return [PendingNotification.from_dict(item) for item in data]

    async def async_save(self, queue: list[PendingNotification]) -> None:
        await self._store.async_save([n.to_dict() for n in queue])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_store.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add custom_components/smart_presence_notify/store.py tests/test_store.py
git commit -m "Add SNPStore for queue persistence"
```

---

## Task 4: Config Flow — Step 1 (Global Settings)

**Files:**
- Create: `custom_components/smart_presence_notify/config_flow.py`
- Create: `custom_components/smart_presence_notify/strings.json`
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing test for step 1**

```python
# tests/test_config_flow.py
"""Tests for config flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smart_presence_notify.const import DOMAIN


async def test_step1_form_shown(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step1_invalid_timeout(hass: HomeAssistant):
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        hass.config_entries.flow.async_progress()[0]["flow_id"],
        user_input={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": -1,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert "queue_timeout_minutes" in result["errors"]


async def test_step1_proceeds_to_step2(hass: HomeAssistant):
    hass.states.async_set("person.mario", "home")
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        hass.config_entries.flow.async_progress()[0]["flow_id"],
        user_input={
            "name": "My Notifier",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "persons"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config_flow.py::test_step1_form_shown -v
```

Expected: `FAILED` — config flow not registered

- [ ] **Step 3: Create config_flow.py (step 1 only)**

```python
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

STEP1_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Smart Presence Notify"): str,
        vol.Required(CONF_TARGET_MODE, default=TargetMode.BROADCAST): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[m.value for m in TargetMode],
                translation_key=CONF_TARGET_MODE,
            )
        ),
        vol.Required(CONF_QUEUE_MODE, default=QueueMode.FIFO): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[m.value for m in QueueMode],
                translation_key=CONF_QUEUE_MODE,
            )
        ),
        vol.Required(CONF_QUEUE_TIMEOUT, default=0): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=10080, step=1, mode="box")
        ),
        vol.Required(CONF_FALLBACK_MODE, default=FallbackMode.DISCARD): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[m.value for m in FallbackMode],
                translation_key=CONF_FALLBACK_MODE,
            )
        ),
        vol.Optional(CONF_FALLBACK_SERVICE, default=""): str,
    }
)


class SNPConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Smart Presence Notify."""

    VERSION = 1
    _global_data: dict

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            timeout = user_input.get(CONF_QUEUE_TIMEOUT, 0)
            if int(timeout) < 0:
                errors[CONF_QUEUE_TIMEOUT] = "invalid_timeout"
            elif (
                user_input.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK
                and not user_input.get(CONF_FALLBACK_SERVICE, "").strip()
            ):
                errors[CONF_FALLBACK_SERVICE] = "fallback_service_required"

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(timeout)
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP1_SCHEMA,
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        person_entities = [
            eid for eid in self.hass.states.entity_ids("person")
        ]
        notify_options = [
            s
            for s in self.hass.services.async_services_for_domain("notify")
        ]
        notify_service_options = [f"notify.{s}" for s in notify_options]

        if user_input is not None:
            persons = _parse_persons_input(user_input, person_entities)
            target_mode = self._global_data.get(CONF_TARGET_MODE)

            if not persons:
                errors["base"] = "no_persons"
            elif target_mode == TargetMode.SINGLE_ADMIN:
                admin_count = sum(1 for p in persons.values() if p.get(CONF_IS_ADMIN))
                if admin_count != 1:
                    errors["base"] = "admin_required"

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
        return SNPOptionsFlow(config_entry)


class SNPOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow (same as config flow)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._global_data: dict = {}

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        defaults = self._entry.data

        if user_input is not None:
            timeout = user_input.get(CONF_QUEUE_TIMEOUT, 0)
            if int(timeout) < 0:
                errors[CONF_QUEUE_TIMEOUT] = "invalid_timeout"
            elif (
                user_input.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK
                and not user_input.get(CONF_FALLBACK_SERVICE, "").strip()
            ):
                errors[CONF_FALLBACK_SERVICE] = "fallback_service_required"

            if not errors:
                self._global_data = dict(user_input)
                self._global_data[CONF_QUEUE_TIMEOUT] = int(timeout)
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=defaults.get("name", "Smart Presence Notify")): str,
                    vol.Required(CONF_TARGET_MODE, default=defaults.get(CONF_TARGET_MODE, TargetMode.BROADCAST)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=[m.value for m in TargetMode])
                    ),
                    vol.Required(CONF_QUEUE_MODE, default=defaults.get(CONF_QUEUE_MODE, QueueMode.FIFO)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=[m.value for m in QueueMode])
                    ),
                    vol.Required(CONF_QUEUE_TIMEOUT, default=defaults.get(CONF_QUEUE_TIMEOUT, 0)): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0, max=10080, step=1, mode="box")
                    ),
                    vol.Required(CONF_FALLBACK_MODE, default=defaults.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD)): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=[m.value for m in FallbackMode])
                    ),
                    vol.Optional(CONF_FALLBACK_SERVICE, default=defaults.get(CONF_FALLBACK_SERVICE, "")): str,
                }
            ),
            errors=errors,
        )

    async def async_step_persons(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        person_entities = list(self.hass.states.entity_ids("person"))
        notify_options = list(self.hass.services.async_services_for_domain("notify"))
        notify_service_options = [f"notify.{s}" for s in notify_options]

        if user_input is not None:
            persons = _parse_persons_input(user_input, person_entities)
            target_mode = self._global_data.get(CONF_TARGET_MODE)

            if not persons:
                errors["base"] = "no_persons"
            elif target_mode == TargetMode.SINGLE_ADMIN:
                admin_count = sum(1 for p in persons.values() if p.get(CONF_IS_ADMIN))
                if admin_count != 1:
                    errors["base"] = "admin_required"

            if not errors:
                new_data = {**self._entry.data, **self._global_data, CONF_PERSONS: persons}
                self.hass.config_entries.async_update_entry(self._entry, data=new_data)
                return self.async_create_entry(title="", data={})

        schema = _build_persons_schema(
            person_entities,
            notify_service_options,
            self._global_data.get(CONF_TARGET_MODE),
            defaults=self._entry.data.get(CONF_PERSONS, {}),
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
```

- [ ] **Step 4: Create strings.json**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Global Settings",
        "data": {
          "name": "Integration Name",
          "target_mode": "Target Mode",
          "queue_mode": "Queue Mode",
          "queue_timeout_minutes": "Queue Timeout (minutes, 0 = disabled)",
          "fallback_mode": "Timeout Fallback",
          "fallback_service": "Fallback Notify Service"
        }
      },
      "persons": {
        "title": "Person — Notify Mapping",
        "description": "Select one or more notify services for each person. The first service is the primary device.",
        "data": {
          "admin_person": "Admin Person (receives notifications when target mode is single admin)"
        }
      }
    },
    "error": {
      "invalid_timeout": "Timeout must be 0 or greater",
      "fallback_service_required": "Fallback service is required when fallback mode is notify_fallback",
      "no_persons": "At least one person with a notify service must be configured",
      "admin_required": "Exactly one admin must be selected in single_admin mode"
    },
    "abort": {
      "already_configured": "Integration is already configured"
    }
  },
  "options": {
    "step": {
      "user": {
        "title": "Update Global Settings",
        "data": {
          "name": "Integration Name",
          "target_mode": "Target Mode",
          "queue_mode": "Queue Mode",
          "queue_timeout_minutes": "Queue Timeout (minutes, 0 = disabled)",
          "fallback_mode": "Timeout Fallback",
          "fallback_service": "Fallback Notify Service"
        }
      },
      "persons": {
        "title": "Update Person — Notify Mapping",
        "data": {
          "admin_person": "Admin Person"
        }
      }
    },
    "error": {
      "invalid_timeout": "Timeout must be 0 or greater",
      "fallback_service_required": "Fallback service is required when fallback mode is notify_fallback",
      "no_persons": "At least one person with a notify service must be configured",
      "admin_required": "Exactly one admin must be selected in single_admin mode"
    }
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_config_flow.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add custom_components/smart_presence_notify/config_flow.py custom_components/smart_presence_notify/strings.json tests/test_config_flow.py
git commit -m "Add config flow (global settings + person mapping) and options flow"
```

---

## Task 5: Config Flow — Validation + Options Flow Tests

**Files:**
- Modify: `tests/test_config_flow.py`

- [ ] **Step 1: Add validation + options flow tests**

Append to `tests/test_config_flow.py`:

```python
async def test_step2_no_persons_shows_error(hass: HomeAssistant):
    """Person step with no persons configured shows error."""
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    # No person entities in hass, so persons form is empty → error
    result = await hass.config_entries.flow.async_configure(flow_id, user_input={})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_persons"


async def test_full_flow_creates_entry(hass: HomeAssistant):
    """Full flow with person and notify service creates a config entry."""
    hass.states.async_set("person.mario", "home")
    # Register a fake notify service
    hass.services.async_register("notify", "mobile_app_mario", lambda call: None)

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Home Notifier",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 30,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={"person.mario__services": ["notify.mobile_app_mario"]},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["persons"]["person.mario"]["notify_services"] == [
        "notify.mobile_app_mario"
    ]
    assert result["data"]["queue_timeout_minutes"] == 30


async def test_single_admin_no_admin_selected_shows_error(hass: HomeAssistant):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    hass.services.async_register("notify", "mobile_app_mario", lambda call: None)
    hass.services.async_register("notify", "mobile_app_lucia", lambda call: None)

    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow_id = hass.config_entries.flow.async_progress()[0]["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "name": "Test",
            "target_mode": "single_admin",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
        },
    )
    # Submit persons without admin_person field
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        user_input={
            "person.mario__services": ["notify.mobile_app_mario"],
            "person.lucia__services": ["notify.mobile_app_lucia"],
            # No admin_person → no admin → error
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "admin_required"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_config_flow.py -v
```

Expected: `6 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_flow.py
git commit -m "Add validation and options flow tests for config flow"
```

---

## Task 6: Coordinator — Scaffold + Presence Detection

**Files:**
- Create: `custom_components/smart_presence_notify/coordinator.py`
- Create: `tests/test_coordinator.py`

- [ ] **Step 1: Write failing tests for presence detection**

```python
# tests/test_coordinator.py
"""Tests for SmartPresenceNotifyCoordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN
from custom_components.smart_presence_notify.coordinator import (
    SmartPresenceNotifyCoordinator,
)


@pytest.fixture
async def coordinator(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    return coord


async def test_someone_home_when_person_is_home(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is True
    assert "person.mario" in coord.data.home_persons


async def test_nobody_home_when_all_away(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()
    assert coord.data.someone_home is False
    assert coord.data.home_persons == []


async def test_presence_updates_on_state_change(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    assert coord.data.someone_home is False
    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()
    assert coord.data.someone_home is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_coordinator.py -v
```

Expected: `ModuleNotFoundError: ...coordinator`

- [ ] **Step 3: Create coordinator.py**

```python
"""Coordinator for Smart Presence Notify."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
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
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self._entry = entry
        self._store = SNPStore(hass)
        self._timeout_unsubs: dict[str, Callable] = {}
        self._presence_unsub: Callable | None = None

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
            "state_changed", self._handle_state_changed
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
        """Return (someone_home, home_person_entity_ids) from current HA state."""
        configured_persons = self._entry.data.get(CONF_PERSONS, {})
        home_persons = [
            entity_id
            for entity_id in configured_persons
            if self.hass.states.get(entity_id) is not None
            and self.hass.states.get(entity_id).state == "home"
        ]
        return bool(home_persons), home_persons

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        entity_id: str = event.data.get("entity_id", "")
        if not entity_id.startswith("person."):
            return
        configured_persons = self._entry.data.get(CONF_PERSONS, {})
        if entity_id not in configured_persons:
            return

        someone_home, home_persons = self._get_presence()
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        # Update coordinator data
        current = self.data
        self.async_set_updated_data(
            CoordinatorData(
                queue=current.queue,
                last_sent=current.last_sent,
                someone_home=someone_home,
                home_persons=home_persons,
            )
        )

        # Drain queue if person just arrived home
        arrived = (
            new_state is not None
            and new_state.state == "home"
            and (old_state is None or old_state.state != "home")
        )
        if arrived and current.queue:
            self.hass.async_create_task(
                self._async_drain_queue(entity_id)
            )

    async def _async_update_data(self) -> CoordinatorData:
        return self.data

    def _get_notify_services_for_person(self, person_entity_id: str) -> list[str]:
        persons = self._entry.data.get(CONF_PERSONS, {})
        return persons.get(person_entity_id, {}).get(CONF_NOTIFY_SERVICES, [])

    async def _async_call_service(
        self, service_full: str, title: str, message: str, extra: dict
    ) -> None:
        """Call a notify.* service."""
        domain, service = service_full.split(".", 1)
        data = {"title": title, "message": message}
        if extra:
            data.update(extra)
        await self.hass.services.async_call(domain, service, data)

    async def _async_notify_person(
        self, person_entity_id: str, title: str, message: str, extra: dict
    ) -> list[str]:
        """Notify all devices for a person. Returns list of services called."""
        services = self._get_notify_services_for_person(person_entity_id)
        recipients: list[str] = []
        for service_full in services:
            await self._async_call_service(service_full, title, message, extra)
            recipients.append(service_full)
        return recipients

    def _get_admin_person(self) -> str | None:
        persons = self._entry.data.get(CONF_PERSONS, {})
        return next(
            (eid for eid, cfg in persons.items() if cfg.get(CONF_IS_ADMIN)), None
        )

    def _record_sent(
        self, title: str, recipients: list[str], priority: str
    ) -> None:
        current = self.data
        self.async_set_updated_data(
            CoordinatorData(
                queue=current.queue,
                last_sent=NotificationRecord(
                    title=title,
                    sent_at=datetime.now(timezone.utc),
                    recipients=recipients,
                    priority=priority,
                ),
                someone_home=current.someone_home,
                home_persons=current.home_persons,
            )
        )

    async def async_send_notification(
        self,
        title: str,
        message: str,
        priority: str = Priority.NORMAL,
        target_override: str | None = None,
        targets: list[str] | None = None,
        extra_data: dict | None = None,
    ) -> None:
        """Route a notification based on presence and configuration."""
        extra = extra_data or {}

        # Branch 1: direct override
        if target_override:
            await self._async_call_service(target_override, title, message, extra)
            self._record_sent(title, [target_override], priority)
            return

        someone_home, home_persons = self._get_presence()

        # Branch 2: high priority
        if priority == Priority.HIGH:
            if someone_home:
                person = home_persons[0]
                recipients = await self._async_notify_person(person, title, message, extra)
                self._record_sent(title, recipients, priority)
            elif self._entry.data.get(CONF_FALLBACK_MODE) == FallbackMode.NOTIFY_FALLBACK:
                fallback = self._entry.data.get(CONF_FALLBACK_SERVICE, "")
                if fallback:
                    await self._async_call_service(fallback, title, message, extra)
                    self._record_sent(title, [fallback], priority)
            else:
                await self._enqueue(title, message, priority, extra)
            return

        # Branch 3: normal priority, someone home
        if someone_home:
            target_mode = self._entry.data.get(CONF_TARGET_MODE, TargetMode.BROADCAST)
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

        # Branch 4: nobody home — enqueue
        await self._enqueue(title, message, priority, extra)

    async def _enqueue(
        self, title: str, message: str, priority: str, extra: dict
    ) -> None:
        import uuid
        timeout_minutes = self._entry.data.get(CONF_QUEUE_TIMEOUT, 0)
        now = datetime.now(timezone.utc)
        expires_at = (
            now + timedelta(minutes=int(timeout_minutes))
            if int(timeout_minutes) > 0
            else None
        )
        notif = PendingNotification(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            priority=priority,
            created_at=now,
            expires_at=expires_at,
            extra_data=extra,
        )
        current = self.data
        new_queue = list(current.queue) + [notif]
        self.async_set_updated_data(
            CoordinatorData(
                queue=new_queue,
                last_sent=current.last_sent,
                someone_home=current.someone_home,
                home_persons=current.home_persons,
            )
        )
        await self._store.async_save(new_queue)
        if expires_at:
            self._schedule_timeout(notif)

    async def _async_drain_queue(self, arrived_person: str) -> None:
        """Drain the pending queue for the person who just arrived."""
        current = self.data
        queue = list(current.queue)
        if not queue:
            return

        queue_mode = self._entry.data.get(CONF_QUEUE_MODE, QueueMode.FIFO)

        if queue_mode == QueueMode.LAST_ONLY:
            to_send = [queue[-1]]
        else:
            to_send = queue

        recipients = self._get_notify_services_for_person(arrived_person)

        if queue_mode == QueueMode.SUMMARY:
            titles = ", ".join(n.title for n in to_send)
            summary_msg = f"{len(to_send)} messages while you were away: {titles}"
            for service_full in recipients:
                await self._async_call_service(
                    service_full, "Missed notifications", summary_msg, {}
                )
            last_title = "Missed notifications"
        else:
            last_title = to_send[-1].title
            for i, notif in enumerate(to_send):
                for service_full in recipients:
                    await self._async_call_service(
                        service_full, notif.title, notif.message, notif.extra_data
                    )
                if i < len(to_send) - 1:
                    await asyncio.sleep(1)

        # Cancel timeouts for drained notifications
        for notif in queue:
            if notif.id in self._timeout_unsubs:
                self._timeout_unsubs.pop(notif.id)()

        self.async_set_updated_data(
            CoordinatorData(
                queue=[],
                last_sent=NotificationRecord(
                    title=last_title,
                    sent_at=datetime.now(timezone.utc),
                    recipients=recipients,
                    priority=queue[-1].priority,
                ),
                someone_home=current.someone_home,
                home_persons=current.home_persons,
            )
        )
        await self._store.async_save([])

    def _schedule_timeout(self, notification: PendingNotification) -> None:
        """Schedule expiry callback for a queued notification."""
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
        """Handle expiry of a queued notification."""
        current = self.data
        new_queue = [n for n in current.queue if n.id != notification.id]
        fallback_mode = self._entry.data.get(CONF_FALLBACK_MODE, FallbackMode.DISCARD)

        if fallback_mode == FallbackMode.NOTIFY_FALLBACK:
            fallback = self._entry.data.get(CONF_FALLBACK_SERVICE, "")
            if fallback:
                await self._async_call_service(
                    fallback,
                    notification.title,
                    notification.message,
                    notification.extra_data,
                )

        self.async_set_updated_data(
            CoordinatorData(
                queue=new_queue,
                last_sent=current.last_sent,
                someone_home=current.someone_home,
                home_persons=current.home_persons,
            )
        )
        await self._store.async_save(new_queue)
```

- [ ] **Step 4: Run presence tests**

```bash
pytest tests/test_coordinator.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add custom_components/smart_presence_notify/coordinator.py tests/test_coordinator.py
git commit -m "Add coordinator with presence detection and full routing/queue/timeout logic"
```

---

## Task 7: Coordinator — Send Flow Tests

**Files:**
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Append send flow tests**

```python
# Append to tests/test_coordinator.py

async def test_send_broadcast_to_home_persons(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call") as mock_call:
        await coord.async_send_notification("Door", "Open", priority="normal")
        mock_call.assert_called_once_with(
            "notify", "mobile_app_mario", {"title": "Door", "message": "Open"}
        )
    assert coord.data.last_sent.title == "Door"
    assert coord.data.last_sent.recipients == ["notify.mobile_app_mario"]


async def test_send_target_override(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call") as mock_call:
        await coord.async_send_notification(
            "Test", "Msg", target_override="notify.telegram"
        )
        mock_call.assert_called_once_with(
            "notify", "telegram", {"title": "Test", "message": "Msg"}
        )


async def test_high_priority_bypasses_queue_sends_to_first_home(hass, mock_config_entry):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call") as mock_call:
        await coord.async_send_notification("Alert", "Fire!", priority="high")
        mock_call.assert_called_once()
    assert coord.data.queue == []


async def test_normal_priority_nobody_home_enqueues(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call") as mock_call:
        await coord.async_send_notification("Door", "Open")
        mock_call.assert_not_called()
    assert len(coord.data.queue) == 1
    assert coord.data.queue[0].title == "Door"


async def test_high_priority_nobody_home_uses_fallback(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 0,
            "fallback_mode": "notify_fallback",
            "fallback_service": "notify.telegram",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call") as mock_call:
        await coord.async_send_notification("Alert", "Fire!", priority="high")
        mock_call.assert_called_once_with(
            "notify", "telegram", {"title": "Alert", "message": "Fire!"}
        )
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_coordinator.py -v
```

Expected: all pass (count grows)

- [ ] **Step 3: Commit**

```bash
git add tests/test_coordinator.py
git commit -m "Add send flow tests for coordinator"
```

---

## Task 8: Coordinator — Queue Drain Tests

**Files:**
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Append drain tests**

```python
# Append to tests/test_coordinator.py

async def test_drain_fifo_on_arrival(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("Msg1", "Body1")
        await coord.async_send_notification("Msg2", "Body2")

    assert len(coord.data.queue) == 2

    calls = []
    with patch.object(hass.services, "async_call", side_effect=lambda *a, **kw: calls.append(a)):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            hass.states.async_set("person.mario", "home")
            await hass.async_block_till_done()

    assert coord.data.queue == []
    titles = [c[2]["title"] for c in calls]
    assert titles == ["Msg1", "Msg2"]


async def test_drain_last_only_on_arrival(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "last_only",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("First", "B1")
        await coord.async_send_notification("Last", "B2")

    calls = []
    with patch.object(hass.services, "async_call", side_effect=lambda *a, **kw: calls.append(a)):
        hass.states.async_set("person.mario", "home")
        await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0][2]["title"] == "Last"


async def test_drain_summary_on_arrival(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "summary",
            "queue_timeout_minutes": 0,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("Door", "Open")
        await coord.async_send_notification("Window", "Open")

    calls = []
    with patch.object(hass.services, "async_call", side_effect=lambda *a, **kw: calls.append(a)):
        hass.states.async_set("person.mario", "home")
        await hass.async_block_till_done()

    assert len(calls) == 1
    assert "2 messages" in calls[0][2]["message"]
    assert "Door" in calls[0][2]["message"]
    assert "Window" in calls[0][2]["message"]
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_coordinator.py -v
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_coordinator.py
git commit -m "Add queue drain tests (fifo, last_only, summary)"
```

---

## Task 9: Coordinator — Timeout Tests

**Files:**
- Modify: `tests/test_coordinator.py`

- [ ] **Step 1: Append timeout tests**

```python
# Append to tests/test_coordinator.py
from freezegun import freeze_time
from datetime import timedelta


async def test_notification_expires_discard(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 60,
            "fallback_mode": "discard",
            "fallback_service": "",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("Temp", "Body")

    assert len(coord.data.queue) == 1
    notif = coord.data.queue[0]

    # Directly trigger expiry
    await coord._async_expire_notification(notif)

    assert coord.data.queue == []


async def test_notification_expires_with_fallback(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Test",
            "target_mode": "broadcast",
            "queue_mode": "fifo",
            "queue_timeout_minutes": 60,
            "fallback_mode": "notify_fallback",
            "fallback_service": "notify.telegram",
            "persons": {
                "person.mario": {"notify_services": ["notify.mobile_app_mario"], "is_admin": True}
            },
        },
    )
    hass.states.async_set("person.mario", "not_home")
    entry.add_to_hass(hass)
    coord = SmartPresenceNotifyCoordinator(hass, entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("Alert", "Body")

    notif = coord.data.queue[0]

    with patch.object(hass.services, "async_call") as mock_call:
        await coord._async_expire_notification(notif)
        mock_call.assert_called_once_with(
            "notify", "telegram", {"title": "Alert", "message": "Body"}
        )

    assert coord.data.queue == []


async def test_queue_persists_across_reinit(hass, mock_config_entry):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)

    coord = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord.async_initialize()

    with patch.object(hass.services, "async_call"):
        await coord.async_send_notification("Persist", "Me")

    assert len(coord.data.queue) == 1

    # Simulate restart by creating a new coordinator with same hass/entry
    coord2 = SmartPresenceNotifyCoordinator(hass, mock_config_entry)
    await coord2.async_initialize()

    assert len(coord2.data.queue) == 1
    assert coord2.data.queue[0].title == "Persist"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_coordinator.py -v
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_coordinator.py
git commit -m "Add timeout and persistence tests for coordinator"
```

---

## Task 10: __init__.py (Entry Setup / Unload)

**Files:**
- Modify: `custom_components/smart_presence_notify/__init__.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_init.py
"""Tests for integration setup and teardown."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


async def test_setup_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "LOADED"


async def test_unload_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state.name == "NOT_LOADED"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_init.py -v
```

Expected: `FAILED` — no platforms registered yet

- [ ] **Step 3: Replace __init__.py with full implementation**

```python
"""Smart Presence Notify integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import SmartPresenceNotifyCoordinator
from .models import SNPRuntimeData
from .services import async_register_services, async_unregister_services

type SNPConfigEntry = ConfigEntry[SNPRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    coordinator = SmartPresenceNotifyCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = SNPRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_services(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SNPConfigEntry) -> bool:
    coordinator: SmartPresenceNotifyCoordinator = entry.runtime_data.coordinator
    await coordinator.async_shutdown()
    async_unregister_services(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 4: Create stub services.py so the import works (full impl in Task 13)**

```python
"""Service stubs — implemented in Task 13."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    pass


def async_unregister_services(hass: HomeAssistant) -> None:
    pass
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_init.py -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add custom_components/smart_presence_notify/__init__.py custom_components/smart_presence_notify/services.py tests/test_init.py
git commit -m "Implement async_setup_entry and async_unload_entry"
```

---

## Task 11: Sensor Entities

**Files:**
- Create: `custom_components/smart_presence_notify/sensor.py`
- Create: `tests/test_sensor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sensor.py
"""Tests for sensor entities."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN
from custom_components.smart_presence_notify.models import (
    CoordinatorData,
    NotificationRecord,
    PendingNotification,
)


async def test_queue_count_sensor_initial_zero(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.smart_presence_notify_queue_count")
    assert state is not None
    assert state.state == "0"


async def test_queue_count_sensor_updates(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator
    with patch.object(hass.services, "async_call"):
        await coordinator.async_send_notification("Test", "Body")

    state = hass.states.get("sensor.smart_presence_notify_queue_count")
    assert state.state == "1"
    assert state.attributes["queue"][0]["title"] == "Test"


async def test_last_sent_sensor_unknown_initially(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.smart_presence_notify_last_sent")
    assert state is not None
    assert state.state in ("unknown", "unavailable", "")
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_sensor.py -v
```

Expected: `AssertionError` — sensor entities not registered

- [ ] **Step 3: Create sensor.py**

```python
"""Sensor entities for Smart Presence Notify."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartPresenceNotifyCoordinator
from .models import CoordinatorData, SNPRuntimeData


@dataclass(frozen=True, kw_only=True)
class SNPSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], StateType]
    extra_fn: Callable[[CoordinatorData], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[SNPSensorDescription, ...] = (
    SNPSensorDescription(
        key="queue_count",
        name="Queue Count",
        icon="mdi:bell-badge",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="notifications",
        value_fn=lambda data: len(data.queue),
        extra_fn=lambda data: {
            "queue": [
                {
                    "id": n.id,
                    "title": n.title,
                    "priority": n.priority,
                    "expires_at": n.expires_at.isoformat() if n.expires_at else None,
                }
                for n in data.queue
            ]
        },
    ),
    SNPSensorDescription(
        key="last_sent",
        name="Last Sent",
        icon="mdi:bell-check",
        value_fn=lambda data: data.last_sent.title if data.last_sent else None,
        extra_fn=lambda data: (
            {
                "sent_at": data.last_sent.sent_at.isoformat(),
                "recipients": data.last_sent.recipients,
                "priority": data.last_sent.priority,
            }
            if data.last_sent
            else {}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: SNPRuntimeData = entry.runtime_data
    async_add_entities(
        SNPSensorEntity(runtime.coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    )


class SNPSensorEntity(CoordinatorEntity[SmartPresenceNotifyCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: SNPSensorDescription

    def __init__(
        self,
        coordinator: SmartPresenceNotifyCoordinator,
        description: SNPSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get("name", "Smart Presence Notify"),
            manufacturer="Smart Presence Notify",
        )

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_fn:
            return self.entity_description.extra_fn(self.coordinator.data)
        return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_sensor.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add custom_components/smart_presence_notify/sensor.py tests/test_sensor.py
git commit -m "Add sensor entities (queue_count, last_sent)"
```

---

## Task 12: Binary Sensor Entity

**Files:**
- Create: `custom_components/smart_presence_notify/binary_sensor.py`
- Create: `tests/test_binary_sensor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_binary_sensor.py
"""Tests for binary sensor entities."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


async def test_someone_home_off_when_all_away(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["home_persons"] == []


async def test_someone_home_on_when_person_home(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    hass.states.async_set("person.lucia", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "on"
    assert "person.mario" in state.attributes["home_persons"]


async def test_someone_home_updates_on_arrival(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "not_home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "off"

    hass.states.async_set("person.mario", "home")
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.smart_presence_notify_someone_home")
    assert state.state == "on"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_binary_sensor.py -v
```

Expected: `AssertionError` — binary sensor not registered

- [ ] **Step 3: Create binary_sensor.py**

```python
"""Binary sensor entities for Smart Presence Notify."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartPresenceNotifyCoordinator
from .models import SNPRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: SNPRuntimeData = entry.runtime_data
    async_add_entities([SNPSomeoneHomeSensor(runtime.coordinator, entry)])


class SNPSomeoneHomeSensor(
    CoordinatorEntity[SmartPresenceNotifyCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _attr_name = "Someone Home"
    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_icon = "mdi:home-account"

    def __init__(
        self,
        coordinator: SmartPresenceNotifyCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_someone_home"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get("name", "Smart Presence Notify"),
            manufacturer="Smart Presence Notify",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.someone_home

    @property
    def extra_state_attributes(self) -> dict:
        return {"home_persons": self.coordinator.data.home_persons}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_binary_sensor.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add custom_components/smart_presence_notify/binary_sensor.py tests/test_binary_sensor.py
git commit -m "Add binary sensor entity (someone_home)"
```

---

## Task 13: Service Registration

**Files:**
- Modify: `custom_components/smart_presence_notify/services.py`
- Create: `custom_components/smart_presence_notify/services.yaml`
- Create: `tests/test_services.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services.py
"""Tests for smart_presence_notify.send service."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_presence_notify.const import DOMAIN


async def test_service_send_calls_coordinator(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    hass.states.async_set("person.mario", "home")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(coordinator, "async_send_notification") as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "send",
            {"title": "Test", "message": "Hello", "priority": "normal"},
            blocking=True,
        )
        mock_send.assert_called_once_with(
            title="Test",
            message="Hello",
            priority="normal",
            target_override=None,
            targets=None,
            extra_data=None,
        )


async def test_service_send_missing_title_raises(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN,
            "send",
            {"message": "no title"},
            blocking=True,
        )


async def test_service_send_with_target_override(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
):
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    with patch.object(coordinator, "async_send_notification") as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "send",
            {
                "title": "Alert",
                "message": "Body",
                "priority": "high",
                "target_override": "notify.telegram",
            },
            blocking=True,
        )
        mock_send.assert_called_once_with(
            title="Alert",
            message="Body",
            priority="high",
            target_override="notify.telegram",
            targets=None,
            extra_data=None,
        )
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_services.py -v
```

Expected: service `smart_presence_notify.send` not found

- [ ] **Step 3: Replace services.py with full implementation**

```python
"""Service registration for Smart Presence Notify."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, Priority
from .models import SNPRuntimeData

SERVICE_SEND = "send"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("priority", default=Priority.NORMAL): vol.In(
            [p.value for p in Priority]
        ),
        vol.Optional("target_override"): cv.string,
        vol.Optional("targets"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("data"): dict,
    }
)


async def async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND):
        return

    async def handle_send(call: ServiceCall) -> None:
        runtime: SNPRuntimeData = entry.runtime_data
        coordinator = runtime.coordinator
        await coordinator.async_send_notification(
            title=call.data["title"],
            message=call.data["message"],
            priority=call.data.get("priority", Priority.NORMAL),
            target_override=call.data.get("target_override"),
            targets=call.data.get("targets"),
            extra_data=call.data.get("data"),
        )

    hass.services.async_register(DOMAIN, SERVICE_SEND, handle_send, SERVICE_SCHEMA)


def async_unregister_services(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE_SEND)
```

- [ ] **Step 4: Create services.yaml**

```yaml
send:
  name: Send Notification
  description: Send a presence-aware notification. Delivered to home members or queued for the first person who returns.
  fields:
    title:
      name: Title
      description: Notification title.
      required: true
      selector:
        text:
    message:
      name: Message
      description: Notification body.
      required: true
      selector:
        text:
    priority:
      name: Priority
      description: High priority bypasses the queue and controls device sound/interruption.
      required: false
      default: normal
      selector:
        select:
          options:
            - normal
            - high
    target_override:
      name: Target Override
      description: Send directly to this notify service, bypassing all presence logic. E.g. notify.telegram.
      required: false
      selector:
        text:
    targets:
      name: Targets
      description: List of notify services to use when target_mode is caller_decides.
      required: false
      selector:
        object:
    data:
      name: Extra Data
      description: Additional data passed verbatim to the notify service (e.g. push sound).
      required: false
      selector:
        object:
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_services.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add custom_components/smart_presence_notify/services.py custom_components/smart_presence_notify/services.yaml tests/test_services.py
git commit -m "Implement smart_presence_notify.send service with voluptuous schema"
```

---

## Task 14: Translations

**Files:**
- Create: `custom_components/smart_presence_notify/translations/en.json`
- Create: `custom_components/smart_presence_notify/translations/it.json`

- [ ] **Step 1: Create translations/en.json**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Global Settings",
        "data": {
          "name": "Integration Name",
          "target_mode": "Target Mode",
          "queue_mode": "Queue Mode",
          "queue_timeout_minutes": "Queue Timeout (minutes, 0 = disabled)",
          "fallback_mode": "Timeout Fallback",
          "fallback_service": "Fallback Notify Service"
        },
        "data_description": {
          "fallback_service": "Required only when Timeout Fallback is set to notify_fallback. Example: notify.telegram"
        }
      },
      "persons": {
        "title": "Person — Notify Mapping",
        "description": "Select one or more notify services for each person. The first selected service is the primary device.",
        "data": {
          "admin_person": "Admin Person"
        },
        "data_description": {
          "admin_person": "Required only in single_admin mode. This person receives all notifications when home."
        }
      }
    },
    "error": {
      "invalid_timeout": "Timeout must be 0 or greater.",
      "fallback_service_required": "A fallback service is required when Timeout Fallback is set to notify_fallback.",
      "no_persons": "At least one person with a notify service must be configured.",
      "admin_required": "Exactly one admin must be selected when Target Mode is single_admin."
    },
    "abort": {
      "already_configured": "Smart Presence Notify is already configured."
    }
  },
  "options": {
    "step": {
      "user": {
        "title": "Update Global Settings",
        "data": {
          "name": "Integration Name",
          "target_mode": "Target Mode",
          "queue_mode": "Queue Mode",
          "queue_timeout_minutes": "Queue Timeout (minutes, 0 = disabled)",
          "fallback_mode": "Timeout Fallback",
          "fallback_service": "Fallback Notify Service"
        }
      },
      "persons": {
        "title": "Update Person — Notify Mapping",
        "data": {
          "admin_person": "Admin Person"
        }
      }
    },
    "error": {
      "invalid_timeout": "Timeout must be 0 or greater.",
      "fallback_service_required": "A fallback service is required when Timeout Fallback is set to notify_fallback.",
      "no_persons": "At least one person with a notify service must be configured.",
      "admin_required": "Exactly one admin must be selected when Target Mode is single_admin."
    }
  }
}
```

- [ ] **Step 2: Create translations/it.json**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Impostazioni Globali",
        "data": {
          "name": "Nome Integrazione",
          "target_mode": "Modalità Destinatario",
          "queue_mode": "Modalità Coda",
          "queue_timeout_minutes": "Timeout Coda (minuti, 0 = disabilitato)",
          "fallback_mode": "Fallback Timeout",
          "fallback_service": "Servizio Notify Fallback"
        },
        "data_description": {
          "fallback_service": "Richiesto solo se il Fallback Timeout è impostato su notify_fallback. Esempio: notify.telegram"
        }
      },
      "persons": {
        "title": "Mappatura Persona — Notify",
        "description": "Seleziona uno o più servizi notify per ogni persona. Il primo è il dispositivo principale.",
        "data": {
          "admin_person": "Persona Admin"
        },
        "data_description": {
          "admin_person": "Richiesto solo in modalità single_admin. Questa persona riceve tutte le notifiche quando è a casa."
        }
      }
    },
    "error": {
      "invalid_timeout": "Il timeout deve essere 0 o maggiore.",
      "fallback_service_required": "Un servizio fallback è richiesto quando il Fallback Timeout è notify_fallback.",
      "no_persons": "Almeno una persona con un servizio notify deve essere configurata.",
      "admin_required": "Deve essere selezionato esattamente un admin in modalità single_admin."
    },
    "abort": {
      "already_configured": "Smart Presence Notify è già configurato."
    }
  },
  "options": {
    "step": {
      "user": {
        "title": "Aggiorna Impostazioni Globali",
        "data": {
          "name": "Nome Integrazione",
          "target_mode": "Modalità Destinatario",
          "queue_mode": "Modalità Coda",
          "queue_timeout_minutes": "Timeout Coda (minuti, 0 = disabilitato)",
          "fallback_mode": "Fallback Timeout",
          "fallback_service": "Servizio Notify Fallback"
        }
      },
      "persons": {
        "title": "Aggiorna Mappatura Persona — Notify",
        "data": {
          "admin_person": "Persona Admin"
        }
      }
    },
    "error": {
      "invalid_timeout": "Il timeout deve essere 0 o maggiore.",
      "fallback_service_required": "Un servizio fallback è richiesto quando il Fallback Timeout è notify_fallback.",
      "no_persons": "Almeno una persona con un servizio notify deve essere configurata.",
      "admin_required": "Deve essere selezionato esattamente un admin in modalità single_admin."
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/smart_presence_notify/translations/
git commit -m "Add English and Italian translations"
```

---

## Task 15: CI — GitHub Actions

**Files:**
- Create: `.github/workflows/tests.yml`

- [ ] **Step 1: Create tests.yml**

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        ha-version:
          - "2026.1.0"
          - "2026.3.0"
          - "2026.4.0"

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install homeassistant==${{ matrix.ha-version }}
          pip install -r requirements_test.txt

      - name: Run tests
        run: pytest tests/ -v --tb=short
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/tests.yml
git commit -m "Add GitHub Actions CI for tests on HA 2026.1, 2026.3, 2026.4"
git push origin main
```

- [ ] **Step 3: Verify CI passes on GitHub**

Open `https://github.com/portbusy/smart-presence-notify/actions` and confirm all 3 matrix jobs pass.

---

## Self-Review Checklist

Spec sections covered:

| Spec section | Task(s) |
|---|---|
| Config flow step 1 (global settings) | Task 4 |
| Config flow step 2 (person mapping) | Task 4 |
| Validation (no persons, admin required) | Task 5 |
| Options flow | Task 4 |
| Store persistence | Task 3 |
| Coordinator presence detection | Task 6 |
| Send flow — target_override | Task 7 |
| Send flow — high priority | Task 7 |
| Send flow — broadcast | Task 7 |
| Send flow — single_admin | Task 7 |
| Send flow — caller_decides | Task 7 |
| Send flow — enqueue | Task 7 |
| Queue drain — fifo | Task 8 |
| Queue drain — last_only | Task 8 |
| Queue drain — summary | Task 8 |
| Timeout — discard | Task 9 |
| Timeout — fallback | Task 9 |
| Persistence across restart | Task 9 |
| Entry setup/unload | Task 10 |
| sensor.queue_count | Task 11 |
| sensor.last_sent | Task 11 |
| binary_sensor.someone_home | Task 12 |
| Service schema + handler | Task 13 |
| Translations (en + it) | Task 14 |
| CI matrix | Task 15 |
