"""Config entry runtime types, separate from the coordinator's data models."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import SmartPresenceNotifyCoordinator


@dataclass
class SNPRuntimeData:
    coordinator: SmartPresenceNotifyCoordinator


type SNPConfigEntry = ConfigEntry[SNPRuntimeData]
