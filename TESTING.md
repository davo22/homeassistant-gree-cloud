# Manual Testing Script

This is a simple Python script to test the cloud connection independently from Home Assistant.

## Prerequisites

```bash
pip install aiohttp pycryptodome aiomqtt netifaces
```

## Install forked greeclimate library

```bash
pip install git+https://github.com/dawidrashid/greeclimate.git@master
```

## Test Script

```python
import asyncio
import logging
from greeclimate.cloud_api import GreeCloudApi
from greeclimate.mqtt_client import GreeMqttClient
from greeclimate.cloud_device import CloudDevice
from greeclimate.deviceinfo import DeviceInfo

logging.basicConfig(level=logging.DEBUG)

async def test_cloud_connection():
    """Test connection to Gree Cloud and device control."""
    
    # Configuration
    SERVER = "Europe"  # Change to your region
    USERNAME = "your-email@example.com"  # Change to your Gree+ username
    PASSWORD = "your-password"  # Change to your Gree+ password
    
    print(f"Testing Gree Cloud connection...")
    print(f"Server: {SERVER}")
    print(f"Username: {USERNAME}")
    print()
    
    try:
        # Login to cloud
        print("1. Logging in to Gree Cloud...")
        api = GreeCloudApi.for_server(SERVER, USERNAME, PASSWORD)
        credentials = await api.login()
        print(f"   ✓ Logged in as user {credentials.user_id}")
        print()
        
        # Get devices
        print("2. Fetching devices...")
        devices = await api.get_all_devices()
        print(f"   ✓ Found {len(devices)} device(s):")
        for dev in devices:
            print(f"     - {dev.name} (MAC: {dev.mac}, Online: {dev.online})")
        print()
        
        if not devices:
            print("No devices found. Exiting.")
            await api.close()
            return
        
        # Connect to MQTT
        print("3. Connecting to MQTT broker...")
        mqtt = GreeMqttClient(credentials.user_id, credentials.token)
        await mqtt.connect()
        print("   ✓ Connected to MQTT")
        print()
        
        # Create and bind to first device
        print("4. Binding to first device...")
        cloud_dev = devices[0]
        device_info = DeviceInfo(
            ip="0.0.0.0",
            port=0,
            mac=cloud_dev.mac,
            name=cloud_dev.name,
        )
        
        device = CloudDevice(
            mqtt_client=mqtt,
            device_info=device_info,
            device_key=cloud_dev.key,
            cipher_version=1,
        )
        
        await device.bind()
        print(f"   ✓ Bound to device: {device.device_info.name}")
        print()
        
        # Get initial state
        print("5. Reading device state...")
        await device.update_state()
        print(f"   Power: {device.power}")
        print(f"   Mode: {device.mode}")
        print(f"   Current Temperature: {device.current_temperature}°C")
        print(f"   Target Temperature: {device.target_temperature}°C")
        print(f"   Fan Speed: {device.fan_speed}")
        print()
        
        # Test command (optional - uncomment to test)
        # print("6. Testing command (turning on)...")
        # device.power = True
        # await device.push_state_update()
        # print("   ✓ Command sent")
        # print()
        
        # Cleanup
        print("7. Cleaning up...")
        await device.close()
        await mqtt.disconnect()
        await api.close()
        print("   ✓ Done")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_cloud_connection())
```

## Usage

1. Save the script as `test_cloud.py`
2. Edit the configuration section with your credentials
3. Run: `python test_cloud.py`

## Expected Output

```
Testing Gree Cloud connection...
Server: Europe
Username: your-email@example.com

1. Logging in to Gree Cloud...
   ✓ Logged in as user 12345678

2. Fetching devices...
   ✓ Found 2 device(s):
     - Living Room AC (MAC: aabbccddeeff, Online: True)
     - Bedroom AC (MAC: 112233445566, Online: True)

3. Connecting to MQTT broker...
   ✓ Connected to MQTT

4. Binding to first device...
   ✓ Bound to device: Living Room AC

5. Reading device state...
   Power: True
   Mode: Mode.Cool
   Current Temperature: 23°C
   Target Temperature: 22°C
   Fan Speed: FanSpeed.Auto

7. Cleaning up...
   ✓ Done
```

## Troubleshooting

- **Login failed**: Check credentials and server region
- **No devices found**: Ensure devices are registered in Gree+ app
- **MQTT connection failed**: Check internet connectivity
- **Timeout errors**: Device might be offline or unresponsive
