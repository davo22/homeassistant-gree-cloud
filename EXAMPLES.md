# Example Automations

This file contains example Home Assistant automations using the Gree Climate Cloud integration.

## Turn on AC when arriving home

```yaml
automation:
  - alias: "Turn on AC when arriving home"
    trigger:
      - platform: state
        entity_id: person.your_name
        to: "home"
    condition:
      - condition: numeric_state
        entity_id: sensor.outdoor_temperature
        above: 25
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.living_room_ac
        data:
          hvac_mode: cool
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          temperature: 22
```

## Turn off AC when leaving home

```yaml
automation:
  - alias: "Turn off AC when leaving home"
    trigger:
      - platform: state
        entity_id: person.your_name
        to: "not_home"
        for:
          minutes: 10
    action:
      - service: climate.turn_off
        target:
          entity_id: climate.living_room_ac
```

## Enable Eco mode at night

```yaml
automation:
  - alias: "Enable AC Eco mode at night"
    trigger:
      - platform: time
        at: "22:00:00"
    condition:
      - condition: state
        entity_id: climate.bedroom_ac
        state: "cool"
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.bedroom_ac
        data:
          preset_mode: eco
      - service: switch.turn_on
        target:
          entity_id: switch.bedroom_ac_quiet
```

## Adjust temperature based on outdoor temperature

```yaml
automation:
  - alias: "Adjust AC temperature based on outdoor temp"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        above: 30
    condition:
      - condition: state
        entity_id: climate.living_room_ac
        state: "cool"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          temperature: 20
  
  - alias: "Adjust AC temperature when outdoor temp drops"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        below: 28
    condition:
      - condition: state
        entity_id: climate.living_room_ac
        state: "cool"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          temperature: 24
```

## Turn on heating when temperature drops

```yaml
automation:
  - alias: "Turn on heating when cold"
    trigger:
      - platform: numeric_state
        entity_id: sensor.living_room_temperature
        below: 18
    condition:
      - condition: time
        after: "06:00:00"
        before: "23:00:00"
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.living_room_ac
        data:
          hvac_mode: heat
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          temperature: 22
```

## Notification when AC has been on for too long

```yaml
automation:
  - alias: "Notify if AC on for 8 hours"
    trigger:
      - platform: state
        entity_id: climate.living_room_ac
        to: "cool"
        for:
          hours: 8
    action:
      - service: notify.mobile_app
        data:
          title: "AC Running Long Time"
          message: "Living room AC has been running for 8 hours"
```

## Enable Sleep mode at bedtime

```yaml
automation:
  - alias: "Enable AC Sleep mode at bedtime"
    trigger:
      - platform: time
        at: "23:00:00"
    condition:
      - condition: state
        entity_id: climate.bedroom_ac
        state: "cool"
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.bedroom_ac
        data:
          preset_mode: sleep
      - service: switch.turn_on
        target:
          entity_id: switch.bedroom_ac_quiet
      - service: switch.turn_off
        target:
          entity_id: switch.bedroom_ac_panel_light
```

## Dashboard Card Example

```yaml
type: thermostat
entity: climate.living_room_ac
features:
  - type: climate-hvac-modes
    hvac_modes:
      - auto
      - cool
      - heat
      - dry
      - fan_only
      - "off"
  - type: climate-preset-modes
    preset_modes:
      - none
      - eco
      - away
      - boost
      - sleep
```

## Advanced: Create comfort scenes

```yaml
# Scenes
scene:
  - name: "AC Cool Comfort"
    entities:
      climate.living_room_ac:
        hvac_mode: cool
        temperature: 22
        fan_mode: auto
        swing_mode: vertical
        preset_mode: none
      switch.living_room_ac_quiet:
        state: off
      switch.living_room_ac_panel_light:
        state: on

  - name: "AC Night Mode"
    entities:
      climate.bedroom_ac:
        hvac_mode: cool
        temperature: 24
        fan_mode: low
        swing_mode: "off"
        preset_mode: sleep
      switch.bedroom_ac_quiet:
        state: on
      switch.bedroom_ac_panel_light:
        state: off

  - name: "AC Turbo Cool"
    entities:
      climate.living_room_ac:
        hvac_mode: cool
        temperature: 20
        fan_mode: high
        swing_mode: both
        preset_mode: boost
```

## Template Sensor: Calculate daily runtime

```yaml
sensor:
  - platform: history_stats
    name: AC Runtime Today
    entity_id: climate.living_room_ac
    state: "cool"
    type: time
    start: "{{ now().replace(hour=0, minute=0, second=0) }}"
    end: "{{ now() }}"
```

## Input Select for Quick Mode Selection

```yaml
input_select:
  ac_mode:
    name: AC Mode
    options:
      - "Off"
      - "Comfort"
      - "Eco"
      - "Turbo"
      - "Sleep"
    initial: "Off"
    icon: mdi:air-conditioner

automation:
  - alias: "AC Mode Selection"
    trigger:
      - platform: state
        entity_id: input_select.ac_mode
    action:
      - choose:
          - conditions:
              - condition: state
                entity_id: input_select.ac_mode
                state: "Off"
            sequence:
              - service: climate.turn_off
                target:
                  entity_id: climate.living_room_ac
          
          - conditions:
              - condition: state
                entity_id: input_select.ac_mode
                state: "Comfort"
            sequence:
              - service: scene.turn_on
                target:
                  entity_id: scene.ac_cool_comfort
          
          - conditions:
              - condition: state
                entity_id: input_select.ac_mode
                state: "Eco"
            sequence:
              - service: climate.set_hvac_mode
                target:
                  entity_id: climate.living_room_ac
                data:
                  hvac_mode: cool
              - service: climate.set_preset_mode
                target:
                  entity_id: climate.living_room_ac
                data:
                  preset_mode: eco
          
          - conditions:
              - condition: state
                entity_id: input_select.ac_mode
                state: "Turbo"
            sequence:
              - service: scene.turn_on
                target:
                  entity_id: scene.ac_turbo_cool
          
          - conditions:
              - condition: state
                entity_id: input_select.ac_mode
                state: "Sleep"
            sequence:
              - service: scene.turn_on
                target:
                  entity_id: scene.ac_night_mode
```
