"""Constants for the Gree Climate Cloud integration."""

DOMAIN = "gree_cloud"

# Config flow constants
CONF_SERVER = "server"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Update intervals
UPDATE_INTERVAL = 60  # Cloud polling interval in seconds
DISCOVERY_TIMEOUT = 10

# Error thresholds
MAX_ERRORS = 3
MAX_EXPECTED_RESPONSE_TIME_INTERVAL = 180

# Dispatcher signals
DISPATCH_DEVICE_DISCOVERED = f"{DOMAIN}_device_discovered"

# Fan modes (matching official integration)
FAN_MEDIUM_LOW = "medium low"
FAN_MEDIUM_HIGH = "medium high"

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

# Compressor temperature in degrees C. Observed values around 58-59 C while
# running; not part of the standard Props enum, so it must be requested
# explicitly (see _SENSOR_EXTRA_PROPS in coordinator.py).
PROP_COMPRESSOR_TEMP = "CompressorTem"

# Relative humidity. Already part of the standard Props enum (HUM_SENSOR), so
# it needs no extra request - only an entity to surface it.
PROP_HUMIDITY = "DwatSen"

# Target humidity (Cool/Dry mode only). Backed by Props.HUM_SET ("Dwet"),
# already exposed by greeclimate as Device.target_humidity, encoding
# humidity% / 5 - 3. Confirmed against real Clivia V3.2.M MQTT traffic in
# BOTH modes (45% -> Dwet 6 in Cool, and in Dry). Only the Cool bounds were
# captured end-to-end (40-80%); the Dry bounds below are ASSUMED from the
# Gree spec sheet and have NOT been verified on real hardware.
HUMIDITY_MIN_COOL = 40
HUMIDITY_MAX_COOL = 80
HUMIDITY_MIN_DRY = 30  # ASSUMED - not verified on real hardware
HUMIDITY_MAX_DRY = 70  # ASSUMED - not verified on real hardware
HUMIDITY_STEP = 5

# Dehumidify mode ("Dmod", part of the standard Props enum but exposed by
# greeclimate as a read-only property - no setter - so it is driven directly
# through raw_properties, the same pattern as the HWHP properties above).
# Holds a single value at a time; verified identical in both Cool and Dry
# mode against real Clivia V3.2.M MQTT traffic:
#   15 = off (plain cooling/drying, no dehumidification)
#   0  = dehumidify (cooling/drying + dehumidify; also implied by setting a
#        target humidity, see climate.py)
#   2  = smart dehumidify ("Smart Drying")
# Exposed as two independent switches (see switch.py) that both just read
# back whichever value Dmod currently holds, rather than fighting each
# other over it.
PROP_DEHUMIDIFY_MODE = "Dmod"
DEHUMIDIFY_MODE_OFF = 15
DEHUMIDIFY_MODE_ON = 0
DEHUMIDIFY_MODE_SMART = 2

# Gree Cloud servers
GREE_CLOUD_SERVERS = {
    "Australia": "https://augrih.gree.com",
    "China Mainland": "https://grih.gree.com",
    "East South Asia": "https://hkgrih.gree.com",
    "Europe": "https://eugrih.gree.com",
    "India": "https://ingrih.gree.com",
    "Latin American": 'https://lagrih.gree.com',
    "Middle East": "https://megrih.gree.com",
    "North American": "https://nagrih.gree.com",
    "Russia": "https://rugrih.gree.com",
    "South American": "https://sagrih.gree.com",
}

# Gree MQTT servers (one per region, must match the REST API region)
GREE_MQTT_SERVERS = {
    "Australia": "mqtt-au.gree.com",
    "China Mainland": "mqtt.gree.com",
    "East South Asia": "mqtt-as.gree.com",
    "Europe": "mqtt-eu.gree.com",
    "India": "mqtt-in.gree.com",
    "Latin American": "mqtt-la.gree.com",
    "Middle East": "mqtt-me.gree.com",
    "North American": "mqtt-na.gree.com",
    "Russia": "mqtt-ru.gree.com",
    "South American": "mqtt-sa.gree.com",
}
