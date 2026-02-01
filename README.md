# Gree Climate Cloud - Home Assistant Integration

Custom integration for Home Assistant that adds support for **cloud-only Gree devices** via the Gree+ app and cloud MQTT broker.

This integration is based on a fork of the [greeclimate](https://github.com/cmroche/greeclimate) library with added cloud support.

> **🚀 Quick Start**: New to this integration? Check out the [Quick Start Guide](QUICKSTART.md) to get up and running in 5 minutes!

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

### Commands Not Working

- Check if device is online in Gree+ app
- Verify internet connectivity
- Look for timeout errors in logs
- Try reloading the integration

### State Updates Delayed

- This is normal - cloud polling occurs every 60 seconds
- For immediate feedback, check the Gree+ app
- Consider using local integration for local devices

### Enable Debug Logging

Add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.gree_cloud: debug
    greeclimate: debug
```

## FAQ

### Q: What's the difference between this and the official Gree integration?

**A:** The official integration only works with devices that support local UDP communication. This cloud integration works with **cloud-only devices** that can only be controlled via the Gree Cloud MQTT broker. If your device works with the official integration, use that instead for better responsiveness.

### Q: Can I use both integrations at the same time?

**A:** Yes! You can use both integrations simultaneously. Use the official integration for local devices and this cloud integration for cloud-only devices.

### Q: How often does the integration update device state?

**A:** The integration polls the cloud every 60 seconds. Changes made in the Gree+ app or locally on the device will be reflected in Home Assistant within 1 minute.

### Q: Does this work offline?

**A:** No, this integration requires an active internet connection to communicate with the Gree Cloud servers.

### Q: Which cipher version should I use?

**A:** Currently, the integration defaults to CipherV1 (AES-128-ECB) which works with most devices. CipherV2 support is implemented but not yet exposed in the UI.

### Q: My device shows as unavailable

**A:** This can happen if:
- The device is offline or not connected to WiFi
- Your internet connection is unstable
- The Gree Cloud servers are experiencing issues
- The device was removed from your Gree+ account

Try power-cycling the device and ensuring it's connected in the Gree+ app.

### Q: Can I control multiple devices?

**A:** Yes! The integration automatically discovers all devices associated with your Gree+ account across all homes.

### Q: Does this support Fahrenheit?

**A:** Yes, the integration detects the temperature unit set on your device and displays temperatures accordingly.

## Credits

- Original [greeclimate](https://github.com/cmroche/greeclimate) library by @cmroche
- Cloud API implementation based on [gree-api-client](https://github.com/luc10/gree-api-client)
- Official Home Assistant [Gree integration](https://www.home-assistant.io/integrations/gree/)

## License

MIT License - see LICENSE file for details
