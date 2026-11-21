"""Trimlight permanent LED lights, controlled over the local network."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import TrimlightCoordinator
from .group import is_group
from .protocol import Trimlight

PLATFORMS = [Platform.LIGHT]

# A controller's runtime data is its coordinator; a group has none.
type TrimlightConfigEntry = ConfigEntry[TrimlightCoordinator | None]


async def async_setup_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    if is_group(entry):
        entry.runtime_data = None
        # Changing a group's members (its options) sets it up again.
        entry.async_on_unload(entry.add_update_listener(_reload))
    else:
        coordinator = TrimlightCoordinator(hass, entry, Trimlight(entry.data[CONF_HOST]))
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: TrimlightConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
