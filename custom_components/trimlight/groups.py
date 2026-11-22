"""Groups: several controllers in one space, controlled together as one light.

A group is its own config entry listing its members' config entry IDs. It
owns no connection; it works through the members' lights and coordinators."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .const import CONF_MEMBERS, CONF_TYPE, DOMAIN, TYPE_GROUP
from .coordinator import TrimlightCoordinator
from .protocol import Pattern


def is_group(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_TYPE) == TYPE_GROUP


def member_ids(entry: ConfigEntry) -> list[str]:
    """Member config entry IDs; options (edited later) win over the data."""
    return list(entry.options.get(CONF_MEMBERS, entry.data.get(CONF_MEMBERS, [])))


def light_unique_id(entry: ConfigEntry) -> str:
    return f"{entry.unique_id or entry.entry_id}_light"


def member_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """The members' light entity IDs, for the ones that still exist."""
    registry = er.async_get(hass)
    out = []
    for member_id in member_ids(entry):
        member = hass.config_entries.async_get_entry(member_id)
        if member is None:
            continue
        if entity_id := registry.async_get_entity_id("light", DOMAIN, light_unique_id(member)):
            out.append(entity_id)
    return out


def member_coordinators(hass: HomeAssistant, entry: ConfigEntry) -> list[TrimlightCoordinator]:
    """The members that are set up and have been read."""
    out = []
    for member_id in member_ids(entry):
        member = hass.config_entries.async_get_entry(member_id)
        if member is not None and member.state is ConfigEntryState.LOADED and member.runtime_data.data:
            out.append(member.runtime_data)
    return out


def coordinators_for_entity(hass: HomeAssistant, entity_id: str) -> list[TrimlightCoordinator]:
    """The controller(s) behind a Trimlight light: one, or a group's members."""
    reg = er.async_get(hass).async_get(entity_id)
    entry = hass.config_entries.async_get_entry(reg.config_entry_id) if reg and reg.config_entry_id else None
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"{entity_id} isn't a Trimlight light")
    if is_group(entry):
        return member_coordinators(hass, entry)
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"{entity_id} isn't set up")
    return [entry.runtime_data]


def _key(p: Pattern) -> str:
    return p.name.strip().lower()


def patterns_out_of_sync(coordinators: list[TrimlightCoordinator]) -> bool:
    """Whether the controllers' pattern names differ (ignoring case)."""
    names = [{_key(p) for p in c.data.patterns if p.name.strip()} for c in coordinators]
    return len(names) > 1 and any(n != names[0] for n in names[1:])


async def async_sync_patterns(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, list[str]]:
    """Gives every controller in a group every pattern any of them has
    (matched by name, ignoring case), copying the missing ones over. A name
    on several controllers keeps the first member's version. Returns what
    was added, by controller name."""
    coordinators = member_coordinators(hass, entry)
    if len(coordinators) < 2:
        return {}
    union: dict[str, Pattern] = {}
    for c in coordinators:
        for p in c.data.patterns:
            if p.name.strip():
                union.setdefault(_key(p), p)
    added: dict[str, list[str]] = {}
    for c in coordinators:
        have = {_key(p) for p in c.data.patterns}
        missing = [p for k, p in union.items() if k not in have]
        if missing:
            await c.add_patterns(missing)
            added[c.data.info.name] = [p.name for p in missing]
    return added
