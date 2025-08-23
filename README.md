# Dog Feeding Tracker for Adafruit MagTag

A CircuitPython 10.x application that tracks dog feeding times on an Adafruit MagTag e-ink display. The tracker shows morning and evening feeding status with visual indicators (bowl icons and NeoPixel LEDs) and automatically sleeps outside feeding windows to conserve battery.

## Features

- **Visual Status Display**: Bowl icons show empty/filled state, text shows feeding times
- **LED Indicators**: Green = fed, Red = not fed (separate for morning/evening)
- **Auto-refresh**: Updates via MQTT triggers or periodic API polling
- **Power Management**: Deep sleep outside feeding windows (7-11 AM, 4-9 PM)
- **Network Resilient**: Automatic reconnection and retry logic
- **Modular Design**: Clean separation of display, network, and business logic

## Hardware Requirements

- Adafruit MagTag (ESP32-S2 with e-ink display)
- USB-C cable for programming/power
- WiFi network (2.4 GHz)

## Software Requirements

- CircuitPython 10.0.0 or later
- Required libraries (in `/lib` folder):
  - `adafruit_datetime`
  - `adafruit_minimqtt`
  - `adafruit_requests`
  - `adafruit_imageload`
  - `adafruit_display_text`
  - `neopixel`

## Installation

1. Install CircuitPython 10.x on your MagTag
2. Copy all Python files to the root directory:
   - `code.py` - Main application
   - `config.py` - Configuration settings
   - `display_manager.py` - Display management
   - `network_manager.py` - Network operations
   - `utils.py` - Utility functions
3. Create `settings.toml` with your network credentials (see below)
4. Create `/images/` directory and add:
   - `background.bmp` - Background image (296x128 pixels)
   - `bowl_tile.bmp` - Bowl sprite sheet (2 tiles: empty and filled)
5. Copy required libraries to `/lib/` folder

## Configuration

### settings.toml

Create this file in the root directory with your settings:

```toml
# WiFi Configuration (auto-connects on boot)
CIRCUITPY_WIFI_SSID = "your_wifi_ssid"
CIRCUITPY_WIFI_PASSWORD = "your_wifi_password"

# MQTT Configuration
MQTT_BROKER = "192.168.1.85"
MQTT_PORT = "1883"
MQTT_USERNAME = "mqtt_username"
MQTT_PASSWORD = "mqtt_password"

# API Endpoints
DOG_FEED_API = "http://192.168.1.85:1880/dog-feed-status"

# Optional: Device hostname
# CIRCUITPY_WIFI_HOSTNAME = "magtag-dogtracker"
```

### config.py Settings

Adjust these settings as needed:

- **Time Windows**: `MORNING_START/END`, `EVENING_START/END`
- **Refresh Intervals**: `STATUS_FETCH_INTERVAL`, `TIME_SYNC_INTERVAL`
- **Display Settings**: Text positions, sprite locations
- **NeoPixel Settings**: Brightness, colors, pixel assignments

## API Requirements

The REST API endpoint should return JSON in this format:

```json
{
  "dog_feed_status": {
    "morning": "2025-08-23T09:26:25Z",  // ISO timestamp or null
    "evening": null,
    "last_updated": "2025-08-23T14:30:00Z"
  }
}
```

## MQTT Topics

- `dog/fed/morning` - Triggers refresh when morning feeding occurs
- `dog/fed/evening` - Triggers refresh when evening feeding occurs

Messages on these topics trigger an API fetch to get the latest status.

## File Structure

```
/
├── code.py                 # Main application
├── config.py              # Configuration constants
├── display_manager.py     # Display and LED management
├── network_manager.py     # WiFi, MQTT, and API handling
├── utils.py              # Utility functions
├── settings.toml         # Network and API settings
├── images/
│   ├── background.bmp   # Display background
│   └── bowl_tile.bmp    # Bowl sprites (empty/filled)
└── lib/
    └── [required libraries]
```

## Operation

1. **Startup**: Device connects to WiFi, syncs time, fetches initial status
2. **Active Hours**: Stays awake during feeding windows (7-11 AM, 4-9 PM)
3. **Updates**: 
   - Immediate update on MQTT trigger
   - Periodic status check every 5 minutes
   - Display only refreshes when data changes
4. **Sleep Mode**: Deep sleeps outside feeding windows to save battery

## Troubleshooting

### Display Issues
- Ensure bowl sprite is properly formatted (indexed BMP)
- Check that images are in `/images/` directory
- Verify display refresh isn't happening too frequently

### Network Issues
- Confirm WiFi credentials in `settings.toml`
- Check firewall allows IoT VLAN to access main network
- Verify Node-RED is listening on all interfaces (0.0.0.0:1880)

### MQTT Issues
- Ensure MQTT broker allows connections from IoT network
- Verify MQTT credentials and port settings
- Check MQTT loop timeout is >= 1.0 seconds

### Debug Commands

In the REPL, you can use utility functions:

```python
from utils import *

# Check memory usage
memory_info()

# View WiFi details
wifi_info()

# Validate configuration
validate_config()

# Enter interactive debug mode
debug_mode()
```

## Power Consumption

- **Active Mode**: ~70-100mA (WiFi + display refresh)
- **Sleep Mode**: ~10mA (deep sleep)
- **Battery Life**: Approximately 3-5 days on 2000mAh battery

## Future Enhancements

- [ ] Add feeding time predictions based on patterns
- [ ] Support multiple pets with separate tracking
- [ ] Add web-based configuration interface
- [ ] Implement feeding reminders/alerts
- [ ] Add weekly/monthly statistics display
- [ ] Support for automatic feeders integration

## License

MIT License - Feel free to modify and adapt for your needs!

## Credits

Created for tracking dog feeding schedules using:
- Adafruit MagTag hardware
- CircuitPython 10.x
- Home Assistant / Node-RED backend