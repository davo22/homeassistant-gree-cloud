# Gree Climate Cloud - Home Assistant Integration

Custom integration for Home Assistant that adds support for **cloud-only Gree devices** via the Gree+ app and cloud MQTT broker.

This integration is based on a fork of the [greeclimate](https://github.com/cmroche/greeclimate) library with added cloud support.

> **🚀 Quick Start**: New to this integration? Check out the [Quick Start Guide](QUICKSTART.md) to get up and running in 5 minutes!

## Features

- 🌐 **Cloud-only device support** - Works with Gree devices that only communicate via cloud
- 🔄 **Full climate control** - Temperature, mode, fan speed, swing modes
- �️ **Hot water heat pump support** - Control Gree WHIO / Hot Water Heat Pump devices
- 🎛️ **Additional switches** - Panel light, quiet mode, fresh air, XFan, health mode (AC/heat pump devices)
- 🔐 **Secure authentication** - Uses your existing Gree+ account credentials
- 🌍 **Multi-region support** - Works with all Gree Cloud regions

## Supported Devices

Anything that works in the **Gree+** app (also sold as *EWPE Smart*) can be discovered. What you get, and whether it works today, depends on the device class and on the Wi-Fi module's protocol version — both are visible in the debug log at startup:

```
CloudDevice initialized: Living room (parent: 9424b8b368bd, child: 7b65b424500000, ver: V1.1.0.0, transport: mqtt)
Device version is 1.45, hid 362001065279+U-WB05RT13V1.45.bin
```

### Device classes

| Class | How it is recognised | Entities | Status |
|---|---|---|---|
| Split, wall, multi-split and ducted air conditioners / heat pumps | cloud `mid` 10001 and similar | climate, switches (panel light, quiet, fresh air, XFan, health, beeper), sensors (energy, humidity, compressor frequency), power-limit select | Supported |
| Commercial unit on its own Wi-Fi module (`Commercial AC…00`) | unit record with `pmac` = module (`mid` 6400 / module `mid` 60) | same as above | Supported (maintainer's own unit) |
| Several indoor units behind one module (multi-head, VRF; Gree+ shows `<unit>@<module>`) | several records with the same `pmac` (`mid` 6000) | one climate per indoor unit | 1.7.0 beta — addressing rewritten in 1.7.0, awaiting confirmation from [#6](https://github.com/davo22/homeassistant-gree-cloud/issues/6) and [#33](https://github.com/davo22/homeassistant-gree-cloud/issues/33) |
| Hot water heat pumps (Gree WHIO, Gree HWHP) | `WatTmp` reported (`mid` 910001) | water heater with operation modes, fill level | Supported |
| Swimming-pool heat pumps | `mid` 9302 | climate (heat / cool / auto, 0.5 °C setpoint), inlet/outlet sensors, pump/compressor/defrost binary sensors, function select | Supported since 1.7.0 ([#48](https://github.com/davo22/homeassistant-gree-cloud/issues/48)) |
| Air-to-water heat pumps (Gree Versati, Arthur Martin) | `mid` 9300 | heating climate, setpoints, water temperatures | In review ([#47](https://github.com/davo22/homeassistant-gree-cloud/pull/47)) — not released yet |

### Wi-Fi modules and protocol versions

| Protocol (`ver`) | Modules seen | Transport | Status |
|---|---|---|---|
| V3.2 and newer (`V3.2.M`, `V3.4.M`, `V3.5.M`) | U-WB05RT13 V1.45, U-WB04BRT13 V1.40, U-WB05_TG V1.14 / V1.20 | cloud MQTT broker | Supported. Some V3.x modules answer status requests with all zeros and only push real state on their own ([#30](https://github.com/davo22/homeassistant-gree-cloud/pull/30)); if your unit shows zeros, please report it. |
| Older than V3.2 (`V2.0.0`, `V1.2.1`, `V1.1.0.0`) | U-WB05RT13 V1.23, U-4MWB65AR11 V2.04 | legacy TLS gateway (since 1.6.0) | Supported — these modules never join the MQTT broker and were silent before 1.6.0 ([#21](https://github.com/davo22/homeassistant-gree-cloud/issues/21)) |

### Models reported working

Collected from issues and pull requests; the last column is where to look for details.

| Model | Type | Module / firmware | Region | Source |
|---|---|---|---|---|
| Gree split (U-WB05RT13 V1.45, `V3.4.M`) | wall split | U-WB05RT13 V1.45 | Europe, Australia | maintainer, [#50](https://github.com/davo22/homeassistant-gree-cloud/issues/50) |
| Gree Commercial AC, single head (`V3.2.M`) | commercial module | U-WB04BRT13 V1.40 | Europe | maintainer |
| Gree Clivia R32 | wall split | V2.04 | North America | [#14](https://github.com/davo22/homeassistant-gree-cloud/issues/14) |
| Gree Clivia R22 | wall split | U-4MWB65AR11 V2.04 | — | [#17](https://github.com/davo22/homeassistant-gree-cloud/pull/17) |
| Gree Clivia (`V3.2.M`) | wall split | — | — | [#28](https://github.com/davo22/homeassistant-gree-cloud/pull/28) (humidity, outdoor temperature, silent mode in review) |
| Gree Livo R32 | wall split, built-in Wi-Fi | V2.10 | North America | [#41](https://github.com/davo22/homeassistant-gree-cloud/issues/41) |
| Gree AC213a | wall split | V20.8 / Wi-Fi V2.10 | — | [#28](https://github.com/davo22/homeassistant-gree-cloud/pull/28) (comment) |
| Heiwa Yoko3 (Gree rebrand) | wall split | Wi-Fi V2.12 | Europe | [#19](https://github.com/davo22/homeassistant-gree-cloud/issues/19) |
| Tosot | wall split | — | North America | [#9](https://github.com/davo22/homeassistant-gree-cloud/issues/9) |
| Sinclair ducted with SWC-05W wired controller | ducted, commercial | V1.39, `mid` 6400 | — | [#7](https://github.com/davo22/homeassistant-gree-cloud/issues/7) (0.5 °C steps) |
| Gree ducted with XE7C-24/HC wired controller | ducted, commercial | U-WB04BRT13 V1.39 | Australia | [#49](https://github.com/davo22/homeassistant-gree-cloud/issues/49) (needs 1.6.0) |
| Gree GUD35W1/NHA-S, GUD35PS1/A-S with XE7A-24/HC controllers | ducted, commercial | controller fw 1.38 works; fw 1.40 under investigation | Europe | [#44](https://github.com/davo22/homeassistant-gree-cloud/issues/44) |
| Gree units on `V2.0.0` modules (three) | wall split | U-WB05RT13 V1.23 | Europe | [#21](https://github.com/davo22/homeassistant-gree-cloud/issues/21) (gateway transport) |
| Gree ERS-AC24KWH-G, four indoor units | multi-head | `V1.1.0.0`, `mid` 6000 | Australia | [#6](https://github.com/davo22/homeassistant-gree-cloud/issues/6) (1.7.0 beta, pending) |
| Gree VRF, five indoor units | VRF | — | East South Asia | [#33](https://github.com/davo22/homeassistant-gree-cloud/issues/33) (1.7.0 beta, pending) |
| Gree WHIO 200 / 270 L | hot water heat pump | — | New Zealand | [#3](https://github.com/davo22/homeassistant-gree-cloud/issues/3) |
| Gree hot water heat pump | hot water heat pump | U-WB04BRT13, `mid` 910001 | Australia | [#40](https://github.com/davo22/homeassistant-gree-cloud/pull/40) |
| Gree GRS-CP11Pd/NbA-K | swimming-pool heat pump | V1.39, `mid` 9302 | Europe | [#48](https://github.com/davo22/homeassistant-gree-cloud/issues/48) |
| Gree Versati / Arthur Martin, model 9300 | air-to-water heat pump | — | Europe | [#47](https://github.com/davo22/homeassistant-gree-cloud/pull/47) (in review) |

Other brands built on Gree hardware and the Gree+ / EWPE Smart app — Trane, Innova, Cooper & Hunter, Proklima, Tadiran, Heiwa, Ekokai, Lessar, Tosot, Wilfa, Sinclair, Arthur Martin — are expected to work the same way as the Gree unit they are based on. If your model is not in the table and works (or does not), please open an issue with the two log lines above.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/davo22/homeassistant-gree-cloud`
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

### Options: external temperature sensor

Older ducted and central units expose no indoor temperature over the protocol and show the setpoint as the current temperature. Open the integration's **Configure** dialog, pick the unit and choose any temperature sensor (a Zigbee thermometer, a thermostat's reading, …); its value is then shown as the climate entity's current temperature and follows the sensor live. Leave the field empty to go back to the unit's own reading. The chosen sensor is exposed as the `external_temperature_sensor` attribute.

## Available Entities

### Air Conditioner / Heat Pump — Climate Entity

Created for standard Gree air conditioner and heat pump devices:

- **HVAC Modes**: Off, Auto, Cool, Heat, Dry, Fan Only
- **Preset Modes**: None, Eco, Away (8°C mode), Boost (Turbo), Sleep
- **Fan Modes**: Auto, Low, Medium Low, Medium, Medium High, High
- **Swing Modes**: Off, Vertical, Horizontal, Both
- **Temperature Control**: Target temperature with 1° step

### Hot Water Heat Pump — Water Heater Entity

Created for Gree WHIO / Hot Water Heat Pump devices (auto-detected):

- **Operation Modes**: Heat Pump (normal), Performance (boost), Off
- **Temperature Control**: Target temperature 40–80°C with 1° step
- **Current Temperature**: Live tank water temperature

### Swimming-Pool Heat Pump — Climate Entity

Created for Gree pool heat pumps (cloud model id `9302`, e.g. GRS-CP11Pd/NbA-K), auto-detected from the cloud record:

- **HVAC Modes**: Off, Heat, Cool, Auto (the unit's `Wmod`)
- **Target Temperature**: water setpoint in 0.5 °C steps, within the limits the unit reports (typically 15–40 °C heating, 10–40 °C cooling)
- **Current Temperature**: water inlet temperature; the outlet temperature, pump/compressor/defrost status and error code are attributes
- **Sensors**: water inlet and outlet temperature
- **Function select**: the Gree+ *Function* menu — Smart / Fast / ECO — independent of the operating mode
- **Binary sensors**: pump running, compressor running (both with the *running* device class, for operating-hour statistics) and defrosting

No air-conditioner switches or selects are created for these units. Protocol mapped in #48; reports from other pool models are welcome.

### Switch Entities

Created for air conditioner and heat pump devices only (not hot water heat pumps):

- **Panel Light**: Control the front panel LED
- **Quiet Mode**: Enable/disable quiet operation
- **Fresh Air**: Enable/disable fresh air intake
- **XFan**: Enable/disable extra fan mode (helps dry coils)
- **Health Mode**: Enable/disable anion/health mode (disabled by default)
- **Beeper**: whether the unit beeps when it receives a command from Home Assistant. Off adds `Buzzer_ON_OFF=1` to every command; the setting lives in Home Assistant (the unit does not report it) and survives restarts. Found under the device's configuration section.

### Select Entities

- **Power limit**: compressor power limit, the "power reduce" setting of the Gree+ app (Off / A1 / A2). Only created for units that report the feature (`PowReduceType` non-zero).

## Cloud Regions

Select the appropriate region for your account:

- Australia
- China Mainland
- East South Asia
- Europe
- India
- Middle East
- North American
- Russia
- South American (also serves Latin America)

## How devices are reached

The Gree cloud has two ways of talking to a Wi-Fi module, and the integration picks one per device from the module's protocol version (the `ver` field of its cloud record, visible in the debug log at startup):

| Module protocol | Transport | Notes |
|---|---|---|
| `V3.2` and newer | MQTT broker (`mqtt-<region>.gree.com`) | Same path the Gree+ app uses for current firmware. |
| older (`V2.x`, `V1.x`) | Legacy TLS gateway | These modules never join the MQTT broker. The integration asks the cloud which gateway the device is attached to (`QueryOnline`) and sends each request over a short TLS connection, exactly like the app does. |

If a device that works in Gree+ never answers in Home Assistant (`Timeout waiting for state update` on every poll), check its `ver` in the debug log and open an issue with it.

## Known Limitations

- **Cloud polling**: The integration polls the cloud every 60 seconds for state updates. Local changes may take up to a minute to reflect in Home Assistant.
- **Internet required**: Devices must be connected to the internet and the Gree Cloud for this integration to work.
- **No local control**: This integration does not support local UDP communication. For local-only devices, use the official Gree integration.
- **Offline detection is poll-based**: a device that stops answering is marked unavailable after three failed polls (about three minutes), not instantly.

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
    greeclimate_davo22: debug
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

**A:** The device did not answer three status polls in a row. This can happen if:

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
