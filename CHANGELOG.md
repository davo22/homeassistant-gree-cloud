# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-01

### Added
- Initial release of Gree Climate Cloud integration
- Support for cloud-only Gree devices via MQTT
- Full climate entity with all HVAC modes
- Preset modes: Eco, Away, Boost, Sleep
- Fan speed control with 6 levels
- Swing mode control (vertical, horizontal, both)
- Switch entities: Panel Light, Quiet, Fresh Air, XFan, Health Mode
- Multi-region cloud server support
- Config flow for easy setup
- HACS compatibility

### Technical Details
- Based on forked greeclimate library with cloud support
- Uses Gree Cloud MQTT broker for device communication
- Supports both CipherV1 and CipherV2 encryption
- 60-second polling interval for state updates
