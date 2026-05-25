from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_FILTER_IDS,
    CONF_MSG_TYPE,
    CONF_RTLTCP_HOST,
    CONF_RTLTCP_PORT,
    DOMAIN,
    ELECTRIC_TYPES,
    GAS_TYPES,
    WATER_TYPES,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

SIGNAL_NEW_READING = f"{DOMAIN}_new_reading"


def _classify_utility(endpoint_type: int | None) -> str:
    if endpoint_type in GAS_TYPES:
        return "gas"
    if endpoint_type in ELECTRIC_TYPES:
        return "electric"
    if endpoint_type in WATER_TYPES:
        return "water"
    return "unknown"


class SdrmrCoordinator:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # meter_id → SdrmrSensor, populated by sensor platform
        self._sensors: dict[str, object] = {}

    def register_sensor(self, unique_id: str, sensor) -> None:
        self._sensors[unique_id] = sensor

    async def async_start(self) -> None:
        self._stop_event.clear()
        self._task = self.hass.async_create_background_task(
            self._listen_loop(), name="sdrmr_listener"
        )

    async def async_stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self) -> None:
        from .amr.client import SdrClient

        data = self.entry.data
        host = data[CONF_RTLTCP_HOST]
        port = data[CONF_RTLTCP_PORT]
        msg_type = data.get(CONF_MSG_TYPE, "scm")
        filter_ids_raw = data.get(CONF_FILTER_IDS, "")
        filter_ids: set[str] = (
            {s.strip() for s in filter_ids_raw.split(",") if s.strip()}
            if filter_ids_raw
            else set()
        )

        while not self._stop_event.is_set():
            try:
                client = SdrClient(host=host, port=port, msg_type=msg_type)
                async for reading in client.stream(self._stop_event):
                    meter_id = str(reading.get("meter_id", ""))
                    if filter_ids and meter_id not in filter_ids:
                        continue
                    endpoint_type = reading.get("endpoint_type")
                    reading["utility"] = _classify_utility(endpoint_type)
                    self._dispatch(reading)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning("SDR connection lost: %s — reconnecting in 10s", exc)
                await asyncio.sleep(10)

    def _dispatch(self, reading: dict) -> None:
        meter_id = str(reading["meter_id"])
        utility = reading["utility"]
        unique_id = f"{meter_id}_sdrmr_{utility}"

        sensor = self._sensors.get(unique_id)
        if sensor is not None:
            self.hass.loop.call_soon_threadsafe(sensor.handle_reading, reading)
        else:
            # New meter — signal sensor platform to create entity
            async_dispatcher_send(
                self.hass,
                f"{SIGNAL_NEW_READING}_{self.entry.entry_id}",
                reading,
            )
