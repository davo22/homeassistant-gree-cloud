"""Bundled copy of the davo22/greeclimate fork (cloud support), tag 1.2.1.

Source: https://github.com/davo22/greeclimate @ 5e5437b39b87fa7c86ac95880ff84d215e157292
License: GPL-3.0 (see LICENSE.txt in this directory).

Bundled under a private name because Home Assistant core ships upstream
``greeclimate`` (for the built-in ``gree`` integration); a second package
with the same import name collides with it and breaks this integration.
Only change: absolute ``greeclimate.`` imports made relative, and the
import-time ``logging.basicConfig(level=DEBUG)`` removed.
"""
