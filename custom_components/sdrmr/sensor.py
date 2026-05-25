from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ELECTRIC_MULTIPLIER,
    CONF_ELECTRIC_UNIT,
    CONF_GAS_MULTIPLIER,
    CONF_GAS_UNIT,
    CONF_WATER_MULTIPLIER,
    CONF_WATER_UNIT,
    DOMAIN,
    ELECTRIC_TYPES,
    GAS_TYPES,
    WATER_TYPES,
)
from .coordinator import SdrmrCoordinator

SIGNAL_NEW_READING = f"{DOMAIN}_new_reading"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SdrmrCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_meters: set[str] = set()

    @callback
    def _on_reading(reading: dict) -> None:
        meter_id = str(reading["meter_id"])
        utility = reading["utility"]
        unique_id = f"{meter_id}_sdrmr_{utility}"
        if unique_id not in known_meters:
            known_meters.add(unique_id)
            async_add_entities([SdrmrSensor(entry, meter_id, utility, reading)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{SIGNAL_NEW_READING}_{entry.entry_id}", _on_reading)
    )


class SdrmrSensor(SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, meter_id: str, utility: str, reading: dict) -> None:
        self._entry = entry
        self._meter_id = meter_id
        self._utility = utility
        self._extra_attrs: dict = {}

        self._attr_unique_id = f"{meter_id}_sdrmr_{utility}"
        self._attr_name = utility.capitalize()

        endpoint_type = reading.get("endpoint_type")
        data = entry.data

        if utility == "gas":
            self._attr_device_class = SensorDeviceClass.GAS
            self._attr_native_unit_of_measurement = data.get(CONF_GAS_UNIT, "ft³")
            self._multiplier = data.get(CONF_GAS_MULTIPLIER, 1.0)
        elif utility == "electric":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = data.get(CONF_ELECTRIC_UNIT, "kWh")
            self._multiplier = data.get(CONF_ELECTRIC_MULTIPLIER, 1.0)
        elif utility == "water":
            self._attr_device_class = SensorDeviceClass.WATER
            self._attr_native_unit_of_measurement = data.get(CONF_WATER_UNIT, "gal")
            self._multiplier = data.get(CONF_WATER_MULTIPLIER, 1.0)
        else:
            self._attr_device_class = None
            self._attr_native_unit_of_measurement = None
            self._multiplier = 1.0

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter_id)},
            name=f"Meter {meter_id}",
            manufacturer="SDR Meter Reader",
            model=reading.get("msg_type", "unknown").upper(),
        )

        self._apply_reading(reading)

    def _apply_reading(self, reading: dict) -> None:
        consumption = reading.get("consumption", 0)
        self._attr_native_value = round(consumption * self._multiplier, 4)
        self._extra_attrs = {
            k: v for k, v in reading.items()
            if k not in ("consumption", "meter_id", "utility", "msg_type", "endpoint_type")
        }

    @property
    def extra_state_attributes(self) -> dict:
        return self._extra_attrs

    async def async_added_to_hass(self) -> None:
        coordinator: SdrmrCoordinator = self.hass.data[DOMAIN][self._entry.entry_id]
        coordinator.register_sensor(self._attr_unique_id, self)

    @callback
    def handle_reading(self, reading: dict) -> None:
        self._apply_reading(reading)
        self.async_write_ha_state()
