# Development Guide

## Setup Development Environment

### Prerequisites

- Home Assistant Core (2024.1.0 or later)
- Python 3.11 or later
- Git

### Local Development Setup

1. Clone this repository:
```bash
git clone https://github.com/davo22/homeassistant-gree-cloud.git
cd homeassistant-gree-cloud
```

2. Create a symbolic link to your Home Assistant custom_components directory:
```bash
ln -s $(pwd)/custom_components/gree_cloud /path/to/your/homeassistant/config/custom_components/gree_cloud
```

3. Restart Home Assistant

### Testing

To test the integration:

1. Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.gree_cloud: debug
    greeclimate: debug
```

2. Check logs in Home Assistant:
   - Go to **Settings** → **System** → **Logs**
   - Or check `home-assistant.log` file

### Code Structure

```
custom_components/gree_cloud/
├── __init__.py           # Integration setup and entry point
├── manifest.json         # Integration metadata
├── config_flow.py        # Configuration UI flow
├── const.py             # Constants and configuration
├── coordinator.py       # Data update coordinator and cloud discovery
├── entity.py            # Base entity class
├── climate.py           # Climate entity implementation
├── switch.py            # Switch entities implementation
├── strings.json         # UI strings (English)
├── icons.json           # Entity icons
└── translations/
    └── en.json          # Translations (English)
```

### Key Components

#### Cloud API Flow

1. User enters credentials in config flow
2. `GreeCloudApi` authenticates with Gree Cloud server
3. API retrieves list of devices with encryption keys
4. `GreeMqttClient` connects to Gree MQTT broker
5. `CloudDevice` instances created for each device
6. Coordinators manage state updates via MQTT

#### Device Communication

- **State Updates**: Poll cloud every 60 seconds via MQTT status request
- **Commands**: Send via MQTT with sequential command execution
- **Encryption**: AES-128-ECB (CipherV1) or AES-128-GCM (CipherV2)

### Debugging Common Issues

#### Authentication Failed
- Verify credentials are correct
- Check server region matches account
- Look for error messages in logs

#### Devices Not Discovered
- Ensure devices are online in Gree+ app
- Check MQTT connection in logs
- Verify device keys are retrieved from API

#### State Not Updating
- Check coordinator update interval
- Look for timeout errors in logs
- Verify MQTT messages are being received

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Code Style

- Follow PEP 8
- Use type hints
- Add docstrings to functions and classes
- Keep lines under 88 characters (Black formatter)

### Dependencies

The integration depends on the forked `greeclimate` library:
- Repository: https://github.com/davo22/greeclimate
- Branch: master

To update the library, modify the `requirements` field in `manifest.json`.
