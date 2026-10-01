# Smart Presence Notify

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/smart_presence_notify/brand/dark_logo@2x.png">
  <img alt="Smart Presence Notify" src="custom_components/smart_presence_notify/brand/logo@2x.png" width="360">
</picture>

Home Assistant custom integration that routes notifications based on who is home.

The integration includes light/dark brand images and high-resolution variants.
Home Assistant 2026.3 or newer displays these bundled images automatically.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/portbusy/smart-presence-notify)](https://github.com/portbusy/smart-presence-notify/releases)
[![Tests](https://github.com/portbusy/smart-presence-notify/actions/workflows/tests.yml/badge.svg)](https://github.com/portbusy/smart-presence-notify/actions/workflows/tests.yml)

## Features

- Sends notifications to all present household members (or a single admin, or caller-defined target)
- Queues notifications when nobody is home and delivers them to the first person who returns
- Configurable queue modes: last-only, FIFO, or summary
- High priority delivers immediately to the first person home, or the fallback when away; without a fallback it waits for presence
- Mobile forwarding of selected Home Assistant bell notifications, including Dreame
- Per-destination delivery checkpoints and bounded retries
- Notification timeout with optional fallback service
- Multi-device support per person
- Optional actionable Yes/No notifications for Home Assistant Companion App devices
- 100% UI configuration — no YAML required

## Installation

### HACS (recommended)

[![Add to Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=portbusy&repository=smart-presence-notify&category=integration)

Or manually via HACS:

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom repositories**
3. Add `https://github.com/portbusy/smart-presence-notify` with category `Integration`
4. Search for "Smart Presence Notify" and install
5. Restart Home Assistant

### Manual

Copy `custom_components/smart_presence_notify/` into your HA `custom_components/` folder and restart.

## Setup

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=smart_presence_notify)

Or go to **Settings → Devices & Services → Add Integration** and search for "Smart Presence Notify".

## Usage

```yaml
service: smart_presence_notify.send
data:
  title: "Garage door"
  message: "Left open for 10 minutes"
  priority: normal  # or: high
```

### Standard central notify entity

Each configuration exposes a notify entity that applies its presence, recipient and queue rules. Use its actual entity ID from Home Assistant:

```yaml
action: notify.send_message
target:
  entity_id: notify.smart_presence_notify
data:
  title: "Laundry"
  message: "The cycle is complete"
```

This standard action accepts only title/message and requires configured recipients (broadcast or single-admin mode). Caller-defined mode requires the `smart_presence_notify.send` action with `targets`. A missing title defaults to the configuration name. The entity's timestamp records acceptance by the router, including queueing; the delivery-status sensor records downstream attempts.

### Automatic channel selection and Live Activities

For an unambiguously linked Companion registration, the router uses the modern notify entity for plain title/message notifications, even when the saved destination is its legacy service. Extra `data`, Yes/No buttons or high priority select the Companion service instead. Selecting both aliases sends once per delivery attempt. If a required advanced channel is unavailable, the message remains queued with a readable delivery error and can be retried after restoring the service. Advanced data is never silently discarded for modern notify entities. Ambiguous registrations are not linked, and other providers retain their configured channel.

Live Activities are explicit: include `live_update: true` and a stable `tag` (1–64 letters, digits, hyphens or underscores). The router passes the payload to Companion; it does not infer activity state from message text or automatically monitor a vacuum. For immediate live updates, use `target_override` to bypass presence:

```yaml
action: smart_presence_notify.send
data:
  title: "Dreame"
  message: "Cleaning · 40%"
  target_override: notify.my_phone
  data:
    live_update: true
    tag: dreame_cleaning
    progress: 40
    progress_max: 100
```

Replace `notify.my_phone` with your registered Companion notify entity or its legacy service. Reuse the tag when updating; end the activity by sending `message: clear_notification` and `data: {tag: dreame_cleaning}` through the same router action. Device support and Companion settings still determine whether the activity appears. See the [Companion Live Activities documentation](https://companion.home-assistant.io/docs/notifications/live-activities/).

### Optional Yes/No responses

Add a Yes/No preset to a notification sent to a `notify.mobile_app_*` service:

```yaml
action: smart_presence_notify.send
data:
  title: "Garage door"
  message: "Do you want to close it?"
  response_preset: yes_no
  response_id: close_garage
```

The first button pressed fires a `smart_presence_notify_response` event:

```yaml
event_type: smart_presence_notify_response
event_data:
  response_id: close_garage
  response: yes  # or: no
```

This feature is opt-in. It is supported by Home Assistant Companion App notify
services; preset buttons are omitted for other notification providers. Button
labels follow the Home Assistant language for English, Italian, Spanish, French,
and German, with English as the fallback. A response is not guaranteed, so
automations should still define a timeout. When
a question is broadcast to multiple people, only the first response received
during the current Home Assistant runtime is emitted. Restarting Home Assistant
discards tokens for fully delivered questions, so their old buttons no longer emit responses. Questions still queued restore their tokens and can become answerable again after a mobile delivery succeeds. Replies are accepted only for issued, delivered questions, for 24 hours. Up to 4096 outstanding response tokens are retained; new questions are rejected at that limit rather than evicting duplicate protection.
Queued actionable notifications retain their buttons; summary queue mode falls
back to FIFO so individual questions are not collapsed into a summary.

## Forward Home Assistant bell notifications

Open the integration's **Configure → Forward bell notifications** page. Select one or more phones by their display names and enable forwarding. Companion notify entities and legacy services from the same unambiguous app registration appear as one choice, including after entity renaming. Delivery automatically prefers an available `notify.mobile_app_*` service to retain replacement tags; if it is absent, the registered notify entity uses `notify.send_message`. Existing saved entity/service aliases for a phone are deduplicated before forwarding. Separate or ambiguous registrations remain separate choices. Saved offline destinations remain selectable. Other notify providers are excluded from this mobile-only selector. A configuration switch also allows enabling/disabling it from dashboards and automations. Forwarding sends immediately, including while nobody is home.

The **Integrations and notifications to forward** field offers a multiple selection of verified sources that are configured in Home Assistant. The initial catalogue supports Dreame Vacuum (`dreame_vacuum_*`) and HomeKit Bridge pairing notifications (their config entry IDs). Matching uses these verified rules; arbitrary ID prefixes are never treated as proof of origin.

Other sources appear as **Observed notification: ID** after emitting a bell notification while this integration is loaded, even with forwarding disabled. Reopen the options page to refresh the choices. Observed IDs remain selectable after dismissal and across restarts; the catalogue stores at most 200 distinct IDs (up to 200 characters each), without titles or messages. New observations are saved with a 15-second delay and flushed on unload. Existing bell notifications are not scanned or replayed.

Select **All bell notifications** explicitly to forward everything. With no selected source and no advanced ID filter, nothing is forwarded. Additional manual ID patterns add sources to the selection; `*` matches any sequence of characters. An optional text filter checks the title and message, ignoring case, and must also match. Observed ID selections match that exact ID, even when it contains wildcard characters.

Existing configurations retain their forwarding behaviour: the Dreame wildcard becomes a named source when editing options, other manual filters are preserved, and legacy empty ID filters become an explicit All selection. Selected sources remain visible if an integration is subsequently removed or an observed ID falls out of the bounded catalogue.
Only new notifications and, optionally, changed notifications are forwarded. Existing bell entries are not replayed when enabling the switch. Identical updates and dismissals are ignored. For legacy `notify.mobile_app_*` services, changed notifications share a stable mobile `tag`, allowing the Companion App to replace an earlier notification. Modern notify entities use `notify.send_message`, which accepts only title/message: they cannot receive the replacement tag, buttons or other Companion App extra data, so changed notifications may appear as separate pushes. Turning the switch off stops new forwards; already queued deliveries retain their retry policy. Embedded base64 images are removed, and forwarded titles/messages are limited to 255/3000 UTF-8 bytes to fit mobile push payloads. Other markdown may render differently on a phone. A changed notification replaces an older pending forward with the same tag, so an old retry cannot overwrite the new content. Deduplication covers the most recent 500 IDs during the current HA runtime.

## Delivery and recovery

An accepted message is persisted before calling a provider. `last_sent` records destinations whose Home Assistant service call completed successfully; this does not confirm receipt on the device. Failed destinations remain queued and are retried after 30, 60, 120 and 240 seconds, for five attempts total. Successful destinations are not repeated during normal retry. The delivery-status sensor shows failures; `smart_presence_notify.retry_pending` restarts the retry budget after you repair a provider. Queued messages also resume after restarting Home Assistant when someone is already home.

A process crash between external delivery and saving its checkpoint can cause a duplicate. This is an at-least-once delivery queue, not a device receipt protocol. Unloading cancels pending timers and active integration delivery tasks.

The queue holds 100 messages by default (configurable from 1 to 1000). A full queue rejects new messages explicitly. Last-only mode replaces unsent waiting messages with the same destinations, retaining failed/in-flight deliveries. The queue sensor previews at most 20 items, with a truncation indicator. Lowering the limit retains existing messages and blocks new messages until space is available.

In caller-defined mode, `targets` are required and are stored with the message when waiting for presence. An explicit `target_override` always bypasses presence. Expired messages are discarded or routed to the configured fallback; failed fallback sends also have retries. Expiry is checked again before delivery to avoid sending an already expired queued message on arrival.

Both legacy notify services and notify entities are supported. Notify entities use `notify.send_message` with their entity ID and accept title/message; Companion App extra data and buttons require `notify.mobile_app_*` services. Bare `notify.send_message`, this integration's actions, and any of its notify entities (including renamed ones) cannot be used as destinations, preventing routing loops.

High-priority mobile sends default to Android `priority: high`, `ttl: 0`, and iOS `push.interruption-level: time-sensitive` with default sound. Values supplied in `data` take precedence; device permissions and settings still determine the actual alert.

## Exposed Entities

| Entity | Description |
|--------|-------------|
| `notify.smart_presence_notify` | Standard central notification entry point (one per configuration) |
| `switch.smart_presence_notify_forward_bell_notifications` | Enable mobile forwarding (requires configured mobile destinations) |
| `sensor.smart_presence_notify_delivery_status` | Ready, retrying or failed, with provider error details |
| `sensor.smart_presence_notify_queue_count` | Number of pending notifications |
| `sensor.smart_presence_notify_last_sent` | Title of the last sent notification |
| `binary_sensor.smart_presence_notify_someone_home` | Whether anyone is currently home |

## License

MIT
