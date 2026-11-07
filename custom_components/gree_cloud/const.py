"""Constants for the Gree Climate Cloud integration."""

DOMAIN = "gree_cloud"

# Config flow constants
CONF_SERVER = "server"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Options (entry.options): {mac: entity_id} of sensors whose value replaces
# the unit's own room temperature reading (#10). Older ducted/central units
# expose no indoor sensor and report the setpoint instead.
CONF_EXTERNAL_TEMPERATURE_SENSORS = "external_temperature_sensors"
OPT_DEVICE = "device"
OPT_TEMPERATURE_SENSOR = "temperature_sensor"

# Update intervals
UPDATE_INTERVAL = 60  # Cloud polling interval in seconds
DISCOVERY_TIMEOUT = 10

# Error thresholds
MAX_ERRORS = 3
MAX_EXPECTED_RESPONSE_TIME_INTERVAL = 180

# Dispatcher signals
DISPATCH_DEVICE_DISCOVERED = f"{DOMAIN}_device_discovered"

# Fan modes not provided by Home Assistant
FAN_MEDIUM_LOW = "medium-low"
FAN_MEDIUM_HIGH = "medium-high"

# Temperature settings. Half-degree steps are only offered to units that report
# support for it (Props.TEMP_HALF_ENABLED); everything else stays whole-degree.
TARGET_TEMPERATURE_STEP = 1
TARGET_TEMPERATURE_STEP_HALF = 0.5

# Gree HWHP (Hot Water Heat Pump) settings
HWHP_PROP_WATER_TEMP = "WatTmp"  # Current water temperature property key
HWHP_PROP_SET_TEM_INT = "SetTemInt"  # Target temperature (integer part)
HWHP_PROP_SET_TEM_DEC = "SetTemDec"  # Target temperature (decimal part, tenths)
HWHP_TEMP_ENCODING_OFFSET = 100  # Raw temp encoding: actual = raw - offset
HWHP_TEMP_MIN = 40  # Minimum target temperature for hot water (°C)
HWHP_TEMP_MAX = 80  # Maximum target temperature for hot water (°C)
HWHP_PROP_WMOD = "Wmod"  # Water heater mode: 0=heat pump, 2=boost/performance
HWHP_PROP_WSTATE = "Wstate"  # Heating state: 0=keep warm (idle), 1=actively heating
HWHP_PROP_POW_CONSUMP = "powConsump"  # Power consumption (raw device units)
HWHP_PROP_WATER_PERCENT = "Watpercent"  # Tank fill percentage (raw: actual = raw - offset)
HWHP_WMOD_HEAT_PUMP = 0
HWHP_WMOD_BOOST = 2
HWHP_OPERATION_HEAT_PUMP = "heat_pump"  # Normal heat pump operation
HWHP_OPERATION_BOOST = "performance"  # Boost / turbo operation

# Energy metering (AC units).
# ElcAll is a cumulative counter in tenths of a kWh; it does not reset daily.
# ElcAllConsumption carries the same value and is not read separately.
PROP_ENERGY_TOTAL = "ElcAll"
ENERGY_SCALE = 0.1

# Compressor frequency in Hz. Reads 0 while the unit is idle and non-zero while
# it is actually running, so it tracks load far more responsively than the
# energy counter, which only moves in whole 0.1 kWh steps.
PROP_COMPRESSOR_FREQ = "CompressorFqy"

# Relative humidity. Already part of the standard Props enum (HUM_SENSOR), so
# it needs no extra request - only an entity to surface it.
PROP_HUMIDITY = "DwatSen"

# Compressor power limit ("power reduce" in the Gree+ app: an on/off switch
# followed by a level, shown as A1 / A2). PowReduceGear is the level, 0 = off.
# PowReduceType is non-zero on units that offer the feature; units without it
# report 0 or omit the key, so it gates the entity (issue #43).
PROP_POWER_REDUCE_GEAR = "PowReduceGear"
PROP_POWER_REDUCE_TYPE = "PowReduceType"

# Room temperature on commercial indoor units, which leave TemSen empty. Same
# +40 offset; the library uses it in place of a missing TemSen (#6, #33).
PROP_ROOM_TEMP = "InTem"
POWER_LIMIT_OFF = "off"
# Gear values captured from a V3.2.M split unit while toggling the Gree+ app
# through Off / A1 / A2 (#43): the levels are 0, 2 and 4, not 0, 1, 2 --
# writing 1 or 2 made the app show A1 either way.
POWER_LIMIT_LEVELS = {POWER_LIMIT_OFF: 0, "a1": 2, "a2": 4}

# Gree swimming-pool heat pumps (cloud model id 9302, e.g. GRS-CP11Pd/NbA-K),
# mapped from live captures in #48. Temperatures use a +100 offset with a
# separate tenths key: InTemInt 120 / InTemDec 5 -> 20.5 C. Every command the
# Gree+ app sends to these units carries FlagPool=1.
POOL_MODEL_ID = "9302"
POOL_PROP_FLAG = "FlagPool"
POOL_PROP_FUNC = "PoolFunc"
POOL_PROP_WMOD = "Wmod"  # 0 = heat, 1 = cool, 2 = auto
POOL_PROP_SET_TEM_INT = "SetTemInt"
POOL_PROP_SET_TEM_DEC = "SetTemDec"  # 0 or 5 (tenths)
POOL_PROP_IN_TEM_INT = "InTemInt"  # water inlet, +100
POOL_PROP_IN_TEM_DEC = "InTemDec"
POOL_PROP_OUT_TEM_INT = "OutTemInt"  # water outlet, +100
POOL_PROP_OUT_TEM_DEC = "OutTemDec"
POOL_PROP_HEAT_TEM_MIN = "HeatTemMin"  # setpoint limits, +100
POOL_PROP_HEAT_TEM_MAX = "HeatTemMax"
POOL_PROP_COOL_TEM_MIN = "CoolTemMin"
POOL_PROP_COOL_TEM_MAX = "CoolTemMax"
POOL_PROP_PUMP_STATUS = "PumpStatus"
POOL_PROP_COMPRESSOR_STATUS = "ComStatus"
POOL_PROP_DEFROST = "Defrost"
POOL_PROP_AUX_STATUS = "AuxStatus"
POOL_PROP_ERROR = "AllErr"
POOL_TEMP_OFFSET = 100
# Gree+ "Function" menu (PoolFunc), independent of Wmod: 0 Smart, 1 Fast, 2 ECO.
POOL_FUNCTIONS = {"smart": 0, "fast": 1, "eco": 2}
POOL_WMOD_HEAT = 0
POOL_WMOD_COOL = 1
POOL_WMOD_AUTO = 2
# Fallbacks when the unit does not report its limits.
POOL_TEMP_MIN_DEFAULT = 10
POOL_TEMP_MAX_DEFAULT = 40

# Gree Cloud servers. "Latin American" was removed in 1.7.0: its hosts never
# existed and Gree's own region directory (globalgrih.gree.com) has no such
# region -- Latin America is served by the South American hosts (#34).
# Entries created with the old name keep working through this alias.
REGION_ALIASES = {"Latin American": "South American"}
GREE_CLOUD_SERVERS = {
    "Australia": "https://augrih.gree.com",
    "China Mainland": "https://grih.gree.com",
    "East South Asia": "https://hkgrih.gree.com",
    "Europe": "https://eugrih.gree.com",
    "India": "https://ingrih.gree.com",
    "Middle East": "https://megrih.gree.com",
    "North American": "https://nagrih.gree.com",
    "Russia": "https://rugrih.gree.com",
    "South American": "https://sagrih.gree.com",
}

# Gree MQTT servers (one per region, must match the REST API region)
GREE_MQTT_SERVERS = {
    "Australia": "mqtt-au.gree.com",
    "China Mainland": "mqtt.gree.com",
    "East South Asia": "mqtt-hk.gree.com",
    "Europe": "mqtt-eu.gree.com",
    "India": "mqtt-in.gree.com",
    "Middle East": "mqtt-me.gree.com",
    "North American": "mqtt-na.gree.com",
    "Russia": "mqtt-ru.gree.com",
    "South American": "mqtt-sa.gree.com",
}
