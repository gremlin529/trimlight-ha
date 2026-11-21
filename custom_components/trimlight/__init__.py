"""Trimlight permanent LED lights, controlled over the local network."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import TrimlightCoordinator
from .protocol import Trimlight

PLATFORMS = [Platform.LIGHT, Platform.SWITCH]

type TrimlightConfigEntry = ConfigEntry[TrimlightCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    coordinator = TrimlightCoordinator(hass, entry, Trimlight(entry.data[CONF_HOST]))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrimlightConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
