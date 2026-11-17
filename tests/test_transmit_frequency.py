"""TX tuning is persisted configuration, independent of appliance state."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.number import NumberMode
from homeassistant.components.radio_frequency import (
    DATA_COMPONENT,
    ModulationType,
    RadioFrequencyTransmitterEntity,
)
from homeassistant.const import EntityCategory, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store

from custom_components.proflame.device import Origin, ProflameDevice
from custom_components.proflame.number import ProflameTransmitFrequency
from custom_components.proflame.protocol import CE_FREQUENCY, FCC_FREQUENCY, Remote

REMOTE = Remote(serial1=0x21, serial2=0xDD, version=2, key1=0x3A, key2=0x9C)
TRANSMITTER = "radio_frequency.test"


def make_device(hass: HomeAssistant, nominal: int = FCC_FREQUENCY) -> ProflameDevice:
    return ProflameDevice(hass, "fireplace", TRANSMITTER, REMOTE, nominal)


@pytest.fixture
def transmitter(hass: HomeAssistant) -> MagicMock:
    """Use the real RF capability filter with a controllable transmitter."""
    radio = MagicMock(spec=RadioFrequencyTransmitterEntity)
    radio.entity_id = TRANSMITTER
    radio.supports_frequency.return_value = True
    radio.supports_modulation.return_value = True
    hass.data[DATA_COMPONENT] = MagicMock(entities=[radio])
    return radio


@pytest.mark.parametrize("nominal", [FCC_FREQUENCY, CE_FREQUENCY])
async def test_old_storage_defaults_to_nominal(hass: HomeAssistant, nominal: int) -> None:
    device = make_device(hass, nominal)
    # Save state in the old shape, with no tuning field.
    await Store[dict[str, object]](hass, 1, "fireplace_state").async_save(
        {
            "power": 1,
            "flame": 3,
            "fan": 2,
            "light": 1,
            "thermostat": 0,
            "aux": 0,
            "front": 0,
            "pilot": 1,
        }
    )
    await device.async_load()
    assert device.transmit_frequency == nominal
    assert device.state.power and device.state.flame == 3
    entity = ProflameTransmitFrequency(device)
    assert entity.native_value == nominal / 1000
    assert entity.native_min_value == nominal / 1000 - 100
    assert entity.native_max_value == nominal / 1000 + 100
    assert entity.native_step == 0.1
    assert entity.mode == NumberMode.BOX
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.native_unit_of_measurement == UnitOfFrequency.KILOHERTZ


@pytest.mark.parametrize("nominal", [FCC_FREQUENCY, CE_FREQUENCY])
async def test_tuning_survives_restart_and_only_next_command_transmits(
    hass: HomeAssistant, transmitter: MagicMock, nominal: int
) -> None:
    device = make_device(hass, nominal)
    original_state = device.state
    listener = MagicMock()
    device.async_add_listener(listener)
    entity = ProflameTransmitFrequency(device)
    frequency = nominal + 12_300
    with (
        patch.object(entity, "async_write_ha_state") as write_state,
        patch(
            "custom_components.proflame.device.async_send_command", new_callable=AsyncMock
        ) as send,
        patch.object(hass.config_entries, "async_reload") as reload_entry,
    ):
        await entity.async_set_native_value(frequency / 1000)
        assert entity.native_value == frequency / 1000
        write_state.assert_called_once()
        send.assert_not_called()
        reload_entry.assert_not_called()
        listener.assert_not_called()
        assert device.state is original_state
        assert device.remote is REMOTE
        assert device.frequency == nominal
        transmitter.supports_frequency.assert_called_with(frequency)
        transmitter.supports_modulation.assert_called_with(ModulationType.OOK)

        restarted = make_device(hass, nominal)
        await restarted.async_load()
        assert restarted.transmit_frequency == frequency
        await restarted.async_set(Origin.USER, flame=4)
        command = send.call_args.args[2]
        assert command.frequency == frequency
        assert isinstance(command.frequency, int)

        await restarted.async_set_transmit_frequency(nominal)
        saved = await Store[dict[str, object]](hass, 1, "fireplace_state").async_load()
        assert saved is not None
        assert saved["transmit_frequency_override"] is None
        restored = make_device(hass, nominal)
        await restored.async_load()
        assert restored.transmit_frequency == nominal


@pytest.mark.parametrize("failure", ["frequency", "modulation", "other_radio", "missing", "range"])
async def test_invalid_tuning_preserves_current_setting(
    hass: HomeAssistant, transmitter: MagicMock, failure: str
) -> None:
    device = make_device(hass)
    await device.async_set_transmit_frequency(FCC_FREQUENCY + 100)
    before = await Store[dict[str, object]](hass, 1, "fireplace_state").async_load()
    requested = FCC_FREQUENCY + 200
    if failure == "frequency":
        transmitter.supports_frequency.return_value = False
    elif failure == "modulation":
        transmitter.supports_modulation.return_value = False
    elif failure == "other_radio":
        transmitter.entity_id = "radio_frequency.other"
    elif failure == "missing":
        hass.data.pop(DATA_COMPONENT)
    else:
        requested = FCC_FREQUENCY + 100_001
    with pytest.raises(ServiceValidationError):
        await device.async_set_transmit_frequency(requested)
    assert device.transmit_frequency == FCC_FREQUENCY + 100
    assert await Store[dict[str, object]](hass, 1, "fireplace_state").async_load() == before


@pytest.mark.parametrize(
    "override",
    [CE_FREQUENCY, FCC_FREQUENCY - 100_001, FCC_FREQUENCY + 100_001, "315000100", True, None],
)
async def test_stale_or_invalid_override_ignored(hass: HomeAssistant, override: object) -> None:
    await Store[dict[str, object]](hass, 1, "fireplace_state").async_save(
        {"transmit_frequency_override": override}
    )
    device = make_device(hass)
    await device.async_load()
    assert device.transmit_frequency == FCC_FREQUENCY


@pytest.mark.parametrize("offset", [-100_000, 100_000])
async def test_range_endpoints(hass: HomeAssistant, transmitter: MagicMock, offset: int) -> None:
    device = make_device(hass)
    await device.async_set_transmit_frequency(FCC_FREQUENCY + offset)
    restored = make_device(hass)
    await restored.async_load()
    assert restored.transmit_frequency == FCC_FREQUENCY + offset
