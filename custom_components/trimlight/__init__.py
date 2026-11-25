"""Trimlight permanent LED lights, controlled over the local network."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryHider

from .const import DOMAIN
from .coordinator import TrimlightCoordinator
from .groups import is_group, light_unique_id, member_ids
from .protocol import Trimlight

PLATFORMS = [Platform.LIGHT]

# A controller's runtime data is its coordinator; a group has none.
type TrimlightConfigEntry = ConfigEntry[TrimlightCoordinator | None]


async def async_setup_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    if is_group(entry):
        entry.runtime_data = None
        # Hide member entities from the UI so only the group appears
        await _hide_group_members(hass, entry)
        # Changing a group's members (its options) sets it up again.
        entry.async_on_unload(entry.add_update_listener(_reload))
    else:
        coordinator = TrimlightCoordinator(hass, entry, Trimlight(entry.data[CONF_HOST]))
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _hide_group_members(hass: HomeAssistant, entry: TrimlightConfigEntry) -> None:
    """Hide the individual member entities so only the group appears in blueprints."""
    registry = er.async_get(hass)
    
    for member_id in member_ids(entry):
        member_entry = hass.config_entries.async_get_entry(member_id)
        if member_entry is None:
            continue
        entity_id = registry.async_get_entity_id("light", DOMAIN, light_unique_id(member_entry))
        if entity_id:
            registry.async_update_entity(entity_id, hidden_by=RegistryEntryHider.INTEGRATION)


async def _reload(hass: HomeAssistant, entry: TrimlightConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    if is_group(entry):
        # Unhide member entities when group is deleted
        registry = er.async_get(hass)
        
        for member_id in member_ids(entry):
            member_entry = hass.config_entries.async_get_entry(member_id)
            if member_entry is None:
                continue
            entity_id = registry.async_get_entity_id("light", DOMAIN, light_unique_id(member_entry))
            if entity_id:
                registry.async_update_entity(entity_id, hidden_by=None)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
