"""
Display Manager for Dog Feeding Tracker
Handles all e-ink display and NeoPixel operations
"""

import time
import board
import displayio
import terminalio
import neopixel
import adafruit_imageload
from adafruit_display_text import label
from config import Config


class DisplayManager:
    """Manages the e-ink display and NeoPixel indicators"""

    def __init__(self):
        """Initialize display components"""
        # NeoPixels
        self.pixels = neopixel.NeoPixel(
            board.NEOPIXEL,
            Config.PIXEL_COUNT,
            brightness=Config.PIXEL_BRIGHTNESS,
            auto_write=True
        )

        # Display sprites and labels
        self.morning_sprite = None
        self.morning_sprite_label = None
        self.evening_sprite = None
        self.evening_sprite_label = None

        # Tracking
        self.last_refresh = 0
        self.first_update = True

        # Load bowl sprites
        self.bowl_icon, self.bowl_icon_pal = adafruit_imageload.load(
            Config.BOWL_SPRITE_BMP
        )
        print("Bowl sprites loaded successfully")

    def setup(self):
        """Initialize the e-ink display"""
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
            # Create white background as fallback
            self._create_fallback_background(main_group)

        # Create morning and evening panels
        morning_group = self._create_panel(Config.MORNING_X_OFFSET, is_morning=True)
        evening_group = self._create_panel(Config.EVENING_X_OFFSET, is_morning=False)

        main_group.append(morning_group)
        main_group.append(evening_group)

        # Show on display
        board.DISPLAY.root_group = main_group

        # Set initial LED states
        self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_RED
        self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_RED
        self.pixels.show()

        print("Display initialized (waiting for first status update)")

    def _create_panel(self, x_offset, is_morning):
        """Create a display panel for morning or evening status"""
        group = displayio.Group()

        # Create bowl sprite
        sprite = displayio.TileGrid(
            self.bowl_icon,
            pixel_shader=self.bowl_icon_pal,
            x=Config.BOWL_SPRITE_X + x_offset,
            y=Config.BOWL_SPRITE_Y,
            width=1,
            height=1,
            tile_width=Config.BOWL_TILE_WIDTH,
            tile_height=Config.BOWL_TILE_HEIGHT,
            default_tile=0  # Start with empty bowl
        )
        group.append(sprite)

        # Create text label
        sprite_label = label.Label(
            terminalio.FONT,
            text="Not fed",
            color=0x000000,
            x=Config.TEXT_X_OFFSET + x_offset,
            y=Config.TEXT_Y_POSITION
        )
        group.append(sprite_label)

        # Store references
        if is_morning:
            self.morning_sprite = sprite
            self.morning_sprite_label = sprite_label
        else:
            self.evening_sprite = sprite
            self.evening_sprite_label = sprite_label

        return group

    def _create_fallback_background(self, group):
        """Create a simple white background if image loading fails"""
        white_palette = displayio.Palette(1)
        white_palette[0] = 0xFFFFFF  # White

        white_bg = displayio.TileGrid(
            displayio.Bitmap(Config.DISPLAY_WIDTH, Config.DISPLAY_HEIGHT, 1),
            pixel_shader=white_palette,
            x=0,
            y=0
        )
        group.append(white_bg)

    def update_status(self, morning_status, evening_status, force_refresh=False):
        """
        Update display based on feeding status
        Returns: True if display was refreshed
        """
        display_changed = False

        # Update morning
        display_changed |= self._update_morning(morning_status)

        # Update evening
        display_changed |= self._update_evening(evening_status)

        # Update pixels
        self.pixels.show()

        # Refresh display if needed
        if self.first_update:
            print("First status update - forcing display refresh")
            self.refresh_display()
            self.first_update = False
            return True
        elif display_changed or force_refresh:
            self.refresh_display()
            return True
        else:
            print("No display changes, skipping refresh")
            return False

    def _update_morning(self, status):
        """Update morning display and return True if changed"""
        changed = False

        if status:
            # Fed - green light, filled bowl
            self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_GREEN

            if self.morning_sprite and self.morning_sprite[0] != 1:
                self.morning_sprite[0] = 1
                changed = True

            if self.morning_sprite_label:
                new_text = f"Fed at {self._parse_time(status)}" if status != True else "Fed"
                if self.morning_sprite_label.text != new_text:
                    self.morning_sprite_label.text = new_text
                    changed = True
        else:
            # Not fed - red light, empty bowl
            self.pixels[Config.MORNING_PIXEL] = Config.PIXEL_RED

            if self.morning_sprite and self.morning_sprite[0] != 0:
                self.morning_sprite[0] = 0
                changed = True

            if self.morning_sprite_label and self.morning_sprite_label.text != "Not fed":
                self.morning_sprite_label.text = "Not fed"
                changed = True

        return changed

    def _update_evening(self, status):
        """Update evening display and return True if changed"""
        changed = False

        if status:
            # Fed - green light, filled bowl
            self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_GREEN

            if self.evening_sprite and self.evening_sprite[0] != 1:
                self.evening_sprite[0] = 1
                changed = True

            if self.evening_sprite_label:
                new_text = f"Fed at {self._parse_time(status)}" if status != True else "Fed"
                if self.evening_sprite_label.text != new_text:
                    self.evening_sprite_label.text = new_text
                    changed = True
        else:
            # Not fed - red light, empty bowl
            self.pixels[Config.EVENING_PIXEL] = Config.PIXEL_RED

            if self.evening_sprite and self.evening_sprite[0] != 0:
                self.evening_sprite[0] = 0
                changed = True

            if self.evening_sprite_label and self.evening_sprite_label.text != "Not fed":
                self.evening_sprite_label.text = "Not fed"
                changed = True

        return changed

    def _parse_time(self, timestamp_str):
        """Parse timestamp to HH:MM format"""
        if not timestamp_str or timestamp_str == True:
            return None

        try:
            if 'T' in str(timestamp_str):
                # ISO format - extract time
                time_part = timestamp_str.split('T')[1]
                time_part = time_part.split('.')[0].split('Z')[0]
                hour, minute = time_part.split(':')[:2]
                return f"{hour}:{minute}"
            return str(timestamp_str)
        except Exception as e:
            print(f"Error parsing time '{timestamp_str}': {e}")
            return str(timestamp_str)

    def refresh_display(self):
        """Safely refresh the e-ink display with rate limiting"""
        current_time = time.monotonic()

        if current_time - self.last_refresh >= Config.DISPLAY_REFRESH_MIN_INTERVAL:
            try:
                print("Refreshing display...")
                board.DISPLAY.refresh()
                self.last_refresh = current_time
                print("Display refreshed")
            except RuntimeError as e:
                if "too soon" in str(e).lower():
                    print(f"Display refresh skipped: {e}")
                else:
                    raise
        else:
            time_since = current_time - self.last_refresh
            print(f"Skipping refresh, too soon (last: {time_since:.1f}s ago)")

    def shutdown(self):
        """Turn off displays before sleep"""
        print("Shutting down display...")
        self.pixels.fill(Config.PIXEL_OFF)
        self.pixels.show()
