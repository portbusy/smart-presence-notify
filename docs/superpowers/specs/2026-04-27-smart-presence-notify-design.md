# Smart Presence Notify — Design Spec

**Date:** 2026-04-27
**HA minimum version:** 2026.1.0 (current stable: 2026.4.4)
**HACS:** content_type integration, public repo

---

## 1. Overview

Custom Home Assistant integration that routes mobile notifications based on household presence:

- Sends to all present members (or configured target) when someone is home
- Queues notifications when nobody is home
- Delivers queued notifications to the first person who returns
- Priority system that bypasses queue and controls device sound/interruption
- 100% UI configuration — no YAML required from the user

---

## 2. Architecture

### 2.1 File Structure

```
custom_components/smart_presence_notify/
├── __init__.py              # async_setup_entry, async_unload_entry
├── config_flow.py           # ConfigFlow + OptionsFlow
├── coordinator.py           # SmartPresenceNotifyCoordinator
├── sensor.py                # SensorEntity (queue_count, last_sent)
├── binary_sensor.py         # BinarySensorEntity (someone_home)
├── services.py              # Service registration + handler
├── const.py                 # Domain, keys, enums
├── manifest.json
├── strings.json
└── translations/
    ├── en.json
    └── it.json
```

### 2.2 Key HA 2026 Patterns

- `ConfigEntry[SNPRuntimeData]` — typed generic entry, no `hass.data`
- `entry.runtime_data` for coordinator and store
- All state updates via push (`state_changed` event listener), no polling
- Services registered via `hass.services.async_register`
- `EntityDescription` dataclasses for all entities
- Brand images in `brand/` folder (HA 2026.3+)

### 2.3 Runtime Data

```python
@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator

type SNPConfigEntry = ConfigEntry[SNPRuntimeData]
```

---

## 3. Config Flow

### 3.1 Step 1 — Global Settings

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | "Smart Presence Notify" | Instance name |
| `target_mode` | select | `broadcast` | `broadcast` / `single_admin` / `caller_decides` |
| `queue_mode` | select | `fifo` | `last_only` / `fifo` / `summary` |
| `queue_timeout_minutes` | int | `0` | 0 = disabled |
| `fallback_mode` | select | `discard` | `discard` / `notify_fallback` |
| `fallback_service` | string | `""` | Visible only if fallback_mode = notify_fallback |

### 3.2 Step 2 — Person Mapping (repeatable)

For each `person.*` entity found in HA:
- Person selector (dropdown from available `person.*`)
- One or more `notify.*` services (ordered list — first = primary device)
- `is_admin` boolean flag (required if `target_mode = single_admin`)

**Validation:**
- At least one person configured
- Every person has at least one notify service
- Exactly one admin if `target_mode = single_admin`

### 3.3 Options Flow

Identical to config flow, accessible from the integration's Configure button.

---

## 4. Coordinator

### 4.1 Data Model

```python
@dataclass
class PendingNotification:
    id: str                       # uuid4
    title: str
    message: str
    priority: Literal["normal", "high"]
    created_at: datetime
    expires_at: datetime | None
    extra_data: dict              # passed through to notify service

@dataclass
class NotificationRecord:
    title: str
    sent_at: datetime
    recipients: list[str]         # notify service names used
    priority: Literal["normal", "high"]

@dataclass
class CoordinatorData:
    queue: list[PendingNotification]
    last_sent: NotificationRecord | None
    someone_home: bool
    home_persons: list[str]       # person entity_ids currently home
```

### 4.2 Initialization

On `async_setup_entry`:
1. Load persisted queue from `Store`
2. Register `state_changed` listener on all `person.*` entities
3. Schedule timeout checks for any already-queued notifications with `expires_at`

### 4.3 Send Flow (`async_send_notification`)

```
receive(title, message, priority, target_override, extra_data)
│
├─ target_override set?
│   └─ YES → call target_override service directly, record last_sent, return
│
├─ priority == "high"?
│   └─ YES → someone home?
│           ├─ YES → send to first home person, record last_sent, return
│           └─ NO  → fallback_mode == notify_fallback?
│                   ├─ YES → send to fallback_service, record last_sent, return
│                   └─ NO  → enqueue with priority=high (drained first on return), return
│
├─ someone home?
│   ├─ target_mode == broadcast   → send to all home persons (all devices)
│   ├─ target_mode == single_admin → send to admin if home, else first home person
│   └─ target_mode == caller_decides → send to caller-provided list
│
└─ nobody home?
    └─ enqueue notification, persist to Store, schedule timeout if expires_at set
```

### 4.4 Queue Drain (on person → home)

```
person X arrives home
│
├─ queue empty? → nothing to do
│
├─ queue_mode == last_only
│   └─ send last item to person X, discard rest
│
├─ queue_mode == fifo
│   └─ send all items in order to person X (1s delay between each)
│
└─ queue_mode == summary
    └─ aggregate all titles into one message, send single notification to person X
        format: "N messages while you were away: [title1], [title2], ..."

After drain: clear queue, persist, update coordinator state.
```

### 4.5 Timeout Handling

- On enqueue: if `queue_timeout_minutes > 0`, compute `expires_at = now + timeout`
- Use `async_track_point_in_time` per notification
- On expiry callback:
  - If `fallback_mode == discard`: remove from queue silently
  - If `fallback_mode == notify_fallback`: send to `fallback_service`, then remove
- Persist updated queue to Store

### 4.6 Persistence

- Store key: `smart_presence_notify` (version 1)
- Serialized: list of `PendingNotification` as dicts (datetime as ISO strings)
- Loaded on setup, saved on every queue mutation
- Survives HA restarts

---

## 5. Entities

All entities belong to a single virtual `DeviceEntry` named after the integration instance.

### 5.1 Sensors

| Key | Entity ID | State | State class | Attributes |
|---|---|---|---|---|
| `queue_count` | `sensor.snp_queue_count` | `int` (0..N) | `measurement` | `queue`: list of `{id, title, priority, expires_at}` |
| `last_sent` | `sensor.snp_last_sent` | notification title (str) | — | `sent_at`, `recipients`, `priority` |

`last_sent` state is `unknown` until first notification is sent.

### 5.2 Binary Sensors

| Key | Entity ID | State | Device class | Attributes |
|---|---|---|---|---|
| `someone_home` | `binary_sensor.snp_someone_home` | `on`/`off` | `presence` | `home_persons`: list of person entity_ids |

### 5.3 Entity Pattern

```python
@dataclass(frozen=True, kw_only=True)
class SNPSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], StateType]
    extra_fn: Callable[[CoordinatorData], dict] | None = None
```

---

## 6. Service

### 6.1 Schema

```yaml
service: smart_presence_notify.send
fields:
  title:
    required: true
    selector:
      text:
  message:
    required: true
    selector:
      text:
  priority:
    required: false
    default: normal
    selector:
      select:
        options: [normal, high]
  target_override:
    required: false
    selector:
      text:          # single notify service, bypasses all presence logic
  targets:
    required: false
    selector:
      object:        # list of notify service names, used when target_mode = caller_decides
                     # e.g. [notify.mobile_app_mario, notify.mobile_app_lucia]
  data:
    required: false
    selector:
      object:        # passed through verbatim to the notify service
```

### 6.2 Handler

Validated with `voluptuous` + `homeassistant.helpers.config_validation`. Calls `coordinator.async_send_notification()`.

---

## 7. Testing

**Framework:** `pytest-homeassistant-custom-component`

| Area | Tests |
|---|---|
| Config flow | Full setup, validation errors, options flow roundtrip |
| Coordinator — send | Normal/high priority, target modes, target_override |
| Coordinator — queue | Enqueue, drain (all 3 modes), FIFO order, summary format |
| Coordinator — timeout | Discard on expiry, fallback service called on expiry |
| Coordinator — persistence | Queue survives simulated restart (reload entry) |
| Entities | State and attributes after each coordinator update |
| Service | Schema validation, call reaches coordinator |

**Tooling:**
- `freezegun` for timeout tests
- Mock `hass.services.async_call` to assert notify service calls
- Simulate `person.*` state changes via `hass.states.async_set`

**CI:** GitHub Actions, matrix on HA 2026.1, 2026.3, 2026.4.

---

## 8. Non-Goals (v0.1)

- Custom Lovelace card
- Multi-instance support (one config entry per HA instance)
- Notification scheduling / recurring reminders
- Read receipts / delivery confirmation
