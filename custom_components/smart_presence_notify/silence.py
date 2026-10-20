"""Local daily quiet hours and a persisted, UTC temporary pause."""

from datetime import datetime

from homeassistant.util import dt as dt_util


def silence_reason(settings: dict, now: datetime) -> str | None:
    until = settings.get("paused_until")
    if until:
        parsed = dt_util.parse_datetime(until)
        if parsed and parsed.tzinfo and parsed > now:
            return "paused"
    if settings.get("quiet_hours_enabled", False):
        start = dt_util.parse_time(settings.get("quiet_hours_start", "22:00:00"))
        end = dt_util.parse_time(settings.get("quiet_hours_end", "08:00:00"))
        local = dt_util.as_local(now).time().replace(tzinfo=None)
        if start and end and start != end:
            active = start <= local < end if start < end else local >= start or local < end
            if active:
                return "quiet_hours"
    return None
