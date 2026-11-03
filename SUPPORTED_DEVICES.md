# Supported devices


Anything that works in the **Gree+** app (also sold as *EWPE Smart*) can be discovered. What you get, and whether it works today, depends on the device class and on the Wi-Fi module's protocol version — both are visible in the debug log at startup:

```
CloudDevice initialized: Living room (parent: 9424b8b368bd, child: 7b65b424500000, ver: V1.1.0.0, transport: mqtt)
Device version is 1.45, hid 362001065279+U-WB05RT13V1.45.bin
```

## Device classes

| Class | How it is recognised | Entities | Status |
|---|---|---|---|
| Split, wall, multi-split and ducted air conditioners / heat pumps | cloud `mid` 10001 and similar | climate, switches (panel light, quiet, fresh air, XFan, health, beeper), sensors (energy, humidity, compressor frequency), power-limit select | Supported |
| Commercial unit on its own Wi-Fi module (`Commercial AC…00`) | unit record with `pmac` = module (`mid` 6400 / module `mid` 60) | same as above | Supported (maintainer's own unit) |
| Several indoor units behind one module (multi-head, VRF; Gree+ shows `<unit>@<module>`) | several records with the same `pmac` (`mid` 6000) | one climate per indoor unit | 1.7.0 beta — addressing rewritten in 1.7.0, awaiting confirmation from [#6](https://github.com/davo22/homeassistant-gree-cloud/issues/6) and [#33](https://github.com/davo22/homeassistant-gree-cloud/issues/33) |
| Hot water heat pumps (Gree WHIO, Gree HWHP) | `WatTmp` reported (`mid` 910001) | water heater with operation modes, fill level | Supported |
| Swimming-pool heat pumps | `mid` 9302 | climate (heat / cool / auto, 0.5 °C setpoint), inlet/outlet sensors, pump/compressor/defrost binary sensors, function select | Supported since 1.7.0 ([#48](https://github.com/davo22/homeassistant-gree-cloud/issues/48)) |
| Air-to-water heat pumps (Gree Versati, Arthur Martin) | `mid` 9300 | heating climate, setpoints, water temperatures | In review ([#47](https://github.com/davo22/homeassistant-gree-cloud/pull/47)) — not released yet |

## Wi-Fi modules and protocol versions

| Protocol (`ver`) | Modules seen | Transport | Status |
|---|---|---|---|
| V3.2 and newer (`V3.2.M`, `V3.4.M`, `V3.5.M`) | U-WB05RT13 V1.45, U-WB04BRT13 V1.40, U-WB05_TG V1.14 / V1.20 | cloud MQTT broker | Supported. Some V3.x modules answer status requests with all zeros and only push real state on their own ([#30](https://github.com/davo22/homeassistant-gree-cloud/pull/30)); if your unit shows zeros, please report it. |
| Older than V3.2 (`V2.0.0`, `V1.2.1`, `V1.1.0.0`) | U-WB05RT13 V1.23, U-4MWB65AR11 V2.04 | legacy TLS gateway (since 1.6.0) | Supported — these modules never join the MQTT broker and were silent before 1.6.0 ([#21](https://github.com/davo22/homeassistant-gree-cloud/issues/21)) |

## Models reported working

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
