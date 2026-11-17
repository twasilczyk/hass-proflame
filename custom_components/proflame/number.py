"""Flame level and transmit tuning."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProflameConfigEntry
from .device import TRANSMIT_TUNING_RANGE, Origin, ProflameDevice
from .entity import ProflameEntity
from .protocol import MAX_LEVEL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProflameConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the fireplace numbers."""
    async_add_entities([
        ProflameFlame(entry.runtime_data),
        ProflameTransmitFrequency(entry.runtime_data),
    ])


class ProflameTransmitFrequency(ProflameEntity, NumberEntity):
    """Per-fireplace transmit frequency in kHz."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfFrequency.KILOHERTZ
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, device: ProflameDevice) -> None:
        """Bound tuning to the configured nominal band."""
        super().__init__(device, "transmit_frequency")
        self._attr_native_min_value = (device.frequency - TRANSMIT_TUNING_RANGE) / 1000
        self._attr_native_max_value = (device.frequency + TRANSMIT_TUNING_RANGE) / 1000

    @property
    @override
    def native_value(self) -> float:
        """Return the effective transmit frequency."""
        return self.device.transmit_frequency / 1000

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Store integer Hz, rounding floating point conversion noise."""
        await self.device.async_set_transmit_frequency(round(value * 1000))
        self.async_write_ha_state()


class ProflameFlame(ProflameEntity, NumberEntity):
    """Main flame height, 0 to 6.

    A number rather than a percentage: the appliance has exactly seven
    positions and the handset counts them, so showing 0–6 says what will
    actually happen. Level 0 with the fire on is the appliance's own lowest
    setting, not "off" — off is the switch.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = MAX_LEVEL
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, device: Any) -> None:
        """Initialize the number."""
        super().__init__(device, "flame")

    @property
    @override
    def native_value(self) -> float:
        """The flame level believed current."""
        return float(self.device.state.flame)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the flame level."""
        await self.device.async_set(Origin.USER, flame=int(value))
