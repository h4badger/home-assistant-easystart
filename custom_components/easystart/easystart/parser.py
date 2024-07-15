"""Parser for EasyStart devices"""

from __future__ import annotations

import asyncio
import dataclasses
import struct
from collections import namedtuple
from datetime import datetime
import logging

# from logging import Logger
from math import exp
from typing import Any, Callable, Tuple, TypeVar, cast

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])

class BleakCharacteristicMissing(BleakError):
    """Raised when a characteristic is missing from a service."""


class BleakServiceMissing(BleakError):
    """Raised when a service is missing."""

READ_CHARACTERISTIC_UUID = "d973f2e1-b19e-11e2-9e96-0800200c9a66"
WRITE_CHARACTERISTIC_UUID = "d973f2e2-b19e-11e2-9e96-0800200c9a66"
CMD_READLIVE = b"\x7b\x22\x43\x6d\x64\x22\x3a\x20\x52\x65\x61\x64\x4c\x69\x76\x65\x7d"
STATUS_PACKET = 123

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class EasyStartDevice:
    """Response data with information about the EasyStart device"""

    STATUS_TEXT = [
        "Normal",
        "Unexpected Curr Flt",
        "Short Cycle Delay",
        "Pwr Intrrptn Fault",
        "Stall Fault",
        "Stuck SR Fault",
        "Open Ovrld Fault",
        "Overcurrent Fault",
        "Bad Wiring Fault",
        "Wrong Voltage Flt"
    ]

    hw_version: str = ""
    sw_version: str = ""
    name: str = ""
    identifier: str = ""
    address: str = ""
    sensors: dict[str, str | float | None] = dataclasses.field(
        default_factory=lambda: {}
    )


# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
class EasyStartBluetoothDeviceData:
    """Data for EasyStart sensors."""

    _event: asyncio.Event | None
    _command_data: bytearray | None

    def __init__(
        self,
        logger: Logger,
    ):
        super().__init__()
        self.logger = logger
        self._command_data = None
        self._event = None

    def notification_handler(self, _: Any, data: bytearray) -> None:
        """Helper for command events"""
        if data[0] == STATUS_PACKET:
            return
        else:
            self._command_data = data

        if self._event is None:
            return
        self._event.set()

    def disconnect_on_missing_services(func: WrapFuncType) -> WrapFuncType:
        """Define a wrapper to disconnect on missing services and characteristics.

        This must be placed after the retry_bluetooth_connection_error
        decorator.
        """

        async def _async_disconnect_on_missing_services_wrap(
            self, *args: Any, **kwargs: Any
        ) -> None:
            try:
                return await func(self, *args, **kwargs)
            except (BleakServiceMissing, BleakCharacteristicMissing) as ex:
                logger.warning(
                    "%s: Missing service or characteristic, disconnecting to force refetch of GATT services: %s",
                    self.name,
                    ex,
                )
                if self.client:
                    await self.client.clear_cache()
                    await self.client.disconnect()
                raise

        return cast(WrapFuncType, _async_disconnect_on_missing_services_wrap)

    @disconnect_on_missing_services
    async def _get_live(self, client: BleakClient, device: EasyStartDevice) -> EasyStartDevice:

        self._event = asyncio.Event()
        try:
            await client.start_notify(
                READ_CHARACTERISTIC_UUID, self.notification_handler
            )
        except:
            self.logger.warn("_get_live Bleak error 1")

        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, CMD_READLIVE)

        self.logger.info("Wrote ReadLive Cmd")

        # Wait for up to ten seconds to see if a
        # callback comes in.
        try:
            await asyncio.wait_for(self._event.wait(), 10)
        except asyncio.TimeoutError:
            self.logger.warn("Timeout getting command data.")
        except:
            self.logger.warn("_get_live Bleak error 2")

        await client.stop_notify(READ_CHARACTERISTIC_UUID)

        if self._command_data is not None and len(self._command_data) == 18 and self._command_data[0] != STATUS_PACKET:
            self.logger.info("Got data: %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d", self._command_data[0], self._command_data[1], self._command_data[2], self._command_data[3], self._command_data[4], self._command_data[5], self._command_data[6], self._command_data[7], self._command_data[8], self._command_data[9], self._command_data[10], self._command_data[11], self._command_data[12], self._command_data[13], self._command_data[14], self._command_data[15], self._command_data[16], self._command_data[17])
            device.sensors["status"] = EasyStartDevice.STATUS_TEXT[self._command_data[2]] if self._command_data[2] < len(EasyStartDevice.STATUS_TEXT) else "Unknown"
            device.sensors["learned_starts"] = int(self._command_data[3])
            device.sensors["current"] = float((self._command_data[4] + (self._command_data[5] * 256.0)) / 10.0)
            device.sensors["line_frequency"] = float(500000.0 / (self._command_data[6] + (self._command_data[7] * 256.0)))
            device.sensors["last_start_peak"] = float((self._command_data[8] + (self._command_data[9] * 256.0)) / 10.0)
            device.sensors["scpt_delay"] = int((self._command_data[10] + (self._command_data[11] * 256)))
            device.sensors["total_faults"] = int((self._command_data[12] + (self._command_data[13] * 256)))
            device.sensors["total_starts"] = int(self._command_data[14] + (self._command_data[15] << 8) + (self._command_data[16] << 16) + (self._command_data[17] << 24))
        else:
            device.sensors["status"] = "Unknown"
            device.sensors["learned_starts"] = int(0)
            device.sensors["current"] = float(0.0)
            device.sensors["line_frequency"] = float(0.0)
            device.sensors["last_start_peak"] = float(0.0)
            device.sensors["scpt_delay"] = int(0)
            device.sensors["total_faults"] = int(0)
            device.sensors["total_starts"] = int(0)
        self._command_data = None
        return device


    async def update_device(self, ble_device: BLEDevice) -> EasyStartDevice:
        """Connects to the device through BLE and retrieves relevant data"""

        client = await establish_connection(BleakClient, ble_device, ble_device.address)
        device = EasyStartDevice()
        device.name = ble_device.name
        device.address = ble_device.address

        device = await self._get_live(client, device)

        await client.disconnect()

        return device
