"""Cloud-based device discovery

Discovers Gree devices via Cloud API instead of local network UDP broadcast.
"""

import asyncio
import logging
from typing import List, Optional
from asyncio.events import AbstractEventLoop

from .cloud_api import GreeCloudApi, CloudDeviceInfo, GREE_CLOUD_SERVERS
from .mqtt_client import GreeMqttClient
from .cloud_device import CloudDevice
from .deviceinfo import DeviceInfo
from .taskable import Taskable

_LOGGER = logging.getLogger(__name__)


class CloudDiscovery(Taskable):
    """Discover Gree devices via Cloud API
    
    Unlike local discovery which uses UDP broadcast, cloud discovery
    authenticates with Gree Cloud and retrieves device list from API.
    
    Example:
        ```python
        # Create discovery instance
        discovery = CloudDiscovery(
            username='user@example.com',
            password='password',
            server='Europe'
        )
        
        # Scan for devices
        devices = await discovery.scan()
        
        # Get MQTT client for device control
        mqtt_client = discovery.mqtt_client
        
        # Create cloud device
        device = CloudDevice(
            mqtt_client,
            devices[0].device_info,
            devices[0].key
        )
        ```
    """
    
    def __init__(
        self,
        username: str,
        password: str,
        server: str = 'Europe',
        loop: AbstractEventLoop = None
    ):
        """Initialize cloud discovery
        
        Args:
            username: Gree Cloud username/email
            password: Gree Cloud password
            server: Gree Cloud server region (see GREE_CLOUD_SERVERS)
            loop: Event loop
        """
        Taskable.__init__(self, loop)
        
        self.username = username
        self.password = password
        self.server = server
        
        self._api: Optional[GreeCloudApi] = None
        self._mqtt_client: Optional[GreeMqttClient] = None
        self._devices: List[CloudDeviceInfo] = []
        self._authenticated = False
    
    @property
    def api(self) -> Optional[GreeCloudApi]:
        """Get Cloud API instance"""
        return self._api
    
    @property
    def mqtt_client(self) -> Optional[GreeMqttClient]:
        """Get MQTT client instance"""
        return self._mqtt_client
    
    @property
    def devices(self) -> List[CloudDeviceInfo]:
        """Get discovered devices"""
        return self._devices
    
    async def authenticate(self) -> None:
        """Authenticate with Gree Cloud"""
        if self._authenticated:
            return
        
        _LOGGER.info(f"Authenticating with Gree Cloud ({self.server})...")
        
        # Create API client
        self._api = GreeCloudApi.for_server(self.server, self.username, self.password)
        
        # Login
        credentials = await self._api.login()
        
        _LOGGER.info(f"Successfully authenticated as user {credentials.user_id}")
        
        mqtt_server = GreeMqttClient.MQTT_SERVERS.get(self.server, 'mqtt-eu.gree.com')
        
        # Create MQTT client with correct server and port
        self._mqtt_client = GreeMqttClient(
            user_id=credentials.user_id,
            token=credentials.token,
            server=mqtt_server,
            port=1984  # Gree uses 1984, not 8883!
        )
        
        # Connect to MQTT broker
        await self._mqtt_client.connect()
        
        self._authenticated = True
    
    async def scan(self) -> List[CloudDeviceInfo]:
        """Scan for cloud devices
        
        Returns:
            List of discovered cloud devices
        """
        if not self._authenticated:
            await self.authenticate()
        
        _LOGGER.info("Scanning for cloud devices...")
        
        # Get all devices from all homes
        self._devices = await self._api.get_all_devices()
        
        _LOGGER.info(f"Found {len(self._devices)} cloud device(s)")
        
        for device in self._devices:
            _LOGGER.debug(f"  - {device.name} ({device.mac}) - {'online' if device.online else 'offline'}")
        
        return self._devices
    
    async def create_device(self, device_info: CloudDeviceInfo, cipher_version: int = 1) -> CloudDevice:
        """Create CloudDevice instance from discovered device info
        
        Args:
            device_info: Cloud device information from scan
            cipher_version: Cipher version to use (1 = ECB, 2 = GCM)
            
        Returns:
            CloudDevice instance ready to use
        """
        if not self._authenticated:
            await self.authenticate()
        
        # Convert CloudDeviceInfo to DeviceInfo
        dev_info = DeviceInfo(
            ip='mqtt.gree.com',  # Not used for cloud devices
            port=8883,
            mac=device_info.mac,
            name=device_info.name,
            brand=None,
            model=device_info.model,
            version=device_info.version
        )
        
        # Create cloud device
        device = CloudDevice(
            mqtt_client=self._mqtt_client,
            device_info=dev_info,
            device_key=device_info.key,
            cipher_version=cipher_version,
            loop=self._loop
        )
        
        return device
    
    async def close(self) -> None:
        """Close and cleanup resources"""
        if self._mqtt_client:
            await self._mqtt_client.disconnect()
            self._mqtt_client = None
        
        if self._api:
            await self._api.close()
            self._api = None
        
        self._authenticated = False
        
        _LOGGER.info("Cloud discovery closed")
    
    @staticmethod
    def list_servers() -> List[str]:
        """List available Gree Cloud servers
        
        Returns:
            List of server region names
        """
        return list(GREE_CLOUD_SERVERS.keys())
    
    def __repr__(self) -> str:
        return f"CloudDiscovery(server={self.server}, devices={len(self._devices)})"
