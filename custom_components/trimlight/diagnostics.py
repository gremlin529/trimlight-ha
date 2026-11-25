"""Diagnostics for Trimlight integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id].get("coordinator")

    return {
        "config_entry_data": async_redact_data(config_entry.data, TO_REDACT),
        "device_info": {
            "name": coordinator.device_info.name if coordinator else "Unknown",
            "mode": coordinator.device_info.mode if coordinator else "Unknown",
            "pixels": coordinator.device_info.pixels if coordinator else "Unknown",
        },
        "patterns_count": len(coordinator.patterns) if coordinator else 0,
        "schedules_count": len(coordinator.schedules) if coordinator else 0,
        "last_update": coordinator.last_update_success if coordinator else None,
        "unavailable_count": coordinator.unavailable_count if coordinator else 0,
    }
