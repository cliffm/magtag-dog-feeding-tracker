"""
Dog Feeding Tracker for Adafruit MagTag
CircuitPython 10.x compatible
Tracks morning and evening dog feeding status with e-ink display
Uses settings.toml for configuration
"""

import os
import gc
import json
import ssl
import time
import alarm
import board
import rtc
import displayio
import terminalio
import socketpool
import neopixel
import wifi
import microcontroller
import adafruit_datetime as datetime
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import adafruit_requests
import adafruit_imageload
from adafruit_display_text import label

# Configuration class for all settings
class Config:
    """Configuration settings for the dog feeding tracker"""

    # Time windows (24-hour format)
    MORNING_START = 7
    MORNING_END = 11
    EVENING_START = 16
    EVENING_END = 23  # Extended for testing (was 21)

    # API endpoints
    TIME_URL = "http://worldtimeapi.org/api/timezone/America/New_York"
    # Get API URL from settings.toml or use default
    DOG_FEED_STATUS_URL = os.getenv("DOG_FEED_API", "http://192.168.1.85:1880/dog-feed-status")

    # MQTT topics
    MQTT_MORNING_TOPIC = 'dog/fed/morning'
    MQTT_EVENING_TOPIC = 'dog/fed/evening'

    # Refresh intervals (seconds)
    TIME_SYNC_INTERVAL = 3600  # 1 hour
    STATUS_FETCH_INTERVAL = 300  # 5 minutes
    DISPLAY_REFRESH_MIN_INTERVAL = 5  # Minimum time between display refreshes
    MQTT_LOOP_TIMEOUT = 1.0  # MQTT loop timeout (must be >= socket timeout)

    # Retry settings
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    CONNECTION_FAILURE_THRESHOLD = 5
    HTTP_TIMEOUT = 5  # Reduced timeout for faster failures

    # NeoPixel settings (MagTag has 4 NeoPixels)
    PIXEL_BRIGHTNESS = 0.05
    PIXEL_RED = (150, 0, 0)
    PIXEL_GREEN = (0, 150, 0)
    PIXEL_OFF = (0, 0, 0)

    # NeoPixel positions for status indicators
    MORNING_PIXEL = 3  # Top right
    EVENING_PIXEL = 0  # Top left

    # Display resources
    BACKGROUND_BMP = "/images/background.bmp"
    BOWL_SPRITE_BMP = "/images/bowl_tile.bmp"

    # Display positioning
    MORNING_X_OFFSET = 0
    EVENING_X_OFFSET = 147


class DogFeedingTracker:
    """Main class for dog feeding tracker functionality"""

    def __init__(self):
        """Initialize the tracker with default values"""
        # Hardware components
        self.pixels = neopixel.NeoPixel(
            board.NEOPIXEL,
            4,  # MagTag has 4 NeoPixels
            brightness=Config.PIXEL_BRIGHTNESS,
            auto_write=True  # CircuitPython 10 supports auto_write
        )

        # Display components
        self.morning_sprite = None
        self.morning_sprite_label = None
        self.evening_sprite = None
        self.evening_sprite_label = None

        # Network components
        self.requests = None
        self.mqtt_client = None
        self.pool = None

        # Timing tracking
        self.last_refresh = 0
        self.last_sync = 0
        self.last_status_fetch = 0

        # Connection tracking
        self.connection_failures = 0
        self.mqtt_connected = False

        # Track if this is first update
        self.first_update = True

        # Load bowl icon sprite sheet
        self.bowl_icon, self.bowl_icon_pal = adafruit_imageload.load(
            Config.BOWL_SPRITE_BMP
        )
        print("Bowl sprites loaded successfully")

    def connect_wifi(self, max_attempts=Config.MAX_RETRIES):
        """
        Connect to WiFi - CircuitPython 10 auto-connects using settings.toml
        Returns: True if connected, False otherwise
        """
        # CircuitPython automatically connects using CIRCUITPY_WIFI_SSID/PASSWORD
        # We just need to verify the connection
        for attempt in range(max_attempts):
            try:
                if wifi.radio.connected:
                    print(f"WiFi connected! IP: {wifi.radio.ipv4_address}")
                    self.connection_failures = 0
                    return True
                else:
                    print(f"Waiting for WiFi connection (attempt {attempt + 1}/{max_attempts})...")
                    time.sleep(2)

            except Exception as e:
                print(f"WiFi error: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(Config.RETRY_DELAY)

        self.connection_failures += 1
        print("Failed to connect to WiFi")
        return False

    def ensure_wifi_connected(self):
        """Check WiFi connection and reconnect if needed"""
        if not wifi.radio.connected:
            print("WiFi disconnected, attempting to reconnect...")
            return self.connect_wifi()
        return True

    def set_device_time(self):
        """
        Set device RTC from time API
        Returns: True if successful, False otherwise
        """
        if not self.ensure_wifi_connected():
            return False

        try:
            if not self.requests:
                self.requests = adafruit_requests.Session(
                    self.pool,
                    ssl.create_default_context()
                )

            print("Fetching current time...")
            response = self.requests.get(Config.TIME_URL, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Parse the datetime string
                dt_string = data['datetime']
                d = datetime.datetime.fromisoformat(dt_string.split('.')[0])

                # Set the RTC
                rtc.RTC().datetime = time.struct_time((
                    d.year, d.month, d.day,
                    d.hour, d.minute, d.second,
                    d.weekday(),
                    data['day_of_year'],
                    -1 if data['dst'] else 0
                ))

                print(f"Device time set to: {d}")
                return True

        except Exception as e:
            print(f"Error setting device time: {e}")

        return False

    def test_connectivity(self):
        """Test network connectivity to various endpoints"""
        print("\n=== Testing Network Connectivity ===")

        # Get MQTT broker from settings
        mqtt_broker = os.getenv("MQTT_BROKER", "192.168.1.85")

        # Test endpoints
        test_urls = [
            ("Time API", Config.TIME_URL),
            ("Dog Feed API", Config.DOG_FEED_STATUS_URL),
            ("MQTT Broker HTTP", f"http://{mqtt_broker}:1880/")
        ]

        for name, url in test_urls:
            try:
                print(f"Testing {name}: {url}")
                response = self.requests.get(url, timeout=5)
                print(f"  ✓ {name} reachable (status: {response.status_code})")
            except Exception as e:
                print(f"  ✗ {name} not reachable: {e}")

        print("=== Connectivity Test Complete ===\n")

    def fetch_dog_feed_status(self):
        """
        Fetch dog feeding status from REST API
        Returns: Status dictionary or None
        """
        if not self.ensure_wifi_connected():
            return None

        for attempt in range(Config.MAX_RETRIES):
            try:
                if not self.requests:
                    return None

                print(f"Fetching dog feed status "
                      f"(attempt {attempt + 1}/{Config.MAX_RETRIES})...")

                response = self.requests.get(
                    Config.DOG_FEED_STATUS_URL,
                    timeout=Config.HTTP_TIMEOUT
                )

                if response.status_code == 200:
                    data = response.json()
                    status = data.get('dog_feed_status', {})

                    # Log status
                    morning = "Yes" if status.get('morning') else "No"
                    evening = "Yes" if status.get('evening') else "No"
                    print(f"Status: Morning fed: {morning}, Evening fed: {evening}")

                    return status
                else:
                    print(f"API returned status code: {response.status_code}")
                    print(f"Response text: {response.text[:200]}")  # First 200 chars

            except Exception as e:
                print(f"Error fetching status: {e}")
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)

        return None

    def parse_timestamp(self, timestamp_str):
        """
        Parse timestamp string to display format (HH:MM)
        Returns: Formatted time string or None
        """
        if not timestamp_str:
            return None

        try:
            # Handle ISO format timestamps
            if 'T' in timestamp_str:
                # Split on T and take time portion
                time_part = timestamp_str.split('T')[1]
                # Remove timezone info and microseconds
                time_part = time_part.split('.')[0].split('Z')[0]
                # Extract hours and minutes
                hour, minute = time_part.split(':')[:2]
                return f"{hour}:{minute}"

            # If already a time string, return as-is
            return timestamp_str

        except Exception as e:
            print(f"Error parsing timestamp '{timestamp_str}': {e}")
            return timestamp_str

    def update_display_from_status(self, status_data, force_refresh=True):
        """Update the display and NeoPixels based on feeding status"""
        if not status_data:
            print("No status data to display")
            return

        morning_status = status_data.get('morning')
        evening_status = status_data.get('evening')

        # Track if anything changed
        display_changed = False

        # Update morning status
        if morning_status:
            self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_GREEN
            if self.morning_sprite:
                if self.morning_sprite[0] != 1:
                    self.morning_sprite[0] = 1  # Show filled bowl
                    display_changed = True
            if self.morning_sprite_label:
                display_time = self.parse_timestamp(morning_status)
                new_text = f"Fed at {display_time}" if display_time else "Fed"
                if self.morning_sprite_label.text != new_text:
                    self.morning_sprite_label.text = new_text
                    display_changed = True
        else:
            self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_RED
            if self.morning_sprite:
                if self.morning_sprite[0] != 0:
                    self.morning_sprite[0] = 0  # Show empty bowl
                    display_changed = True
            if self.morning_sprite_label:
                if self.morning_sprite_label.text != "Not fed":
                    self.morning_sprite_label.text = "Not fed"
                    display_changed = True

        # Update evening status
        if evening_status:
            self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_GREEN
            if self.evening_sprite:
                if self.evening_sprite[0] != 1:
                    self.evening_sprite[0] = 1  # Show filled bowl
                    display_changed = True
            if self.evening_sprite_label:
                display_time = self.parse_timestamp(evening_status)
                new_text = f"Fed at {display_time}" if display_time else "Fed"
                if self.evening_sprite_label.text != new_text:
                    self.evening_sprite_label.text = new_text
                    display_changed = True
        else:
            self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_RED
            if self.evening_sprite:
                if self.evening_sprite[0] != 0:
                    self.evening_sprite[0] = 0  # Show empty bowl
                    display_changed = True
            if self.evening_sprite_label:
                if self.evening_sprite_label.text != "Not fed":
                    self.evening_sprite_label.text = "Not fed"
                    display_changed = True

        # Show pixels (in case auto_write is False)
        self.pixels.show()

        # Always refresh on first update, otherwise based on changes
        if self.first_update:
            print("First status update - forcing display refresh")
            self.refresh_display()
            self.first_update = False
        elif display_changed or force_refresh:
            self.refresh_display()
        else:
            print("No display changes, skipping refresh")

    def refresh_display(self):
        """Safely refresh the e-ink display with rate limiting"""
        current_time = time.monotonic()

        # Increased minimum interval to prevent rapid refreshes
        if current_time - self.last_refresh >= 10:  # Changed from 5 to 10 seconds
            try:
                print("Refreshing display...")
                board.DISPLAY.refresh()
                self.last_refresh = current_time
                print("Display refreshed")
            except RuntimeError as e:
                # Handle "refresh too soon" errors
                if "too soon" in str(e).lower():
                    print(f"Display refresh skipped: {e}")
                else:
                    raise
        else:
            print(f"Skipping refresh, too soon (last: {current_time - self.last_refresh:.1f}s ago)")

    def check_time_window(self):
        """Check if device should be active or enter deep sleep"""
        # Get current time
        current = rtc.RTC().datetime
        now = datetime.datetime(
            current.tm_year, current.tm_mon, current.tm_mday,
            current.tm_hour, current.tm_min, current.tm_sec
        )

        seconds_to_sleep = 0
        sleep_reason = ""

        if now.hour < Config.MORNING_START:
            # Before morning window
            target = datetime.datetime(
                now.year, now.month, now.day,
                Config.MORNING_START, 0, 0
            )
            seconds_to_sleep = (target - now).total_seconds()
            sleep_reason = "before morning window"

        elif Config.MORNING_END <= now.hour < Config.EVENING_START:
            # Between windows
            target = datetime.datetime(
                now.year, now.month, now.day,
                Config.EVENING_START, 0, 0
            )
            seconds_to_sleep = (target - now).total_seconds()
            sleep_reason = "between feeding windows"

        elif now.hour >= Config.EVENING_END:
            # After evening window
            tomorrow = now + datetime.timedelta(days=1)
            target = datetime.datetime(
                tomorrow.year, tomorrow.month, tomorrow.day,
                Config.MORNING_START, 0, 0
            )
            seconds_to_sleep = (target - now).total_seconds()
            sleep_reason = "after evening window"

        if seconds_to_sleep > 60:  # Only sleep if more than 1 minute
            hours = seconds_to_sleep / 3600
            print(f"Entering deep sleep ({sleep_reason}) for {hours:.1f} hours")

            # Cleanup before sleep
            self.before_sleep()

            # Create time alarm for next wake
            time_alarm = alarm.time.TimeAlarm(
                monotonic_time=time.monotonic() + seconds_to_sleep
            )

            # Enter deep sleep
            alarm.exit_and_deep_sleep_until_alarms(time_alarm)

    def before_sleep(self):
        """Cleanup tasks before entering deep sleep"""
        print("Preparing for deep sleep...")

        # Turn off all NeoPixels to save power
        self.pixels.fill(Config.PIXEL_OFF)
        self.pixels.show()

        # Disconnect MQTT if connected
        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.disconnect()
                print("MQTT disconnected")
            except:
                pass

        # Force garbage collection
        gc.collect()

    def setup_panel(self, x_offset=0):
        """
        Create a display panel for morning or evening status
        Returns: (group, sprite, label)
        """
        group = displayio.Group()

        # Create tile grid for bowl sprite
        sprite = displayio.TileGrid(
            self.bowl_icon,
            pixel_shader=self.bowl_icon_pal,
            x=5 + x_offset,
            y=20,
            width=1,
            height=1,
            tile_width=140,
            tile_height=82,
            default_tile=0  # Start with empty bowl
        )
        group.append(sprite)

        # Create text label
        sprite_label = label.Label(
            terminalio.FONT,
            text="Not fed",
            color=0x000000,
            x=13 + x_offset,
            y=105  # Position below bowl sprite
        )
        group.append(sprite_label)

        return group, sprite, sprite_label

    def setup_display(self):
        """Initialize the e-ink display with background and panels"""
        print("Setting up display...")

        # Create main display group
        main_group = displayio.Group()

        # Load and add background
        try:
            background = displayio.OnDiskBitmap(Config.BACKGROUND_BMP)
            bg_sprite = displayio.TileGrid(
                background,
                pixel_shader=background.pixel_shader,
                x=0,
                y=0
            )
            main_group.append(bg_sprite)
        except Exception as e:
            print(f"Could not load background: {e}")

        # Create morning and evening panels
        morning_group, self.morning_sprite, self.morning_sprite_label = (
            self.setup_panel(Config.MORNING_X_OFFSET)
        )
        evening_group, self.evening_sprite, self.evening_sprite_label = (
            self.setup_panel(Config.EVENING_X_OFFSET)
        )

        # Add panels to main group
        main_group.append(morning_group)
        main_group.append(evening_group)

        # Show on display using root_group (CircuitPython 10)
        board.DISPLAY.root_group = main_group

        # Don't refresh here - let the first status update do it
        print("Display initialized (waiting for first status update to refresh)")

    def setup_mqtt_client(self):
        """Create and configure MQTT client"""
        print("Setting up MQTT client...")

        # Get MQTT settings from environment variables (settings.toml)
        mqtt_broker = os.getenv("MQTT_BROKER", "192.168.1.85")
        mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        mqtt_username = os.getenv("MQTT_USERNAME")
        mqtt_password = os.getenv("MQTT_PASSWORD")

        print(f"MQTT Broker: {mqtt_broker}:{mqtt_port}")

        self.mqtt_client = MQTT.MQTT(
            broker=mqtt_broker,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            socket_pool=self.pool,
            is_ssl=False,
            keep_alive=60  # CircuitPython 10 supports keep_alive
        )

        # Set callbacks
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

        # Add topic callbacks
        self.mqtt_client.add_topic_callback(
            Config.MQTT_MORNING_TOPIC,
            self.on_feeding_trigger
        )
        self.mqtt_client.add_topic_callback(
            Config.MQTT_EVENING_TOPIC,
            self.on_feeding_trigger
        )

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        print(f"Connected to MQTT Broker! (RC: {rc})")
        self.mqtt_connected = True

        # Subscribe to topics
        client.subscribe(Config.MQTT_MORNING_TOPIC)
        client.subscribe(Config.MQTT_EVENING_TOPIC)
        print(f"Subscribed to feeding topics")

    def on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        print(f"Disconnected from MQTT Broker (RC: {rc})")
        self.mqtt_connected = False

    def on_mqtt_message(self, client, topic, message):
        """General MQTT message callback"""
        print(f"Message on {topic}: {message}")

    def on_feeding_trigger(self, client, topic, message):
        """Feeding-specific MQTT trigger callback"""
        print(f"Feeding trigger on {topic}: {message}")

        # Fetch latest status from API
        status_data = self.fetch_dog_feed_status()
        if status_data:
            # Force refresh on MQTT trigger since something likely changed
            self.update_display_from_status(status_data, force_refresh=True)
        else:
            print("Failed to fetch status after MQTT trigger")

    def connect_mqtt(self):
        """
        Connect to MQTT broker with error handling
        Returns: True if connected, False otherwise
        """
        if not self.mqtt_client:
            return False

        try:
            print(f"Connecting to MQTT broker {self.mqtt_client.broker}...")
            self.mqtt_client.connect()
            self.mqtt_connected = True
            return True
        except Exception as e:
            print(f"MQTT connection failed: {e}")
            self.mqtt_connected = False
            return False

    def run(self):
        """Main run loop"""
        print("\n=== Dog Feeding Tracker Starting ===")
        print(f"CircuitPython {'.'.join(map(str, sys.implementation.version))}")

        # Check WiFi connection (CircuitPython auto-connects from settings.toml)
        if not self.connect_wifi():
            print("Failed to connect to WiFi, will retry after sleep...")
            time.sleep(30)
            microcontroller.reset()

        # Show network info
        print(f"Network: {wifi.radio.ap_info.ssid if wifi.radio.ap_info else 'Unknown'}")
        print(f"IP Address: {wifi.radio.ipv4_address}")
        print(f"Signal Strength: {wifi.radio.ap_info.rssi if wifi.radio.ap_info else 'Unknown'} dBm")

        # Create socket pool for network operations
        self.pool = socketpool.SocketPool(wifi.radio)

        # Initialize requests session
        self.requests = adafruit_requests.Session(
            self.pool,
            ssl.create_default_context()
        )

        # Set device time
        if not self.set_device_time():
            print("Warning: Could not sync device time")

        # Test network connectivity
        self.test_connectivity()

        # Initialize display
        self.setup_display()

        # Set initial NeoPixel state (red = not fed)
        self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_RED
        self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_RED
        self.pixels.show()

        # Set up MQTT
        self.setup_mqtt_client()
        self.connect_mqtt()

        # Fetch initial status
        print("\nFetching initial feeding status...")
        initial_status = self.fetch_dog_feed_status()
        if initial_status:
            self.update_display_from_status(initial_status, force_refresh=True)

        print("\nEntering main loop...")

        # Main loop
        while True:
            try:
                # Check if we should sleep (outside feeding windows)
                # Temporarily disabled for testing
                # self.check_time_window()

                # Periodic time sync
                if time.monotonic() - self.last_sync > Config.TIME_SYNC_INTERVAL:
                    print("\nSyncing device time...")
                    if self.set_device_time():
                        self.last_sync = time.monotonic()

                # Handle MQTT
                if self.mqtt_client:
                    if self.mqtt_connected:
                        try:
                            # Non-blocking loop with timeout
                            self.mqtt_client.loop(timeout=Config.MQTT_LOOP_TIMEOUT)
                        except Exception as e:
                            print(f"MQTT loop error: {e}")
                            self.mqtt_connected = False
                    else:
                        # Try to reconnect
                        self.connect_mqtt()

                # Periodic status fetch (fallback)
                if time.monotonic() - self.last_status_fetch > Config.STATUS_FETCH_INTERVAL:
                    print("\nPeriodic status check...")
                    status_data = self.fetch_dog_feed_status()
                    if status_data:
                        # Don't force refresh for periodic updates
                        self.update_display_from_status(status_data, force_refresh=False)
                    self.last_status_fetch = time.monotonic()

                # Check connection health
                if self.connection_failures > Config.CONNECTION_FAILURE_THRESHOLD:
                    print(f"\nToo many failures ({self.connection_failures}), resetting...")
                    microcontroller.reset()

                # Free up memory periodically
                gc.collect()

                # Small delay to prevent tight loop
                time.sleep(3)

            except MemoryError as e:
                print(f"Memory error: {e}")
                gc.collect()
                time.sleep(5)

            except Exception as e:
                print(f"Main loop error: {e}")
                time.sleep(5)


# Check if we're waking from deep sleep
print("\n" + "="*50)
if alarm.wake_alarm:
    print("Woke from deep sleep!")
else:
    print("Fresh start (not from deep sleep)")

# Import sys for version info
import sys

# Run the tracker
def main():
    """Entry point for the dog feeding tracker"""
    try:
        tracker = DogFeedingTracker()
        tracker.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        # Wait before reset to allow reading error
        time.sleep(10)
        microcontroller.reset()


if __name__ == '__main__':
    main()
