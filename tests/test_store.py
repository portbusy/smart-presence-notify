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
