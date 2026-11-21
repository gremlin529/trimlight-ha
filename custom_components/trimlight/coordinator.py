"""Polls one Trimlight controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LIBRARY_INTERVAL, POLL_INTERVAL
from .protocol import Detail, DeviceInfo, Pattern, Schedule, Trimlight, TrimlightError, scheduled_pattern

_LOGGER = logging.getLogger(__name__)


@dataclass
class TrimlightData:
    info: DeviceInfo
    detail: Detail
    patterns: list[Pattern] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)

    def pattern(self, pattern_id: int | None) -> Pattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)

    def scheduled(self, now: datetime) -> Pattern | None:
        """The pattern the controller's schedules show now (in timer mode)."""
        return self.pattern(scheduled_pattern(now, self.detail, self.schedules))


class TrimlightCoordinator(DataUpdateCoordinator[TrimlightData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Trimlight) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=POLL_INTERVAL)
        self.client = client
        self._library_at: datetime | None = None

    async def _async_update_data(self) -> TrimlightData:
        try:
            # Check Device also keeps the controller's clock right, which
            # its schedules depend on.
            info = await self.client.device_info(dt_util.now().replace(tzinfo=None))
            detail = await self.client.detail()
            old = self.data
            now = dt_util.utcnow()
            stale = (
                old is None
                or self._library_at is None
                or now - self._library_at > LIBRARY_INTERVAL
                or old.detail.pattern_ids != detail.pattern_ids
                or old.detail.schedule_ids != detail.schedule_ids
            )
            if stale:
                patterns = await self.client.patterns(detail.pattern_ids)
                schedules = await self.client.schedules(detail.schedule_ids)
                self._library_at = now
            else:
                patterns, schedules = old.patterns, old.schedules
        except TrimlightError as err:
            raise UpdateFailed(str(err)) from err
        return TrimlightData(info, detail, patterns, schedules)

    def set_mode_locally(self, mode: int) -> None:
        """After a command: show the new mode without waiting for a poll."""
        if self.data and self.data.info.mode != mode:
            self.data.info.mode = mode
            self.async_update_listeners()
