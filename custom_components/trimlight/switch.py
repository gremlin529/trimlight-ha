"""Run schedule: on hands the controller to its own schedules (timer mode),
off keeps it on whatever was last chosen (manual mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrimlightConfigEntry
from .coordinator import TrimlightCoordinator
from .light import device_info
from .protocol import MODE_MANUAL, MODE_TIMER


async def async_setup_entry(
    hass: HomeAssistant, entry: TrimlightConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TrimlightSchedule(entry.runtime_data, entry)])


class TrimlightSchedule(CoordinatorEntity[TrimlightCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: TrimlightCoordinator, entry: TrimlightConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_schedule"
        self._attr_device_info = device_info(coordinator, entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.info.mode == MODE_TIMER

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_mode(MODE_TIMER)
        self.coordinator.set_mode_locally(MODE_TIMER)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.set_mode(MODE_MANUAL)
        self.coordinator.set_mode_locally(MODE_MANUAL)
