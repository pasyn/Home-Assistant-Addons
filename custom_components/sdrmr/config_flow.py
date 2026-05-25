from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_ELECTRIC_MULTIPLIER,
    CONF_ELECTRIC_UNIT,
    CONF_FILTER_IDS,
    CONF_GAS_MULTIPLIER,
    CONF_GAS_UNIT,
    CONF_MSG_TYPE,
    CONF_RTLTCP_HOST,
    CONF_RTLTCP_PORT,
    CONF_WATER_MULTIPLIER,
    CONF_WATER_UNIT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DOMAIN,
    ELECTRIC_UNITS,
    GAS_UNITS,
    MSG_TYPES,
    WATER_UNITS,
)

STEP_CONNECTION = vol.Schema(
    {
        vol.Required(CONF_RTLTCP_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_RTLTCP_PORT, default=DEFAULT_PORT): vol.Coerce(int),
    }
)

STEP_PROTOCOL = vol.Schema(
    {
        vol.Required(CONF_MSG_TYPE, default="scm"): vol.In(MSG_TYPES),
        vol.Optional(CONF_FILTER_IDS, default=""): str,
    }
)

STEP_UNITS = vol.Schema(
    {
        vol.Required(CONF_GAS_UNIT, default="ft³"): vol.In(GAS_UNITS),
        vol.Required(CONF_ELECTRIC_UNIT, default="kWh"): vol.In(ELECTRIC_UNITS),
        vol.Required(CONF_WATER_UNIT, default="gal"): vol.In(WATER_UNITS),
        vol.Required(CONF_GAS_MULTIPLIER, default=1.0): vol.Coerce(float),
        vol.Required(CONF_ELECTRIC_MULTIPLIER, default=1.0): vol.Coerce(float),
        vol.Required(CONF_WATER_MULTIPLIER, default=1.0): vol.Coerce(float),
    }
)


class SdrmrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_protocol()
        return self.async_show_form(step_id="user", data_schema=STEP_CONNECTION)

    async def async_step_protocol(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_units()
        return self.async_show_form(step_id="protocol", data_schema=STEP_PROTOCOL)

    async def async_step_units(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            title = f"SDR Meter Reader ({self._data[CONF_RTLTCP_HOST]}:{self._data[CONF_RTLTCP_PORT]})"
            return self.async_create_entry(title=title, data=self._data)
        return self.async_show_form(step_id="units", data_schema=STEP_UNITS)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SdrmrOptionsFlow(config_entry)


class SdrmrOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self._entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_MSG_TYPE, default=data.get(CONF_MSG_TYPE, "scm")): vol.In(MSG_TYPES),
                vol.Optional(CONF_FILTER_IDS, default=data.get(CONF_FILTER_IDS, "")): str,
                vol.Required(CONF_GAS_UNIT, default=data.get(CONF_GAS_UNIT, "ft³")): vol.In(GAS_UNITS),
                vol.Required(CONF_ELECTRIC_UNIT, default=data.get(CONF_ELECTRIC_UNIT, "kWh")): vol.In(ELECTRIC_UNITS),
                vol.Required(CONF_WATER_UNIT, default=data.get(CONF_WATER_UNIT, "gal")): vol.In(WATER_UNITS),
                vol.Required(CONF_GAS_MULTIPLIER, default=data.get(CONF_GAS_MULTIPLIER, 1.0)): vol.Coerce(float),
                vol.Required(CONF_ELECTRIC_MULTIPLIER, default=data.get(CONF_ELECTRIC_MULTIPLIER, 1.0)): vol.Coerce(float),
                vol.Required(CONF_WATER_MULTIPLIER, default=data.get(CONF_WATER_MULTIPLIER, 1.0)): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
