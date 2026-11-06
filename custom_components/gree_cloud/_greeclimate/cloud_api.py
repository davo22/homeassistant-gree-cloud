"""Gree Cloud API Client

Based on: https://github.com/luc10/gree-api-client

Allows authentication with Gree Cloud and retrieval of device information
including encryption keys required for MQTT communication.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from Crypto.Cipher import AES
import base64

_LOGGER = logging.getLogger(__name__)


@dataclass
class CloudDeviceInfo:
    """Information about a cloud device"""
    name: str
    mac: str
    key: str
    model: Optional[str] = None
    version: Optional[str] = None
    online: bool = True


@dataclass
class CloudHome:
    """Information about a Gree Cloud home"""
    id: int
    name: str


@dataclass
class CloudCredentials:
    """Gree Cloud authentication credentials"""
    user_id: int
    token: str


# Gree Cloud API Servers by region
GREE_CLOUD_SERVERS = {
    'Australia': 'https://augrih.gree.com',
    'China Mainland': 'https://grih.gree.com',
    'East South Asia': 'https://hkgrih.gree.com',
    'Europe': 'https://eugrih.gree.com',
    'India': 'https://ingrih.gree.com',
    'Latin American': 'https://lagrih.gree.com',
    'Middle East': 'https://megrih.gree.com',
    'North American': 'https://nagrih.gree.com',
    'Russia': 'https://rugrih.gree.com',
    'South American': 'https://sagrih.gree.com',
}


class GreeCloudApi:
    """Gree Cloud API Client

    Provides authentication and device discovery for Gree Cloud services.
    """

    # App constants from reverse engineering
    APP_ID = '4920681951525131286'
    APP_HASH = '0fa513124aa97781d1f3f40d61ca1a89'
    AES_KEY = b'#G$&^jgfujy6ujxt'

    def __init__(self, base_url: str, username: str, password: str):
        """Initialize the Gree Cloud API client

        Args:
            base_url: The regional Gree Cloud server URL
            username: User email/username
            password: User password (will be hashed internally)
        """
        self.base_url = base_url
        self.username = username
        self.password = password
        self.user_id: Optional[int] = None
        self.token: Optional[str] = None

        # Create session with timeout
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session: Optional[aiohttp.ClientSession] = aiohttp.ClientSession(timeout=timeout)

    @classmethod
    def for_server(cls, server: str, username: str, password: str) -> 'GreeCloudApi':
        """Create API client for a specific server region

        Args:
            server: Server region name (e.g., 'Europe', 'North American')
            username: User email/username
            password: User password

        Returns:
            GreeCloudApi instance configured for the specified region
        """
        if server not in GREE_CLOUD_SERVERS:
            raise ValueError(f"Unknown server: {server}. Must be one of: {list(GREE_CLOUD_SERVERS.keys())}")
        return cls(GREE_CLOUD_SERVERS[server], username, password)

    def _md5(self, input_str: str) -> str:
        """Calculate MD5 hash"""
        return hashlib.md5(input_str.encode('utf-8')).hexdigest()

    def _prepare_body(self, payload: Dict, date: datetime, hash_props: List[str]) -> Dict:
        """Prepare request body with authentication

        Args:
            payload: Request payload data
            date: Current datetime (should be UTC)
            hash_props: List of property names to include in hash calculation

        Returns:
            Complete request body with API authentication
        """
        # Use UTC time for consistency with server
        t = date.strftime('%Y-%m-%d %H:%M:%S')
        r = int(date.timestamp())

        # Generate verification code
        vc = self._md5(f"{self.APP_ID}_{self.APP_HASH}_{t}_{r}")

        # Generate data verification code
        props = [str(payload[p]) for p in hash_props]
        dat_vc = self._md5(f"{self.APP_HASH}_{'_'.join(props)}")

        return {
            'api': {
                'appId': self.APP_ID,
                'r': r,
                't': t,
                'vc': vc,
            },
            'datVc': dat_vc,
            **payload
        }

    def _encrypt(self, data: str) -> bytes:
        """Encrypt data with AES-128-ECB"""
        cipher = AES.new(self.AES_KEY, AES.MODE_ECB)
        # PKCS7 padding
        pad_len = 16 - (len(data) % 16)
        padded = data + (chr(pad_len) * pad_len)
        encrypted = cipher.encrypt(padded.encode('utf-8'))
        return encrypted

    def _decrypt(self, data: bytes) -> str:
        """Decrypt data with AES-128-ECB"""
        cipher = AES.new(self.AES_KEY, AES.MODE_ECB)
        decrypted = cipher.decrypt(data)
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        return decrypted[:-pad_len].decode('utf-8')

    async def _send_request(self, endpoint: str, data: str) -> str:
        """Send POST request to API

        Args:
            endpoint: API endpoint path
            data: JSON data to send

        Returns:
            Encrypted response string
        """
        import aiohttp

        url = f"{self.base_url}{endpoint}"

        encrypted_body = self._encrypt(data)
        base64_body = base64.b64encode(encrypted_body).decode('utf-8')

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Gaen1': '5ac2bdf935bcca70',
            'Charset': 'utf-8',
        }

        _LOGGER.debug(f"Sending request to {url}")

        # Use persistent session with timeout
        async with self._session.post(url, data=base64_body, headers=headers) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}: {response.reason}")

            json_data = await response.json()
            return json_data['enRes']

    async def login(self) -> CloudCredentials:
        """Login to Gree Cloud

        Returns:
            CloudCredentials with user_id and token
        """
        from datetime import timezone

        # IMPORTANT: Use UTC time to match server time
        date = datetime.now(timezone.utc)
        t = date.strftime('%Y-%m-%d %H:%M:%S')

        # Hash password using Gree's algorithm
        h = self._md5(self._md5(self.password) + self.password)
        psw = self._md5(h + t)

        body = json.dumps(self._prepare_body(
            {
                'psw': psw,
                't': t,
                'user': self.username,
            },
            date,
            ['user', 'psw', 't']
        ))

        encrypted_response = await self._send_request('/App/UserLoginV2', body)
        decrypted = self._decrypt(base64.b64decode(encrypted_response))

        _LOGGER.debug(f"Login response (decrypted): {decrypted}")

        data = json.loads(decrypted)
        _LOGGER.debug(f"Login response (parsed): {data}")

        # Check for error response
        if 'r' in data and data['r'] != 200:
            raise Exception(f"Login failed: {data.get('msg', 'Unknown error')}")

        # Handle different response formats
        if 'uid' in data:
            user_id = data['uid']
            token = data['token']
        elif 'data' in data and isinstance(data['data'], dict):
            user_id = data['data'].get('uid')
            token = data['data'].get('token')
        else:
            raise Exception(f"Unexpected login response format: {data}")

        if not user_id or not token:
            raise Exception(f"Missing uid or token in response: {data}")

        self.user_id = user_id
        self.token = token

        _LOGGER.info(f"Successfully logged in as user {self.user_id}")

        return CloudCredentials(user_id=user_id, token=token)

    async def get_homes(self) -> List[CloudHome]:
        """Get list of homes

        Returns:
            List of CloudHome objects
        """
        from datetime import timezone

        if not self.user_id or not self.token:
            raise Exception('Not logged in. Call login() first.')

        date = datetime.now(timezone.utc)

        body = json.dumps(self._prepare_body(
            {
                'token': self.token,
                'uid': self.user_id,
            },
            date,
            ['token', 'uid']
        ))

        encrypted_response = await self._send_request('/App/GetHomes', body)
        decrypted = self._decrypt(base64.b64decode(encrypted_response))
        data = json.loads(decrypted)

        homes = [
            CloudHome(id=h['id'], name=h['name'].strip())
            for h in data['home']
        ]

        _LOGGER.info(f"Found {len(homes)} homes")
        return homes

    async def get_devices(self, home_id: int) -> List[CloudDeviceInfo]:
        """Get list of devices in a home

        Args:
            home_id: ID of the home

        Returns:
            List of CloudDeviceInfo objects
        """
        from datetime import timezone

        if not self.user_id or not self.token:
            raise Exception('Not logged in. Call login() first.')

        date = datetime.now(timezone.utc)

        body = json.dumps(self._prepare_body(
            {
                'token': self.token,
                'homeId': home_id,
                'uid': self.user_id,
            },
            date,
            ['token', 'uid', 'homeId']
        ))

        encrypted_response = await self._send_request('/App/GetDevsInRoomsOfHomeV2', body)
        decrypted = self._decrypt(base64.b64decode(encrypted_response))
        data = json.loads(decrypted)

        devices = []
        for room in data['rooms']:
            for dev in room['devs']:
                device = CloudDeviceInfo(
                    name=dev['name'].strip(),
                    mac=dev['mac'].strip(),
                    key=dev['key'].strip(),
                    model=dev.get('model', '').strip() if dev.get('model') else None,
                    version=dev.get('ver', '').strip() if dev.get('ver') else None,
                    online=bool(dev.get('online', 1))
                )
                devices.append(device)

        _LOGGER.info(f"Found {len(devices)} devices in home {home_id}")
        return devices

    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
            _LOGGER.debug("HTTP session closed")

    async def __aenter__(self):
        """Async context manager enter"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
        return False

    async def get_all_devices(self) -> List[CloudDeviceInfo]:
        """Get all devices from all homes

        Filters out duplicate devices with same key. When duplicates exist,
        keeps the one with MAC ending in '00' (responsive) and hides the one without.

        Returns:
            List of all CloudDeviceInfo objects across all homes (deduplicated)
        """
        homes = await self.get_homes()
        all_devices = []

        for home in homes:
            devices = await self.get_devices(home.id)
            all_devices.extend(devices)

        # Filter duplicates: when same key exists with MACs where one ends with '00'
        filtered_devices = self._filter_duplicate_devices(all_devices)

        if len(filtered_devices) < len(all_devices):
            _LOGGER.info(f"Filtered out {len(all_devices) - len(filtered_devices)} duplicate device(s)")

        _LOGGER.info(f"Found total of {len(filtered_devices)} devices across all homes")
        return filtered_devices

    def _filter_duplicate_devices(self, devices: List[CloudDeviceInfo]) -> List[CloudDeviceInfo]:
        """Filter out duplicate devices with same key

        When devices share the same encryption key but have different MACs
        (one normal, one ending with '00'), keep only the one with '00'.
        The device without '00' suffix doesn't respond to commands.

        Args:
            devices: List of devices to filter

        Returns:
            Filtered list without duplicates
        """
        # Group devices by encryption key
        key_groups: Dict[str, List[CloudDeviceInfo]] = {}
        for device in devices:
            if device.key not in key_groups:
                key_groups[device.key] = []
            key_groups[device.key].append(device)

        filtered = []
        for key, group in key_groups.items():
            if len(group) == 1:
                # No duplicates, keep as is
                filtered.append(group[0])
            else:
                # Multiple devices with same key - filter by MAC
                # Prefer device WITH '00' suffix (responsive device)
                devices_with_00 = [d for d in group if d.mac.endswith('00') and len(d.mac) > 12]
                devices_without_00 = [d for d in group if not (d.mac.endswith('00') and len(d.mac) > 12)]

                if devices_with_00:
                    # Keep device(s) with '00' suffix
                    filtered.extend(devices_with_00)
                    if devices_without_00:
                        _LOGGER.debug(f"Filtering out non-responsive device(s) without '00': {[d.mac for d in devices_without_00]}")
                else:
                    # No device with '00' found, keep all (shouldn't happen but be safe)
                    filtered.extend(group)

        return filtered
