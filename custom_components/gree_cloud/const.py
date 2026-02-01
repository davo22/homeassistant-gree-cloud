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

# Temperature settings
TARGET_TEMPERATURE_STEP = 1

# Gree Cloud servers
GREE_CLOUD_SERVERS = {
    "Europe": "https://eugrih.gree.com",
    "East South Asia": "https://hkgrih.gree.com",
    "North American": "https://nagrih.gree.com",
    "South American": "https://sagrih.gree.com",
    "China Mainland": "https://grih.gree.com",
    "India": "https://ingrih.gree.com",
    "Middle East": "https://megrih.gree.com",
    "Australia": "https://augrih.gree.com",
    "Russian server": "https://rugrih.gree.com",
}
