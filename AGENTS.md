# Rules for changing this integration

For AI agents and for people. The integration runs in many homes on hardware
nobody here can test, so a regression is found by a user, days later. The
automated tests are what stands between a change and that user.

## The rule

**Every change of behaviour comes with an automated test in the same pull
request.** No test, no merge.

- **Bug fix:** first write a test that fails for the reported reason, then fix
  it. The test stays as the proof the bug cannot come back.
- **New device, entity or option:** add a recorded device (`tests/fixtures/`)
  or extend one, and test what the entities show and what each command sends.
- **Refactoring:** the tests must pass untouched. If a test or a snapshot has
  to change, it is a change of behaviour: treat it as one and say so.
- **Never** delete, skip or loosen a test to get a green run. Never run
  `--snapshot-update` without reading the diff; every changed snapshot line
  must be intended and named in the pull request.

## Before and after every change

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt   # once
.venv/bin/python -m pytest -q
```

Run exactly this (it is what CI runs) before the change, to know the starting
point, and after it. The whole suite takes under a minute. See
[tests/README.md](tests/README.md) for how the tests are built.

## What must not change by accident

The tests pin these; a diff in any of them needs a reason in the pull request:

- **Unique ids and entity ids** (`tests/snapshots/test_devices.ambr`). Changing
  one orphans the user's entities, history and automations.
- **Status requests** (`tests/snapshots/test_status_requests.ambr`). A module
  can drop a request that is too long without any error: one extra column took
  air conditioners offline in 1.8.0-beta.1. Never more than 40 columns, five
  for a VRF head, and do not add columns to what an air conditioner is asked.
- **What a command sends:** property names, values and their order.
- **Air conditioners stay as they are** when the change is about another kind
  of device.
- **The library pin:** `manifest.json` and `requirements_test.txt` name the same
  `greeclimate-davo22` version.
- **Temperatures under two names:** climate and water heater classes provide
  `native_…` (read by Home Assistant 2026.11 and later) together with the old
  name (read by earlier versions). CI runs one Home Assistant version, so a
  change there is also checked on a running Home Assistant of the other kind.

## Devices and protocol values

- A fixture holds what a real unit reported (from a debug log or a capture in
  an issue). Do not invent properties or values; if the behaviour of a unit is
  not known, do not pin a guess: leave it out and ask the reporter.
- No real identifiers anywhere in the repository: MAC addresses, keys, account
  names, e-mail addresses and SSIDs are replaced by synthetic ones.
- Tests never touch the network. Everything goes through `tests/fake_cloud.py`.

## How a change ships

1. One topic per pull request, kept small; several small ones beat a big one.
2. Branch, pull request following the template, CI green.
3. Squash-merge, check that CI on `main` is green too.
4. Pre-release first. Anything that touches the communication with a device is
   also checked on a running Home Assistant before the final release, and by
   the reporter when it concerns hardware only they have.
