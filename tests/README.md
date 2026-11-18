# Tests

The real integration and the real `greeclimate-davo22` library run inside Home
Assistant's test harness against a fake Gree cloud. Nothing is mocked inside
the integration, so a test sees what a user would see: entities and their
states on one side, the packets a unit receives on the other.

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest -q                       # everything, as CI does
.venv/bin/python -m pytest tests/test_pool.py -q    # one file
.venv/bin/python -m pytest -q --cov=custom_components.gree_cloud --cov-report=term-missing
```

## Layout

| File | What it pins |
| --- | --- |
| `fake_cloud.py` | The fake cloud: login, device list, MQTT broker, gateway, and `FakeUnit` with the manners of a real unit |
| `fixtures/*.json` | Recorded devices: account record, reported state, manners |
| `conftest.py`, `common.py` | Fixtures (`cloud`, `setup_integration`, `poll`, `settle`) and helpers |
| `test_devices.py` | Entities, unique ids and states of every recorded device (snapshots) |
| `test_status_requests.py` | The columns each device is asked for, the 40-column limit (snapshots) |
| `test_air_conditioner.py` | Service call → command, for air conditioners |
| `test_water_heater.py`, `test_pool.py`, `test_versati.py` | The same for heat pumps |
| `test_heatpump.py` | Decoding and write rules of `heatpump.py`, without Home Assistant |
| `test_config_flow.py`, `test_setup.py` | Account, options, setup, unload, packaging guards |
| `test_availability.py` | Missed polls, outages, reconnecting |

## Writing a test

```python
async def test_setting_the_temperature(hass, cloud, setup_integration, poll):
    unit = cloud.add("split_ac", state={"SetTem": 21})   # a fixture, adjusted
    await setup_integration()
    unit.forget()                                         # drop the setup traffic

    await call(hass, "climate", "set_temperature", "climate.living_room", temperature=24)

    assert unit.commands == [{"SetTem": 24, "TemRec": 0, "Add0.5": 0}]
    await poll()                                          # the next regular poll
    assert hass.states.get("climate.living_room").attributes["temperature"] == 24
```

A unit can be made to misbehave: `answers_status=False`, `acks_commands=False`,
`command_result=400`, `refuses={"Mod"}`, `max_columns=40`, `ignores_columns`,
`cloud.offline.add(unit.module_mac)`, `cloud.drop_connection()`. A unit that
reports by itself: `await cloud.push(unit, Pow=1)`.

## Adding a device

1. Take the state from a debug log of a real unit and write
   `fixtures/<name>.json` like the existing ones. Replace every identifier
   (MAC, key, names) with a synthetic one; do not invent properties.
2. Add it to the lists in `test_devices.py` and `test_status_requests.py`.
3. Run with `--snapshot-update`, then read the new snapshot: it is the list of
   entities a user with this device gets.

## Snapshots

`snapshots/*.ambr` are compared on every run. When one differs, the change in
the code changed what users see or what units are asked. Update it
(`--snapshot-update`) only when that is intended, and review the diff like code.

## Things that bite

- **Do not freeze the clock** (`freezer`): the library's timeouts then never
  expire and the test hangs. Use the `poll` fixture to move to the next poll.
- **Discovery runs in the background.** `setup_integration()` waits for it;
  after pushing a state use `await settle(hass, cloud)`.
- **One shared config entry.** `setup_integration()` sets up the Europe entry
  from the `config_entry` fixture; for other data update that entry
  (`hass.config_entries.async_update_entry`) instead of adding a second one.
- Command timeouts are shortened to a quarter of a second in `conftest.py`.
