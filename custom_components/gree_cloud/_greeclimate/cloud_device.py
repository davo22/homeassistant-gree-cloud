"""Cloud-based Gree device implementation

Handles communication with Gree devices via Cloud MQTT broker.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List

from .cipher import CipherV1, CipherV2
from .device import Device, Props
from .deviceinfo import DeviceInfo
from .mqtt_client import GreeMqttClient, MqttDeviceMessage
from .taskable import Taskable

_LOGGER = logging.getLogger(__name__)


class CloudDevice(Device):
    """Cloud-based Gree device
    
    Communicates with Gree devices through the Gree Cloud MQTT broker.
    Supports both CipherV1 (AES-128-ECB) and CipherV2 (AES-128-GCM).
    
    Important differences from local devices:
    - Uses MQTT instead of UDP
    - Temperature values are NOT offset (no +40 adjustment)
    - Commands must be sent sequentially with response wait
    - Supports parent/child device hierarchy
    
    Example:
        ```python
        # Login to cloud
        api = GreeCloudApi.for_server('Europe', 'user@example.com', 'password')
        await api.login()
        devices = await api.get_all_devices()
        
        # Create MQTT client
        mqtt = GreeMqttClient(api.user_id, api.token)
        await mqtt.connect()
        
        # Create cloud device
        device_info = CloudDeviceInfo(
            name=devices[0].name,
            mac=devices[0].mac,
            key=devices[0].key
        )
        device = CloudDevice(mqtt, device_info)
        
        # Use device
        await device.bind()
        await device.update_state()
        device.power = True
        device.target_temperature = 24
        await device.push_state_update()
        ```
    """
    
    def __init__(
        self,
        mqtt_client: GreeMqttClient,
        device_info: DeviceInfo,
        device_key: str,
        cipher_version: int = 1,
        timeout: int = 120,
        command_timeout: int = 10,
        loop: asyncio.AbstractEventLoop = None
    ):
        """Initialize cloud device
        
        Args:
            mqtt_client: Connected MQTT client instance
            device_info: Device information (ip/port not used, but mac/name required)
            device_key: Device encryption key from Cloud API
            cipher_version: Cipher version to use (1 = ECB, 2 = GCM), defaults to 1
            timeout: General timeout for device operations
            command_timeout: Timeout for MQTT command responses
            loop: Event loop
        """
        super().__init__(device_info, timeout=timeout, loop=loop)
        
        self._mqtt_client = mqtt_client
        self._device_key = device_key
        self._cipher_version = cipher_version
        self._command_timeout = command_timeout
        
        # Setup cipher based on version
        if cipher_version == 2:
            self.device_cipher = CipherV2(device_key.encode())
        else:
            self.device_cipher = CipherV1(device_key.encode())
        
        # Detect parent/child MAC addresses
        self._child_mac = device_info.mac
        self._parent_mac = self._detect_parent_mac(device_info.mac)
        
        # Response handling
        self._response_event: Optional[asyncio.Event] = None
        self._response_data: Optional[Dict] = None
        
        # Setup message handler
        self._mqtt_client.add_message_handler(self._handle_mqtt_message)
        
        _LOGGER.info(f"CloudDevice initialized: {device_info.name} (parent: {self._parent_mac}, child: {self._child_mac})")
    
    def _detect_parent_mac(self, mac: str) -> str:
        """Detect parent MAC from child MAC
        
        For devices ending with '00' and longer than 12 chars, strip last 2 chars.
        This handles parent/child device hierarchy for commercial units.
        """
        if mac.endswith('00') and len(mac) > 12:
            return mac[:-2]
        return mac
    
    async def bind(self, key: str = None, cipher=None):
        """Bind to cloud device
        
        For cloud devices, binding is simplified since we already have
        the device key from the Cloud API.
        
        Args:
            key: Device key (ignored, uses key from __init__)
            cipher: Cipher (ignored, uses cipher from __init__)
        """
        # Subscribe to device topics
        await self._mqtt_client.subscribe_to_device(self._parent_mac)
        
        _LOGGER.info(f"Cloud device bound: {self.device_info.name}")
        
        # Trigger initial state update
        await self.update_state()
    
    async def update_state(self):
        """Update device state from cloud"""
        _LOGGER.debug(f"Updating cloud device state: {self.device_info.name}")
        
        # Request all properties
        props = [x.value for x in Props]
        if not self.hid:
            props.append('hid')
        
        # Setup response event
        self._response_event = asyncio.Event()
        self._response_data = None
        
        # Send status request
        command = {
            't': 'status',
            'cols': props
        }
        
        await self._mqtt_client.publish_command(
            self._parent_mac,
            command,
            self.device_cipher,
            self._child_mac
        )
        
        # Wait for response
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=self._command_timeout)
            
            if self._response_data:
                # Process response data
                self.handle_state_update(**self._response_data)
        
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Timeout waiting for state update from {self.device_info.name}")
        finally:
            self._response_event = None
            self._response_data = None
    
    async def push_state_update(self):
        """Push pending state updates to device
        
        IMPORTANT: Cloud devices require sequential command sending.
        Each command must wait for response before sending the next.
        """
        if not self._dirty:
            return
        
        _LOGGER.debug(f"Pushing state updates to cloud device: {self.device_info.name}")
        
        # Build commands with proper ordering (Mode first, Power last)
        commands = self._build_command_sequence()
        
        # Send commands sequentially
        for cmd in commands:
            await self._send_command(cmd['opt'], cmd['p'])
        
        self._dirty.clear()
    
    def _build_command_sequence(self) -> List[Dict[str, Any]]:
        """Build command sequence with proper ordering
        
        Order matters for cloud devices:
        1. Mode first (if present)
        2. Temperature with bit/unit
        3. Other properties
        4. Power last (if present)
        """
        commands = []
        remaining = {}
        
        # Collect pending updates
        for prop_name in self._dirty:
            value = self._properties.get(prop_name)
            remaining[prop_name] = value
        
        # Mode first
        if Props.MODE.value in remaining:
            commands.append({
                'opt': [Props.MODE.value],
                'p': [remaining[Props.MODE.value]]
            })
            del remaining[Props.MODE.value]
        
        # Temperature-related properties must always travel together in one
        # command: a 0.5C step where the whole-degree part is unchanged only
        # marks TEMP_BIT/TEMP_DECI/TEMP_HALF_DEGREE dirty, and the device
        # ignores those without SetTem present alongside them.
        temp_group = (
            Props.TEMP_SET.value,
            Props.TEMP_BIT.value,
            Props.TEMP_DECI.value,
            Props.TEMP_HALF_DEGREE.value,
        )
        if any(p in remaining for p in temp_group):
            temp_opt = []
            temp_p = []
            for p in temp_group:
                value = self._properties.get(p)
                if value is not None:
                    temp_opt.append(p)
                    temp_p.append(value)
                remaining.pop(p, None)

            if Props.TEMP_UNIT.value in remaining:
                temp_opt.append(Props.TEMP_UNIT.value)
                temp_p.append(remaining[Props.TEMP_UNIT.value])
                del remaining[Props.TEMP_UNIT.value]

            commands.append({'opt': temp_opt, 'p': temp_p})
        
        # Save Power for last
        has_power = Props.POWER.value in remaining
        power_value = remaining.pop(Props.POWER.value, None)
        
        # Other properties
        for key, value in remaining.items():
            commands.append({'opt': [key], 'p': [value]})
        
        # Power last
        if has_power:
            commands.append({
                'opt': [Props.POWER.value],
                'p': [power_value]
            })
        
        return commands
    
    async def _send_command(self, opt: List[str], p: List[Any]) -> None:
        """Send command and wait for response"""
        _LOGGER.debug(f"Sending command to {self.device_info.name}: {opt} = {p}")
        
        # Setup response event
        self._response_event = asyncio.Event()
        
        # Send command
        command = {
            't': 'cmd',
            'opt': opt,
            'p': p
        }
        
        await self._mqtt_client.publish_command(
            self._parent_mac,
            command,
            self.device_cipher,
            self._child_mac
        )
        
        # Wait for response (short timeout - some devices don't ack)
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            _LOGGER.debug(f"No ack from {self.device_info.name} (command may still have been executed)")
        finally:
            self._response_event = None
    
    def _handle_mqtt_message(self, topic: str, message: MqttDeviceMessage) -> None:
        """Handle incoming MQTT messages"""
        # Check if message is for this device
        if self._parent_mac not in topic and self._child_mac not in topic:
            return
        
        # Handle response messages (command acknowledgments / state responses)
        if 'response/' in topic:
            if message.pack:
                try:
                    decrypted = self.device_cipher.decrypt(message.pack)
                    _LOGGER.debug(f"Response decrypted: {decrypted}")
                    if decrypted.get('t') == 'dat':
                        cols = decrypted.get('cols', [])
                        dat = decrypted.get('dat', [])
                        if cols and dat and len(cols) == len(dat):
                            data = dict(zip(cols, dat))
                            if self._response_event:
                                self._response_data = data
                            else:
                                self.handle_state_update(**data)
                except Exception as e:
                    _LOGGER.debug(f"Could not decrypt response: {e}")
            if self._response_event:
                self._response_event.set()
            return
        
        # Handle status messages
        if 'status/' in topic and message.pack:
            try:
                decrypted = self.device_cipher.decrypt(message.pack)
                
                # Process status data
                if decrypted.get('t') == 'dat':
                    cols = decrypted.get('cols', [])
                    dat = decrypted.get('dat', [])
                    
                    if cols and dat and len(cols) == len(dat):
                        data = dict(zip(cols, dat))
                        
                        # Store for state update
                        if self._response_event:
                            self._response_data = data
                            self._response_event.set()
                        else:
                            # Unsolicited status update
                            self.handle_state_update(**data)
            
            except Exception as e:
                _LOGGER.debug(f"Failed to decrypt status message: {e}")
        
        # Handle connect messages
        if 'connect/' in topic:
            _LOGGER.info(f"Device {self.device_info.name} connected to cloud")
    
    async def close(self):
        """Close device and cleanup resources"""
        try:
            # Unsubscribe from MQTT topics
            await self._mqtt_client.unsubscribe_from_device(self._parent_mac)
            
            # Remove message handler
            self._mqtt_client.remove_message_handler(self._handle_mqtt_message)
            
            # Close transport if exists
            if self._transport:
                super().close()
        
        except Exception as e:
            _LOGGER.warning(f"Error closing cloud device: {e}")
    
    def __repr__(self) -> str:
        return (f"CloudDevice(name={self.device_info.name}, "
                f"mac={self.device_info.mac}, "
                f"parent_mac={self._parent_mac}, "
                f"child_mac={self._child_mac})")
