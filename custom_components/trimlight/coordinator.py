"""Polls one Trimlight controller, and edits its saved patterns."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LIBRARY_INTERVAL, MAX_MISSED_POLLS, POLL_INTERVAL
from .protocol import (
    CATEGORY_CUSTOM,
    CATEGORY_PRESET,
    EFFECTS,
    NAME_LENGTH,
    Detail,
    DeviceInfo,
    Pattern,
    Schedule,
    Trimlight,
    TrimlightError,
    scheduled_pattern,
)

_LOGGER = logging.getLogger(__name__)

Rgb = tuple[int, int, int]


def percent_to_byte(pct: float) -> int:
    return max(0, min(255, round(pct * 255 / 100)))


def byte_to_percent(value: int) -> int:
    return round(value * 100 / 255)


@dataclass
class PatternEdit:
    """Pattern settings from a service call; None leaves a setting as it is
    (or uses the default for a new pattern). Speed and brightness are 0-100."""

    effect: str | None = None
    speed: float | None = None
    brightness: float | None = None
    colors: list[Rgb] | None = None
    counts: list[int] | None = None


@dataclass
class TrimlightData:
    info: DeviceInfo
    detail: Detail
    patterns: list[Pattern] = field(default_factory=list)
    schedules: list[Schedule] = field(default_factory=list)

    def pattern(self, pattern_id: int | None) -> Pattern | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)

    def find(self, name: str) -> Pattern | None:
        """A saved pattern by name, ignoring case and outer spaces."""
        key = name.strip().lower()
        return next((p for p in self.patterns if p.name.strip().lower() == key), None)

    def scheduled(self, now: datetime) -> Pattern | None:
        """The pattern the controller's schedules show now (in timer mode)."""
        return self.pattern(scheduled_pattern(now, self.detail, self.schedules))


def used_colors(p: Pattern) -> int:
    """How many of the 7 colour slots a custom pattern uses (count above 0)."""
    return sum(1 for c in p.dot_counts if c)


def edited(p: Pattern, edit: PatternEdit) -> Pattern:
    """p with an edit applied. Colours and counts line up slot by slot; slots
    past the last colour are cleared."""
    if p.category == CATEGORY_PRESET and (edit.effect is not None or edit.colors or edit.counts):
        raise ServiceValidationError(
            f"'{p.name}' is a built-in (colour wheel) pattern: only its name, speed and brightness can change"
        )
    colors = [tuple(p.dot_colors[i * 3:i * 3 + 3]) for i in range(7)]
    counts = list(p.dot_counts)
    used = used_colors(p)
    if edit.colors is not None:
        used = len(edit.colors)
        colors = list(edit.colors) + [(0, 0, 0)] * (7 - used)
        counts = [(counts[i] or 1) if i < used else 0 for i in range(7)]
    if edit.counts is not None:
        if len(edit.counts) > used:
            raise ServiceValidationError(f"{len(edit.counts)} dot counts given for {used} colours")
        counts[: len(edit.counts)] = edit.counts
    return replace(
        p,
        effect=EFFECTS.index(edit.effect) if edit.effect is not None else p.effect,
        speed=percent_to_byte(edit.speed) if edit.speed is not None else p.speed,
        brightness=percent_to_byte(edit.brightness) if edit.brightness is not None else p.brightness,
        dot_counts=bytes(counts),
        dot_colors=bytes(c for rgb in colors for c in rgb),
    )


def check_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ServiceValidationError("A pattern needs a name")
    if not name.isascii():
        raise ServiceValidationError(f"'{name}': the controller only takes plain (ASCII) letters in names")
    if len(name) > NAME_LENGTH:
        raise ServiceValidationError(f"'{name}' is longer than the controller's {NAME_LENGTH} characters")
    return name


class TrimlightCoordinator(DataUpdateCoordinator[TrimlightData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: Trimlight) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=POLL_INTERVAL)
        self.client = client
        self._library_at: datetime | None = None
        self._missed = 0

    async def _async_update_data(self) -> TrimlightData:
        try:
            data = await self._read()
        except TrimlightError as err:
            # While the Trimlight app is connected, the controller drops or
            # muddles other connections. Ride out a few polls on what we
            # last read rather than going unavailable.
            self._missed += 1
            if self.data is not None and self._missed <= MAX_MISSED_POLLS:
                _LOGGER.debug("Trimlight %s: poll failed (%s), keeping the last reading", self.client.host, err)
                return self.data
            raise UpdateFailed(str(err)) from err
        self._missed = 0
        return data

    async def _read(self) -> TrimlightData:
        # Check Device also keeps the controller's clock right, which its
        # schedules depend on.
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
        return TrimlightData(info, detail, patterns, schedules)

    def set_mode_locally(self, mode: int) -> None:
        """After a command: show the new mode without waiting for a poll."""
        if self.data and self.data.info.mode != mode:
            self.data.info.mode = mode
            self.async_update_listeners()

    # ------------------------------------------------------------- library

    def _need(self, name: str) -> Pattern:
        if (p := self.data.find(name)) is None:
            raise ServiceValidationError(f"{self.data.info.name} has no pattern called '{name}'")
        return p

    async def _write(self, call) -> None:
        try:
            await call
        except TrimlightError as err:
            raise HomeAssistantError(f"Couldn't reach {self.data.info.name}: {err}") from err
        # Read the library back straight away so Home Assistant shows it.
        await asyncio.sleep(1)
        self._library_at = None
        await self.async_refresh()

    async def save_pattern(self, name: str, edit: PatternEdit) -> Pattern:
        """Changes the pattern with this name, or creates it."""
        name = check_name(name)
        if (existing := self.data.find(name)) is not None:
            pattern = replace(edited(existing, edit), name=name)
            await self._write(self.client.update_pattern(pattern))
            return pattern
        if not edit.colors:
            raise ServiceValidationError(f"'{name}' is a new pattern: give it at least one colour")
        free = next((i for i in range(1, 256) if i not in self.data.detail.pattern_ids), None)
        if free is None:
            raise ServiceValidationError(f"{self.data.info.name} has no room for another pattern")
        blank = Pattern(free, name, CATEGORY_CUSTOM, 0, percent_to_byte(50), 255, bytes(7), bytes(21))
        pattern = edited(blank, edit)
        await self._write(self.client.create_pattern(pattern))
        return pattern

    async def copy_pattern(self, source: Pattern) -> None:
        """Saves a copy of another controller's pattern, over any pattern
        here with the same name."""
        if (existing := self.data.find(source.name)) is not None:
            await self._write(self.client.update_pattern(replace(source, id=existing.id)))
            return
        free = next((i for i in range(1, 256) if i not in self.data.detail.pattern_ids), None)
        if free is None:
            raise ServiceValidationError(f"{self.data.info.name} has no room for another pattern")
        await self._write(self.client.create_pattern(replace(source, id=free)))

    async def rename_pattern(self, name: str, new_name: str) -> None:
        pattern = self._need(name)
        new_name = check_name(new_name)
        clash = self.data.find(new_name)
        if clash is not None and clash.id != pattern.id:
            raise ServiceValidationError(f"{self.data.info.name} already has a pattern called '{new_name}'")
        await self._write(self.client.update_pattern(replace(pattern, name=new_name)))

    async def delete_pattern(self, name: str) -> None:
        await self._write(self.client.delete_pattern(self._need(name).id))

    async def preview_pattern(self, edit: PatternEdit) -> None:
        blank = Pattern(0, "", CATEGORY_CUSTOM, 0, percent_to_byte(50), 255, bytes(7), bytes(21))
        try:
            await self.client.preview(edited(blank, edit))
        except TrimlightError as err:
            raise HomeAssistantError(f"Couldn't reach {self.data.info.name}: {err}") from err
