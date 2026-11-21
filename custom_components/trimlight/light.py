"""The controller's lights: on/off, saved patterns as effects, brightness and
solid colour, plus off timers.

The controller never reports what it's showing. In manual mode the state is
what Home Assistant last sent; in timer mode it's worked out from the
controller's own schedules."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import TrimlightConfigEntry
from .const import (
    ATTR_MINUTES,
    ATTR_OFF_AT,
    ATTR_TIME,
    DOMAIN,
    SERVICE_CANCEL_OFF_TIMER,
    SERVICE_TURN_OFF_AT,
    SERVICE_TURN_OFF_IN,
)
from .coordinator import TrimlightCoordinator
from .protocol import MODE_MANUAL, MODE_TIMER, Pattern

ATTR_SCHEDULE = "running_schedule"


async def async_setup_entry(
    hass: HomeAssistant, entry: TrimlightConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TrimlightLight(entry.runtime_data, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_TURN_OFF_IN,
        {vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))},
        "async_turn_off_in",
    )
    platform.async_register_entity_service(SERVICE_TURN_OFF_AT, {vol.Required(ATTR_TIME): cv.time}, "async_turn_off_at")
    platform.async_register_entity_service(SERVICE_CANCEL_OFF_TIMER, None, "async_cancel_off_timer")


def device_info(coordinator: TrimlightCoordinator, entry: TrimlightConfigEntry) -> DeviceInfo:
    info = coordinator.data.info
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name=info.name,
        manufacturer="Trimlight",
        model=f"{info.pixels} pixels",
        configuration_url=None,
    )


class TrimlightLight(CoordinatorEntity[TrimlightCoordinator], LightEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, coordinator: TrimlightCoordinator, entry: TrimlightConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_light"
        self._attr_device_info = device_info(coordinator, entry)
        # What we last sent, for manual mode.
        self._on = False
        self._effect: str | None = None
        self._brightness = 255
        self._rgb: tuple[int, int, int] = (255, 255, 255)
        self._off_at: datetime | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------- patterns

    def _names(self) -> dict[str, Pattern]:
        """Effect name -> pattern; repeated names get a number."""
        out: dict[str, Pattern] = {}
        for p in self.coordinator.data.patterns:
            name, n = p.name or f"Pattern {p.id}", 2
            while name in out:
                name, n = f"{p.name} ({n})", n + 1
            out[name] = p
        return out

    def _name_of(self, pattern: Pattern | None) -> str | None:
        if pattern is None:
            return None
        return next((n for n, p in self._names().items() if p.id == pattern.id), pattern.name)

    def _timer_mode(self) -> bool:
        return self.coordinator.data.info.mode == MODE_TIMER

    def _scheduled(self) -> Pattern | None:
        return self.coordinator.data.scheduled(dt_util.now().replace(tzinfo=None))

    # ---------------------------------------------------------------- state

    @property
    def effect_list(self) -> list[str]:
        return list(self._names())

    @property
    def is_on(self) -> bool:
        if self._timer_mode():
            return self._scheduled() is not None
        return self._on

    @property
    def effect(self) -> str | None:
        if self._timer_mode():
            return self._name_of(self._scheduled())
        return self._effect

    @property
    def brightness(self) -> int:
        if self._timer_mode():
            p = self._scheduled()
            return p.brightness if p else self._brightness
        return self._brightness

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        return self._rgb

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_SCHEDULE: self._timer_mode(),
            ATTR_OFF_AT: self._off_at.isoformat() if self._off_at else None,
        }

    # ------------------------------------------------------------- commands

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self.coordinator.client
        names = self._names()
        brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] in names:
            pattern = names[kwargs[ATTR_EFFECT]]
            # Keep the pattern's own brightness unless one was asked for.
            if ATTR_BRIGHTNESS not in kwargs:
                brightness = pattern.brightness
            await client.play_pattern(pattern, brightness)
            self._effect = kwargs[ATTR_EFFECT]
        elif ATTR_RGB_COLOR in kwargs:
            self._rgb = tuple(kwargs[ATTR_RGB_COLOR])
            self._effect = None
            await client.solid_color(*self._scaled(self._rgb, brightness))
        elif self._effect in names:
            # Brightness alone, or plain on: the current (or last) pattern.
            pattern = names[self._effect]
            if ATTR_BRIGHTNESS in kwargs:
                await client.set_brightness(pattern, brightness)
            else:
                await client.play_pattern(pattern, brightness)
        elif self._effect is None and self._on:
            await client.solid_color(*self._scaled(self._rgb, brightness))
        else:
            # Nothing picked yet: whatever the schedule would show, else the
            # first pattern.
            pattern = self._scheduled() or next(iter(names.values()), None)
            if pattern is None:
                await client.solid_color(*self._scaled(self._rgb, brightness))
            else:
                await client.play_pattern(pattern, brightness)
                self._effect = self._name_of(pattern)
        self._brightness = brightness
        self._on = True
        self.coordinator.set_mode_locally(MODE_MANUAL)
        self.async_write_ha_state()

    @staticmethod
    def _scaled(rgb: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
        return tuple(round(c * brightness / 255) for c in rgb)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.turn_off()
        self._on = False
        self._clear_timer()
        self.coordinator.set_mode_locally(MODE_MANUAL)
        self.async_write_ha_state()

    # --------------------------------------------------------------- timers

    async def async_turn_off_in(self, minutes: int) -> None:
        self._set_timer(dt_util.now() + timedelta(minutes=minutes))

    async def async_turn_off_at(self, time) -> None:
        now = dt_util.now()
        at = now.replace(hour=time.hour, minute=time.minute, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        self._set_timer(at)

    async def async_cancel_off_timer(self) -> None:
        self._clear_timer()
        self.async_write_ha_state()

    def _set_timer(self, at: datetime) -> None:
        self._clear_timer()
        self._off_at = at
        self._unsub_timer = async_track_point_in_time(self.hass, self._timer_fired, at)
        self.async_write_ha_state()

    def _clear_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer = None
        self._off_at = None

    @callback
    def _timer_fired(self, _now: datetime) -> None:
        self._unsub_timer = None
        self.hass.async_create_task(self.async_turn_off())

    # ---------------------------------------------------------- persistence

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        self._on = last.state == "on"
        self._effect = last.attributes.get(ATTR_EFFECT)
        self._brightness = last.attributes.get(ATTR_BRIGHTNESS) or self._brightness
        if rgb := last.attributes.get(ATTR_RGB_COLOR):
            self._rgb = tuple(rgb)
        # A timer outlives a restart; one that came due meanwhile fires now.
        if (off_at := last.attributes.get(ATTR_OFF_AT)) and (at := dt_util.parse_datetime(off_at)):
            if at <= dt_util.now():
                self.hass.async_create_task(self.async_turn_off())
            else:
                self._set_timer(at)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()
