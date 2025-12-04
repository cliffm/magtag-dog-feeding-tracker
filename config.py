"""
Configuration constants for Dog Feeding Tracker
All timing, display, and hardware settings in one place
"""

import os


class Config:
    """Configuration settings for the dog feeding tracker"""

    # Time windows (24-hour format)
    MORNING_START = 7
    MORNING_END = 11
    EVENING_START = 16
    EVENING_END = 21

    # Get API URL from settings.toml or use default
    DOG_FEED_STATUS_URL = os.getenv("DOG_FEED_API", "http://192.168.1.85:1880/dog-feed-status")

    # MQTT topics
    MQTT_MORNING_TOPIC = 'dog/fed/morning'
    MQTT_EVENING_TOPIC = 'dog/fed/evening'

    # MQTT payload for clearing fed status (fed status uses current timestamp)
    # Set to empty string, "false", or whatever your backend expects
    MQTT_NOT_FED_PAYLOAD = os.getenv("MQTT_NOT_FED_PAYLOAD", "")

    # Refresh intervals (seconds)
    TIME_SYNC_INTERVAL = 3600  # 1 hour
    STATUS_FETCH_INTERVAL = 300  # 5 minutes
    DISPLAY_REFRESH_MIN_INTERVAL = 10  # Minimum time between display refreshes
    MQTT_LOOP_TIMEOUT = 1.0  # MQTT loop timeout (must be >= socket timeout)

    # Retry settings
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    CONNECTION_FAILURE_THRESHOLD = 5
    HTTP_TIMEOUT = 5  # Reduced timeout for faster failures

    # NeoPixel settings (MagTag has 4 NeoPixels)
    PIXEL_COUNT = 4
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

    # Display dimensions (MagTag)
    DISPLAY_WIDTH = 296
    DISPLAY_HEIGHT = 128

    # Bowl sprite dimensions
    BOWL_TILE_WIDTH = 140
    BOWL_TILE_HEIGHT = 82
    BOWL_SPRITE_X = 5
    BOWL_SPRITE_Y = 20

    # Text positioning
    TEXT_X_OFFSET = 13
    TEXT_Y_POSITION = 105  # Below bowl sprite
