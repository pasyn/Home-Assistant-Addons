DOMAIN = "sdrmr"

# Endpoint type → utility classification, ported from SDRMR/run.sh
GAS_TYPES = {0, 1, 2, 9, 12, 156, 188}
ELECTRIC_TYPES = {4, 5, 7, 8}
WATER_TYPES = {3, 11, 13, 171}

DEFAULT_HOST = "homeassistant"
DEFAULT_PORT = 1234

CONF_RTLTCP_HOST = "rtltcp_host"
CONF_RTLTCP_PORT = "rtltcp_port"
CONF_MSG_TYPE = "msg_type"
CONF_FILTER_IDS = "filter_ids"
CONF_GAS_UNIT = "gas_unit"
CONF_ELECTRIC_UNIT = "electric_unit"
CONF_WATER_UNIT = "water_unit"
CONF_GAS_MULTIPLIER = "gas_multiplier"
CONF_ELECTRIC_MULTIPLIER = "electric_multiplier"
CONF_WATER_MULTIPLIER = "water_multiplier"

MSG_TYPES = ["scm", "scm+", "r900", "r900bcd", "idm", "netidm", "all"]
GAS_UNITS = ["ft³", "m³"]
ELECTRIC_UNITS = ["Wh", "kWh", "MWh"]
WATER_UNITS = ["gal", "l"]
