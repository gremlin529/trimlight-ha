"""Trimlight lights: one per controller, and one per group of controllers.

A controller's light: saved patterns as effects, brightness and solid colour.
Off hands the controller back to its own schedules (its only off), so the
light stays on while a schedule is showing. The controller never reports
what it's showing: in manual mode the state is what Home Assistant last
sent; in timer mode it's worked out from the controller's schedules.

A group's light drives its members' lights together; its effects are the
patterns every member has, matched by name ignoring case.

Both have off timers and the pattern editing actions."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import color as color_util
from homeassistant.util import dt as dt_util

from . import TrimlightConfigEntry
from .const import (
    ATTR_MINUTES,
    ATTR_OFF_AT,
    ATTR_TIME,
    DOMAIN,
    SERVICE_CANCEL_OFF_TIMER,
    SERVICE_COPY_PATTERN,
    SERVICE_DELETE_PATTERN,
    SERVICE_PREVIEW_PATTERN,
    SERVICE_RENAME_PATTERN,
    SERVICE_SAVE_PATTERN,
    SERVICE_SYNC_PATTERNS,
    SERVICE_TURN_OFF_AT,
    SERVICE_TURN_OFF_IN,
)
from .coordinator import PatternEdit, TrimlightCoordinator, byte_to_percent, used_colors
from .groups import (
    async_sync_patterns,
    coordinators_for_entity,
    is_group,
    light_unique_id,
    member_coordinators,
    member_entity_ids,
    patterns_out_of_sync,
)
from .protocol import CATEGORY_PRESET, EFFECTS, MODE_MANUAL, MODE_TIMER, Pattern

_LOGGER = logging.getLogger(__name__)

ATTR_SCHEDULE = "running_schedule"
ATTR_PATTERN = "pattern"
ATTR_MEMBERS = "members"


# ------------------------------------------------------------ action fields

def _color(value: Any) -> tuple[int, int, int]:
    """A colour as '#ff0078', 'ff0078', a name ('red') or [255, 0, 120]."""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return tuple(max(0, min(255, int(c))) for c in value)
        except (TypeError, ValueError):
            pass
    text = str(value).strip()
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
        return tuple(bytes.fromhex(text.lstrip("#")))
    try:
        return tuple(color_util.color_name_to_rgb(text.lower().replace(" ", "")))
    except ValueError:
        raise vol.Invalid(f"'{value}' isn't a colour (try a name like red, or #ff0078)") from None


def _colors(value: Any) -> list[tuple[int, int, int]]:
    # A lone [r, g, b] is one colour, not three.
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(isinstance(c, int) for c in value):
        value = [value]
    value = cv.ensure_list(value)
    if not 1 <= len(value) <= 7:
        raise vol.Invalid("give 1 to 7 colours")
    return [_color(v) for v in value]


PERCENT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
PATTERN_FIELDS = {
    vol.Optional("effect"): vol.In(EFFECTS),
    vol.Optional("speed"): PERCENT,
    vol.Optional("brightness"): PERCENT,
    vol.Optional("colors"): _colors,
    vol.Optional("counts"): vol.All(
        cv.ensure_list, vol.Length(min=1, max=7), [vol.All(vol.Coerce(int), vol.Range(min=1, max=255))]
    ),
}


def _edit(fields: dict[str, Any]) -> PatternEdit:
    return PatternEdit(
        effect=fields.get("effect"),
        speed=fields.get("speed"),
        brightness=fields.get("brightness"),
        colors=fields.get("colors"),
        counts=fields.get("counts"),
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: TrimlightConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if is_group(entry):
        async_add_entities([TrimlightGroupLight(hass, entry)])
    else:
        async_add_entities([TrimlightLight(entry.runtime_data, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_TURN_OFF_IN,
        {vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))},
        "async_turn_off_in",
    )
    platform.async_register_entity_service(SERVICE_TURN_OFF_AT, {vol.Required(ATTR_TIME): cv.time}, "async_turn_off_at")
    platform.async_register_entity_service(SERVICE_CANCEL_OFF_TIMER, None, "async_cancel_off_timer")
    platform.async_register_entity_service(
        SERVICE_SAVE_PATTERN, {vol.Required("name"): cv.string, **PATTERN_FIELDS}, "async_save_pattern"
    )
    platform.async_register_entity_service(
        SERVICE_RENAME_PATTERN,
        {vol.Required("pattern"): cv.string, vol.Required("new_name"): cv.string},
        "async_rename_pattern",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_PATTERN, {vol.Required("pattern"): cv.string}, "async_delete_pattern"
    )
    platform.async_register_entity_service(
        SERVICE_COPY_PATTERN,
        {vol.Required("source"): cv.entity_id, vol.Required("pattern"): cv.string},
        "async_copy_pattern",
    )
    platform.async_register_entity_service(
        SERVICE_PREVIEW_PATTERN, {**PATTERN_FIELDS, vol.Required("colors"): _colors}, "async_preview_pattern"
    )
    platform.async_register_entity_service(SERVICE_SYNC_PATTERNS, None, "async_sync_patterns")


# ------------------------------------------------------------------ shared

class _TrimlightBase(LightEntity, RestoreEntity):
    """Off timers and the pattern actions, over the controller(s) this
    light drives."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT

    _off_at: datetime | None = None
    _unsub_timer: CALLBACK_TYPE | None = None

    def _coordinators(self) -> list[TrimlightCoordinator]:
        raise NotImplementedError

    # -- off timers (off means back to the schedule)

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

    def _restore_timer(self, attributes) -> None:
        """A timer outlives a restart; one that came due meanwhile fires now."""
        if (off_at := attributes.get(ATTR_OFF_AT)) and (at := dt_util.parse_datetime(off_at)):
            if at <= dt_util.now():
                self.hass.async_create_task(self.async_turn_off())
            else:
                self._set_timer(at)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()

    # -- pattern actions, on every controller this light drives

    def _targets(self) -> list[TrimlightCoordinator]:
        coordinators = self._coordinators()
        if not coordinators:
            raise ServiceValidationError(f"{self.entity_id}: no controllers are reachable")
        return coordinators

    def _having(self, name: str) -> list[TrimlightCoordinator]:
        """The controllers that have a pattern by this name (a group's
        members needn't all have it)."""
        having = [c for c in self._targets() if c.data.find(name) is not None]
        if not having:
            raise ServiceValidationError(f"{self.entity_id} has no pattern called '{name}'")
        return having

    async def async_save_pattern(self, name: str, **fields: Any) -> None:
        edit = _edit(fields)
        # With colours it can create the pattern where it's missing; without,
        # it can only change the ones that exist.
        targets = self._targets() if edit.colors else self._having(name)
        await asyncio.gather(*(c.save_pattern(name, edit) for c in targets))

    async def async_rename_pattern(self, pattern: str, new_name: str) -> None:
        await asyncio.gather(*(c.rename_pattern(pattern, new_name) for c in self._having(pattern)))

    async def async_delete_pattern(self, pattern: str) -> None:
        await asyncio.gather(*(c.delete_pattern(pattern) for c in self._having(pattern)))

    async def async_copy_pattern(self, source: str, pattern: str) -> None:
        sources = coordinators_for_entity(self.hass, source)
        found = next((p for c in sources if (p := c.data.find(pattern)) is not None), None)
        if found is None:
            raise ServiceValidationError(f"{source} has no pattern called '{pattern}'")
        targets = [c for c in self._targets() if c not in sources or c.data.find(pattern) is None]
        await asyncio.gather(*(c.copy_pattern(found) for c in targets))

    async def async_preview_pattern(self, **fields: Any) -> None:
        edit = _edit(fields)
        await asyncio.gather(*(c.preview_pattern(edit) for c in self._targets()))
        self._previewed()

    def _previewed(self) -> None:
        """After a preview: the lights show something unsaved."""

    async def async_sync_patterns(self) -> None:
        """Only groups have members to keep the same."""


def describe(p: Pattern | None) -> dict[str, Any] | None:
    """A pattern's settings, in the same terms save_pattern takes."""
    if p is None:
        return None
    out: dict[str, Any] = {
        "name": p.name,
        "speed": byte_to_percent(p.speed),
        "brightness": byte_to_percent(p.brightness),
    }
    if p.category == CATEGORY_PRESET:
        out["preset"] = p.effect
        return out
    n = used_colors(p)
    out["effect"] = EFFECTS[p.effect] if p.effect < len(EFFECTS) else p.effect
    out["colors"] = [f"#{p.dot_colors[i * 3:i * 3 + 3].hex()}" for i in range(n)]
    out["counts"] = list(p.dot_counts[:n])
    return out


# -------------------------------------------------------------- controller

def device_info(coordinator: TrimlightCoordinator, entry: TrimlightConfigEntry) -> DeviceInfo:
    info = coordinator.data.info
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name=info.name,
        manufacturer="Trimlight",
        model=f"{info.pixels} pixels",
    )


class TrimlightLight(CoordinatorEntity[TrimlightCoordinator], _TrimlightBase):
    def __init__(self, coordinator: TrimlightCoordinator, entry: TrimlightConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = light_unique_id(entry)
        self._attr_device_info = device_info(coordinator, entry)
        # What we last sent, for manual mode.
        self._on = False
        self._effect: str | None = None
        self._brightness = 255
        self._rgb: tuple[int, int, int] = (255, 255, 255)

    def _coordinators(self) -> list[TrimlightCoordinator]:
        return [self.coordinator]

    # -- patterns

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

    # -- state

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
        effect = self.effect
        return {
            ATTR_SCHEDULE: self._timer_mode(),
            ATTR_OFF_AT: self._off_at.isoformat() if self._off_at else None,
            ATTR_PATTERN: describe(self._names().get(effect)) if effect else None,
        }

    # -- commands

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
        elif ATTR_EFFECT in kwargs:
            raise ServiceValidationError(f"{self.entity_id} has no pattern called '{kwargs[ATTR_EFFECT]}'")
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
        self.coordinator.set_mode_locally(MODE_TIMER)
        self.async_write_ha_state()

    async def async_rename_pattern(self, pattern: str, new_name: str) -> None:
        await super().async_rename_pattern(pattern, new_name)
        if self._effect and self._effect.strip().lower() == pattern.strip().lower():
            self._effect = new_name.strip()
            self.async_write_ha_state()

    def _previewed(self) -> None:
        self._on = True
        self._effect = None
        self.coordinator.set_mode_locally(MODE_MANUAL)
        self.async_write_ha_state()

    # -- persistence

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        self._on = last.state == STATE_ON
        self._effect = last.attributes.get(ATTR_EFFECT)
        self._brightness = last.attributes.get(ATTR_BRIGHTNESS) or self._brightness
        if rgb := last.attributes.get(ATTR_RGB_COLOR):
            self._rgb = tuple(rgb)
        self._restore_timer(last.attributes)


# ------------------------------------------------------------------- group

class TrimlightGroupLight(_TrimlightBase):
    """Several controllers as one light, through their own lights."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: TrimlightConfigEntry) -> None:
        self._entry = entry
        self._sync_lock = asyncio.Lock()
        self._attr_unique_id = f"group_{entry.entry_id}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"group_{entry.entry_id}")},
            name=entry.title,
            manufacturer="Trimlight",
            model="Group",
        )

    def _coordinators(self) -> list[TrimlightCoordinator]:
        return member_coordinators(self.hass, self._entry)

    def _members(self) -> list[str]:
        return member_entity_ids(self.hass, self._entry)

    def _states(self):
        return [s for e in self._members() if (s := self.hass.states.get(e)) and s.state != STATE_UNAVAILABLE]

    # -- state, from the members' lights

    @property
    def available(self) -> bool:
        return bool(self._states())

    @property
    def effect_list(self) -> list[str]:
        """The patterns every member has, named as the first member has them."""
        states = self._states()
        if not states:
            return []
        common = None
        for s in states:
            names = {n.lower() for n in s.attributes.get(ATTR_EFFECT_LIST) or []}
            common = names if common is None else common & names
        return [n for n in states[0].attributes.get(ATTR_EFFECT_LIST) or [] if n.lower() in common]

    @property
    def is_on(self) -> bool:
        return any(s.state == STATE_ON for s in self._states())

    @property
    def effect(self) -> str | None:
        """The pattern, if every member that's on shows the same one."""
        effects = {(s.attributes.get(ATTR_EFFECT) or "").lower() for s in self._states() if s.state == STATE_ON}
        if len(effects) != 1 or not (key := effects.pop()):
            return None
        return next((n for n in self.effect_list if n.lower() == key), None)

    @property
    def brightness(self) -> int | None:
        levels = [s.attributes.get(ATTR_BRIGHTNESS) for s in self._states() if s.state == STATE_ON]
        levels = [b for b in levels if b is not None]
        return max(levels) if levels else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        for s in self._states():
            if s.state == STATE_ON and (rgb := s.attributes.get(ATTR_RGB_COLOR)):
                return tuple(rgb)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_MEMBERS: self._members(),
            ATTR_OFF_AT: self._off_at.isoformat() if self._off_at else None,
        }

    # -- commands, passed to each member's light

    async def _each(self, service: str, data: dict[str, Any], effect: str | None = None) -> None:
        calls = []
        for state in self._states():
            member_data = {ATTR_ENTITY_ID: state.entity_id, **data}
            if effect is not None:
                names = state.attributes.get(ATTR_EFFECT_LIST) or []
                match = next((n for n in names if n.lower() == effect.lower()), None)
                if match is None:
                    _LOGGER.warning("%s has no pattern '%s'; leaving it as it is", state.entity_id, effect)
                    continue
                member_data[ATTR_EFFECT] = match
            calls.append(
                self.hass.services.async_call("light", service, member_data, blocking=True, context=self._context)
            )
        await asyncio.gather(*calls)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # A pattern made on one controller since the last check is copied to
        # the others first, so it can show on all of them.
        await self.async_sync_patterns()
        data = {k: v for k, v in kwargs.items() if k in (ATTR_BRIGHTNESS, ATTR_RGB_COLOR)}
        await self._each("turn_on", data, kwargs.get(ATTR_EFFECT))

    # -- keeping the members' patterns the same

    async def async_sync_patterns(self) -> None:
        """Copies patterns missing from any member over from the others."""
        if self._sync_lock.locked() or not patterns_out_of_sync(self._coordinators()):
            return
        async with self._sync_lock:
            added = await async_sync_patterns(self.hass, self._entry)
        for name, patterns in added.items():
            _LOGGER.info("%s: copied %s to %s", self._entry.title, ", ".join(patterns), name)

    @callback
    def _check_sync(self) -> None:
        if not self._sync_lock.locked() and patterns_out_of_sync(self._coordinators()):
            self.hass.async_create_task(self.async_sync_patterns())

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._clear_timer()
        await self._each("turn_off", {})
        self.async_write_ha_state()

    # -- follow the members

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def member_changed(_event: Event) -> None:
            self.async_write_ha_state()
            self._check_sync()

        self.async_on_remove(async_track_state_change_event(self.hass, self._members(), member_changed))

        # The controllers are read every minute (their pattern lists when they
        # change), so a pattern made in the app is noticed within about a
        # minute. Also once everything has started (the members load after
        # the group, maybe).
        @callback
        def check(*_args: Any) -> None:
            self._check_sync()

        self.async_on_remove(async_track_time_interval(self.hass, check, timedelta(seconds=60)))
        self.async_on_remove(async_at_started(self.hass, check))
        if (last := await self.async_get_last_state()) is not None:
            self._restore_timer(last.attributes)
