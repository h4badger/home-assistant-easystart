"""Support for EasyStart sensors."""
from __future__ import annotations

import logging
import dataclasses

from .easystart import EasyStartDevice

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfFrequency,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SENSORS_MAPPING_TEMPLATE: dict[str, SensorEntityDescription] = {
    "status": SensorEntityDescription(
        key="status",
        name="Status",
        device_class=SensorDeviceClass.ENUM,
        options=EasyStartDevice.STATUS_TEXT + ["Unknown"],
        icon="mdi:list-status",
    ),
    "current": SensorEntityDescription(
        key="current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        name="Current",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
    ),
    "line_frequency": SensorEntityDescription(
        key="line_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        name="Line Frequency",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sine-wave",
    ),
    "last_start_peak": SensorEntityDescription(
        key="last_start_peak",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        name="Last Start Peak",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-ac",
    ),
    "scpt_delay": SensorEntityDescription(
        key="scpt_delay",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        name="SCPT Delay",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
    ),
    "learned_starts": SensorEntityDescription(
        key="learned_starts",
        suggested_display_precision=0,
        name="Learned Starts",
        icon="mdi:counter",
    ),
    "total_faults": SensorEntityDescription(
        key="total_faults",
        suggested_display_precision=0,
        name="Total Faults",
        icon="mdi:counter",
    ),
    "total_starts": SensorEntityDescription(
        key="total_starts",
        suggested_display_precision=0,
        name="Total Starts",
        icon="mdi:counter",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EasyStart sensors."""

    coordinator: DataUpdateCoordinator[EasyStartDevice] = hass.data[DOMAIN][entry.entry_id]

    sensors_mapping = SENSORS_MAPPING_TEMPLATE.copy()

    entities = []
    _LOGGER.debug("got sensors: %s", coordinator.data.sensors)
    for sensor_type, sensor_value in coordinator.data.sensors.items():
        if sensor_type not in sensors_mapping:
            _LOGGER.debug(
                "Unknown sensor type detected: %s, %s",
                sensor_type,
                sensor_value,
            )
            continue
        entities.append(
            EasyStartSensor(coordinator, coordinator.data, sensors_mapping[sensor_type])
        )

    async_add_entities(entities)


class EasyStartSensor(CoordinatorEntity[DataUpdateCoordinator[EasyStartDevice]], SensorEntity):
    """EasyStart sensors for the device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        easystart_device: EasyStartDevice,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Populate the EasyStart entity with relevant data."""
        super().__init__(coordinator)
        self.entity_description = entity_description

        name = f"{easystart_device.name} {easystart_device.identifier}"

        self._attr_unique_id = f"{name}_{entity_description.key}"

        self._id = easystart_device.address
        self._attr_device_info = DeviceInfo(
            connections={
                (
                    CONNECTION_BLUETOOTH,
                    easystart_device.address,
                )
            },
            name=name,
            manufacturer="Micro-Air, LLC.",
            model="EasyStart",
            hw_version=easystart_device.hw_version,
            sw_version=easystart_device.sw_version,
        )

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        try:
            return self.coordinator.data.sensors[self.entity_description.key]
        except KeyError:
            return None
