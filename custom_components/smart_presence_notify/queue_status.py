"""Explain queued work without exposing it as a device receipt confirmation."""

from datetime import datetime

from .const import MAX_DELIVERY_ATTEMPTS, Priority
from .models import CoordinatorData, PendingNotification

_REASONS = {
    "en": {
        "paused": "Notifications temporarily paused; waiting for resume or paused_until.",
        "quiet_hours": "Waiting for the end of configured quiet hours.",
        "expiry_pending": "Expired; awaiting discard or fallback handling.",
        "retries_exhausted": "Automatic attempts exhausted; repair the destination and retry manually.",
        "waiting_for_presence": "Waiting for someone to return home.",
        "retry_scheduled": "A delivery failed; the next attempt is scheduled at retry_at.",
        "pending": "Pending delivery or currently being processed.",
    },
    "it": {
        "paused": "Notifiche in pausa temporanea; in attesa della ripresa o di paused_until.",
        "quiet_hours": "In attesa della fine della fascia silenziosa configurata.",
        "expiry_pending": "Scaduta; in attesa di eliminazione o inoltro al destinatario alternativo.",
        "retries_exhausted": "Tentativi automatici esauriti; ripristina il destinatario e riprova manualmente.",
        "waiting_for_presence": "In attesa che qualcuno rientri a casa.",
        "retry_scheduled": "Un invio è fallito; il prossimo tentativo è programmato per retry_at.",
        "pending": "In attesa di invio o attualmente in elaborazione.",
    },
}


def queue_reason(item: PendingNotification, data: CoordinatorData, now: datetime) -> str:
    if not item.expired and item.expires_at and item.expires_at <= now:
        return "expiry_pending"
    if item.attempts >= MAX_DELIVERY_ATTEMPTS:
        return "retries_exhausted"
    if data.silence_reason and not (
        item.priority == Priority.HIGH and data.high_priority_bypasses_silence
    ):
        return data.silence_reason
    if item.requires_presence and not data.someone_home:
        return "waiting_for_presence"
    if item.retry_at and item.retry_at > now:
        return "retry_scheduled"
    return "pending"


def explain_queue_item(item, data, now, language):
    reason = queue_reason(item, data, now)
    return {
        "reason": reason,
        "explanation": _REASONS.get(language, _REASONS["en"])[reason],
        "requires_presence": item.requires_presence,
        "fallback_delivery": item.expired,
    }
