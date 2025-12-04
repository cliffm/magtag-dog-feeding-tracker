"""
Network Manager for Dog Feeding Tracker
Handles WiFi, MQTT, and HTTP API communications
"""

import os
import ssl
import time
import wifi
import socketpool
import rtc
import adafruit_ntp
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import adafruit_requests
from config import Config


class NetworkManager:
    """Manages all network communications"""

    def __init__(self, on_feeding_trigger=None):
        """Initialize network components"""
        self.pool = None
        self.requests = None
        self.mqtt_client = None
        self.mqtt_connected = False
        self.connection_failures = 0
        self.on_feeding_trigger = on_feeding_trigger

    def connect_wifi(self, max_attempts=Config.MAX_RETRIES):
        """
        Verify WiFi connection (CircuitPython auto-connects from settings.toml)
        Returns: True if connected
        """
        for attempt in range(max_attempts):
            try:
                if wifi.radio.connected:
                    print(f"WiFi connected! IP: {wifi.radio.ipv4_address}")
                    self.connection_failures = 0

                    # Create socket pool
                    self.pool = socketpool.SocketPool(wifi.radio)

                    # Initialize requests session
                    self.requests = adafruit_requests.Session(
                        self.pool,
                        ssl.create_default_context()
                    )

                    # Show network info
                    if wifi.radio.ap_info:
                        print(f"Network: {wifi.radio.ap_info.ssid}")
                        print(f"Signal: {wifi.radio.ap_info.rssi} dBm")

                    return True
                else:
                    print(f"Waiting for WiFi (attempt {attempt + 1}/{max_attempts})...")
                    time.sleep(2)

            except Exception as e:
                print(f"WiFi error: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(Config.RETRY_DELAY)

        self.connection_failures += 1
        print("Failed to connect to WiFi")
        return False

    def ensure_wifi_connected(self):
        """Check and maintain WiFi connection"""
        if not wifi.radio.connected:
            print("WiFi disconnected, attempting to reconnect...")
            return self.connect_wifi()
        return True

    def sync_time(self):
        print("Syncing time via NTP...")

        try:
            pool = socketpool.SocketPool(wifi.radio)
            ntp = adafruit_ntp.NTP(pool, server="pool.ntp.org", tz_offset=-5)  # EST offset
            now = ntp.datetime

            print("Raw NTP time:", now)

            rtc.RTC().datetime = now
            print("NTP sync OK")
            return True

        except Exception as e:
            print("NTP sync failed:", e)
            return False

        return False

    def fetch_dog_feed_status(self):
        """
        Fetch feeding status from REST API
        Returns: Dict with 'morning' and 'evening' keys or None
        """
        if not self.ensure_wifi_connected():
            return None

        for attempt in range(Config.MAX_RETRIES):
            try:
                if not self.requests:
                    return None

                print(f"Fetching status (attempt {attempt + 1}/{Config.MAX_RETRIES})...")
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
                    print(f"API returned status: {response.status_code}")
                    if response.text:
                        print(f"Response: {response.text[:200]}")

            except Exception as e:
                print(f"Error fetching status: {e}")
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(Config.RETRY_DELAY)

        return None

    def setup_mqtt(self):
        """Initialize MQTT client"""
        if not self.pool:
            print("No socket pool available for MQTT")
            return False

        print("Setting up MQTT client...")

        # Get MQTT settings from environment
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
            keep_alive=60
        )

        # Set callbacks
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self.mqtt_client.on_message = self._on_mqtt_message

        # Add topic callbacks
        self.mqtt_client.add_topic_callback(
            Config.MQTT_MORNING_TOPIC,
            self._on_feeding_message
        )
        self.mqtt_client.add_topic_callback(
            Config.MQTT_EVENING_TOPIC,
            self._on_feeding_message
        )

        return True

    def connect_mqtt(self):
        """Connect to MQTT broker"""
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

    def loop_mqtt(self):
        """Process MQTT messages"""
        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.loop(timeout=Config.MQTT_LOOP_TIMEOUT)
            except Exception as e:
                print(f"MQTT loop error: {e}")
                self.mqtt_connected = False
                return False
        elif self.mqtt_client:
            # Try to reconnect
            return self.connect_mqtt()
        return False

    def publish_feeding_status(self, topic, fed=True):
        """
        Publish feeding status to MQTT topic

        Args:
            topic: MQTT topic to publish to
            fed: True for fed (sends timestamp), False for not fed

        Returns: True if published successfully
        """
        if not self.mqtt_client:
            print("MQTT client not initialized")
            return False

        if not self.mqtt_connected:
            print("MQTT not connected, attempting reconnect...")
            if not self.connect_mqtt():
                return False

        try:
            # Determine message payload
            if fed:
                # Generate timestamp in "H:MM:SS am/pm" format
                message = self._get_current_timestamp()
            else:
                # Use configured payload for clearing, default to empty string
                message = getattr(Config, 'MQTT_NOT_FED_PAYLOAD', '')

            print(f"Publishing to {topic}: {message}")
            self.mqtt_client.publish(topic, message)
            print(f"Published successfully")
            return True

        except Exception as e:
            print(f"MQTT publish error: {e}")
            self.mqtt_connected = False
            return False

    def _get_current_timestamp(self):
        """
        Get current time as timestamp string in "H:MM:SS am/pm" format
        Example: "5:45:50 pm"
        """
        current = rtc.RTC().datetime

        hour = current.tm_hour
        minute = current.tm_min
        second = current.tm_sec

        # Convert to 12-hour format
        if hour == 0:
            hour_12 = 12
            period = "am"
        elif hour < 12:
            hour_12 = hour
            period = "am"
        elif hour == 12:
            hour_12 = 12
            period = "pm"
        else:
            hour_12 = hour - 12
            period = "pm"

        # Format: "H:MM:SS am/pm" (no leading zero on hour)
        timestamp = f"{hour_12}:{minute:02d}:{second:02d} {period}"
        return timestamp

    def disconnect_mqtt(self):
        """Disconnect MQTT client"""
        if self.mqtt_client and self.mqtt_connected:
            try:
                self.mqtt_client.disconnect()
                print("MQTT disconnected")
            except:
                pass
            self.mqtt_connected = False

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        print(f"Connected to MQTT Broker! (RC: {rc})")
        self.mqtt_connected = True

        # Subscribe to topics
        client.subscribe(Config.MQTT_MORNING_TOPIC)
        client.subscribe(Config.MQTT_EVENING_TOPIC)
        print("Subscribed to feeding topics")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        print(f"Disconnected from MQTT (RC: {rc})")
        self.mqtt_connected = False

    def _on_mqtt_message(self, client, topic, message):
        """General MQTT message callback"""
        print(f"Message on {topic}: {message}")

    def _on_feeding_message(self, client, topic, message):
        """Feeding-specific MQTT message callback"""
        print(f"Feeding trigger on {topic}: {message}")

        # Call the external handler if provided
        if self.on_feeding_trigger:
            self.on_feeding_trigger(topic, message)

    def test_connectivity(self):
        """Test network connectivity to various endpoints"""
        if not self.requests:
            print("Requests session not initialized")
            return

        print("\n=== Testing Network Connectivity ===")

        mqtt_broker = os.getenv("MQTT_BROKER", "192.168.1.85")

        test_urls = [
            ("Dog Feed API", Config.DOG_FEED_STATUS_URL),
            ("MQTT HTTP", f"http://{mqtt_broker}:1880/")
        ]

        for name, url in test_urls:
            try:
                print(f"Testing {name}: {url}")
                response = self.requests.get(url, timeout=5)
                print(f"  ✓ {name} reachable (status: {response.status_code})")
            except Exception as e:
                print(f"  ✗ {name} not reachable: {e}")

        print("=== Connectivity Test Complete ===\n")

    def check_connection_health(self):
        """Check if connections are healthy"""
        return self.connection_failures <= Config.CONNECTION_FAILURE_THRESHOLD
