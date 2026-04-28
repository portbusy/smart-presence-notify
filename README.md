# Smart Presence Notify

Home Assistant custom integration that routes notifications based on who is home.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/portbusy/smart-presence-notify)](https://github.com/portbusy/smart-presence-notify/releases)
[![Tests](https://github.com/portbusy/smart-presence-notify/actions/workflows/tests.yml/badge.svg)](https://github.com/portbusy/smart-presence-notify/actions/workflows/tests.yml)

## Features

- Sends notifications to all present household members (or a single admin, or caller-defined target)
- Queues notifications when nobody is home and delivers them to the first person who returns
- Configurable queue modes: last-only, FIFO, or summary
- Priority support: high-priority notifications bypass the queue and control device sound/interruption
- Notification timeout with optional fallback service
- Multi-device support per person
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

## Exposed Entities

| Entity | Description |
|--------|-------------|
| `sensor.smart_presence_notify_queue_count` | Number of pending notifications |
| `sensor.smart_presence_notify_last_sent` | Title of the last sent notification |
| `binary_sensor.smart_presence_notify_someone_home` | Whether anyone is currently home |

## License

MIT
