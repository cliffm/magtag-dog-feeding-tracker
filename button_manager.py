"""
Button Manager for Dog Feeding Tracker
Handles the 4 MagTag buttons (D11-D15) for manual feeding status control
"""

import board
import time
from digitalio import DigitalInOut, Direction, Pull
from config import Config


class ButtonManager:
    """Manages the 4 MagTag buttons for feeding control"""

    # Button pins on MagTag (left to right when viewing from front)
    BUTTON_PINS = [board.D15, board.D14, board.D12, board.D11]

    # Button actions
    BUTTON_MORNING_FED = 0      # D15 - leftmost
    BUTTON_MORNING_CLEAR = 1   # D14
    BUTTON_EVENING_FED = 2     # D12
    BUTTON_EVENING_CLEAR = 3   # D11 - rightmost

    # Debounce settings
    DEBOUNCE_DELAY = 0.2  # seconds

    def __init__(self, network_manager, display_manager):
        """
        Initialize button handler

        Args:
            network_manager: NetworkManager instance for MQTT publishing
            display_manager: DisplayManager instance for LED feedback
        """
        self.network = network_manager
        self.display = display_manager
        self.buttons = []
        self.last_press_time = [0] * 4

        # Initialize buttons
        for pin in self.BUTTON_PINS:
            button = DigitalInOut(pin)
            button.direction = Direction.INPUT
            button.pull = Pull.UP
            self.buttons.append(button)

        print("ButtonManager initialized (4 buttons ready)")
        print("  D15: Morning Fed | D14: Morning Clear")
        print("  D12: Evening Fed | D11: Evening Clear")

    def check_buttons(self):
        """
        Check all buttons and handle presses

        Returns: True if any button was pressed
        """
        current_time = time.monotonic()
        button_pressed = False

        for i, button in enumerate(self.buttons):
            # Buttons are active LOW (pressed = False)
            if not button.value:
                # Check debounce
                if current_time - self.last_press_time[i] > self.DEBOUNCE_DELAY:
                    self.last_press_time[i] = current_time
                    self._handle_button_press(i)
                    button_pressed = True

                    # Wait for button release to prevent repeat triggers
                    while not button.value:
                        time.sleep(0.01)

        return button_pressed

    def _handle_button_press(self, button_index):
        """Handle a specific button press"""
        print(f"\nButton {button_index} pressed (D{self.BUTTON_PINS[button_index]})")

        # Flash the appropriate LED to indicate button press
        self._flash_feedback(button_index)

        if button_index == self.BUTTON_MORNING_FED:
            self._set_morning_fed()
        elif button_index == self.BUTTON_MORNING_CLEAR:
            self._clear_morning_fed()
        elif button_index == self.BUTTON_EVENING_FED:
            self._set_evening_fed()
        elif button_index == self.BUTTON_EVENING_CLEAR:
            self._clear_evening_fed()

    def _flash_feedback(self, button_index):
        """Provide visual feedback via NeoPixels"""
        # Determine which pixel to flash based on button
        if button_index in (self.BUTTON_MORNING_FED, self.BUTTON_MORNING_CLEAR):
            pixel_index = Config.MORNING_PIXEL
        else:
            pixel_index = Config.EVENING_PIXEL

        # Store current color
        original_color = self.display.pixels[pixel_index]

        # Quick flash (white -> original)
        self.display.pixels[pixel_index] = (50, 50, 50)  # White flash
        self.display.pixels.show()
        time.sleep(0.1)
        self.display.pixels[pixel_index] = original_color
        self.display.pixels.show()

    def _set_morning_fed(self):
        """Publish morning fed status"""
        print("Setting morning as FED")
        success = self.network.publish_feeding_status(
            Config.MQTT_MORNING_TOPIC,
            fed=True
        )
        if success:
            print("Morning fed status published")
        else:
            print("Failed to publish morning status")
            self._error_flash()

    def _clear_morning_fed(self):
        """Clear morning fed status"""
        print("Clearing morning (NOT FED)")
        success = self.network.publish_feeding_status(
            Config.MQTT_MORNING_TOPIC,
            fed=False
        )
        if success:
            print("Morning cleared")
        else:
            print("Failed to clear morning status")
            self._error_flash()

    def _set_evening_fed(self):
        """Publish evening fed status"""
        print("Setting evening as FED")
        success = self.network.publish_feeding_status(
            Config.MQTT_EVENING_TOPIC,
            fed=True
        )
        if success:
            print("Evening fed status published")
        else:
            print("Failed to publish evening status")
            self._error_flash()

    def _clear_evening_fed(self):
        """Clear evening fed status"""
        print("Clearing evening (NOT FED)")
        success = self.network.publish_feeding_status(
            Config.MQTT_EVENING_TOPIC,
            fed=False
        )
        if success:
            print("Evening cleared")
        else:
            print("Failed to clear evening status")
            self._error_flash()

    def _error_flash(self):
        """Flash red to indicate an error"""
        # Flash all pixels red briefly
        original_colors = [self.display.pixels[i] for i in range(Config.PIXEL_COUNT)]

        for _ in range(3):
            self.display.pixels.fill(Config.PIXEL_RED)
            self.display.pixels.show()
            time.sleep(0.1)
            self.display.pixels.fill(Config.PIXEL_OFF)
            self.display.pixels.show()
            time.sleep(0.1)

        # Restore original colors
        for i, color in enumerate(original_colors):
            self.display.pixels[i] = color
        self.display.pixels.show()
