# Gree Climate Cloud - Home Assistant Integration

Custom integration for Home Assistant that adds support for **cloud-only Gree devices** via the Gree+ app and cloud MQTT broker.

This integration is based on a fork of the [greeclimate](https://github.com/cmroche/greeclimate) library with added cloud support.

## Features

- 🌐 **Cloud-only device support** - Works with Gree devices that only communicate via cloud
- 🔄 **Full climate control** - Temperature, mode, fan speed, swing modes
- 🎛️ **Additional switches** - Panel light, quiet mode, fresh air, XFan, health mode
- 🔐 **Secure authentication** - Uses your existing Gree+ account credentials
- 🌍 **Multi-region support** - Works with all Gree Cloud regions

## Supported Devices

Any Gree Smart device working with the Gree+ app should be supported, including non-Gree branded devices such as:

- Trane
- Innova
- Cooper & Hunter
- Proklima
- Tadiran
- Heiwa
- Ekokai
- Lessar
- Tosot
- Wilfa

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/dawidrashid/homeassistant-gree-cloud`
6. Select category: "Integration"
7. Click "Add"
8. Search for "Gree Climate Cloud" and install
9. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/gree_cloud` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Gree Climate Cloud"
4. Select your server region (e.g., Europe, North American, etc.)
5. Enter your Gree+ account credentials (username/email and password)
6. Click **Submit**

The integration will automatically discover all devices associated with your Gree+ account.

## Available Entities

### Climate Entity

Each device creates a climate entity with the following features:

- **HVAC Modes**: Off, Auto, Cool, Heat, Dry, Fan Only
- **Preset Modes**: None, Eco, Away (8°C mode), Boost (Turbo), Sleep
- **Fan Modes**: Auto, Low, Medium Low, Medium, Medium High, High
- **Swing Modes**: Off, Vertical, Horizontal, Both
- **Temperature Control**: Target temperature with 1° step

### Switch Entities

Each device also creates the following switches:

- **Panel Light**: Control the front panel LED
- **Quiet Mode**: Enable/disable quiet operation
- **Fresh Air**: Enable/disable fresh air intake
- **XFan**: Enable/disable extra fan mode (helps dry coils)
- **Health Mode**: Enable/disable anion/health mode (disabled by default)

## Cloud Regions

Select the appropriate region for your account:

- Europe
- East South Asia
- North American
- South American
- China Mainland
- India
- Middle East
- Australia
- Russian server

## Known Limitations

- **Cloud polling**: The integration polls the cloud every 60 seconds for state updates. Local changes may take up to a minute to reflect in Home Assistant.
- **Internet required**: Devices must be connected to the internet and the Gree Cloud for this integration to work.
- **No local control**: This integration does not support local UDP communication. For local-only devices, use the official Gree integration.

## Troubleshooting

### Login Failed

- Verify your Gree+ credentials are correct
- Ensure you selected the correct server region
- Check that your account has devices registered in the Gree+ app

### Devices Not Discovered

- Ensure devices are online in the Gree+ app
- Try reloading the integration
- Check Home Assistant logs for error messages

### Enable Debug Logging

Add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.gree_cloud: debug
    greeclimate: debug
```

## Credits

- Original [greeclimate](https://github.com/cmroche/greeclimate) library by @cmroche
- Cloud API implementation based on [gree-api-client](https://github.com/luc10/gree-api-client)
- Official Home Assistant [Gree integration](https://www.home-assistant.io/integrations/gree/)

## License

MIT License - see LICENSE file for details
