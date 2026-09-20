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

# Compressor and outdoor temperature. Neither is part of the standard Props
# enum, so both must be requested explicitly (see _SENSOR_EXTRA_PROPS in
# coordinator.py). Verified on a real Clivia V3.2.M with the device set to
# Celsius (HA showed indoor temp correctly in C): these raw keys still
# report Fahrenheit regardless of the TemUn setting - unlike TemSen (indoor
# temperature), which greeclimate already normalizes to the display unit.
# They therefore need an unconditional F->C conversion; see
# _fahrenheit_to_celsius in sensor.py.
PROP_COMPRESSOR_TEMP = "CompressorTem"
PROP_OUTDOOR_TEMP = "OutEnvTem"

# Panel light auto-sense. Not part of the standard Props enum, so it must be
# requested explicitly (see _LIGHT_EXTRA_PROPS in coordinator.py). Combined
# with Props.LIGHT ("Lig"), the panel light actually has three states,
# verified on real hardware:
#   Lig=0            -> off
#   Lig=1, LigSen=1  -> on (manual, full brightness)
#   Lig=1, LigSen=0  -> auto (adjusts to ambient light)
PROP_LIGHT_SENSOR = "LigSen"

PANEL_LIGHT_ON = "on"
PANEL_LIGHT_AUTO = "auto"
PANEL_LIGHT_OFF = "off"

# Buzzer (command confirmation beep) control. Not part of the standard Props
# enum, so it must be requested explicitly (see _SOUND_EXTRA_PROPS in
# coordinator.py). Has no setter in greeclimate - driven directly through
# raw_properties, the same pattern as Dmod/LigSen.
PROP_BUZZER_CTRL = "BuzzerCtrl"  # 1 = beep ON (normal), 0 = beep OFF (silent)

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
# Holds a single value at a time; verified on a real Clivia V3.2.M:
#   15 = off (plain cooling/drying, no dehumidification)
#   0  = target-based dehumidify (uses Dwet; also implied by setting a
#        target humidity, see climate.py) - available in Cool and Dry
#   1  = continuous dehumidify, no target ("Continuous Dry") - Dry only
#   2  = smart dehumidify ("Smart Drying") - Cool only
# Exposed as three independent switches plus the climate target humidity
# (see switch.py and climate.py) that each just read back whichever value
# Dmod currently holds, rather than fighting each other over it. Mode
# gating is enforced only through each entity's `available` property -
# nothing here forces Dmod, the fan, or any other control when the HVAC
# mode changes; the device manages that on its own.
PROP_DEHUMIDIFY_MODE = "Dmod"
DEHUMIDIFY_MODE_OFF = 15
DEHUMIDIFY_MODE_ON = 0
DEHUMIDIFY_MODE_CONTINUOUS = 1
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
