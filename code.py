"""
Dog Feeding Tracker for Adafruit MagTag
Main application file - coordinates all components
CircuitPython 10.x compatible
"""

import gc
import sys
import time
import alarm
import microcontroller
import rtc
import adafruit_datetime as datetime

from config import Config
from display_manager import DisplayManager
from network_manager import NetworkManager
from button_manager import ButtonManager


class DogFeedingTracker:
    """Main application class"""

    def __init__(self, woke_from_sleep=False):
        """Initialize the tracker"""
        print("\n=== Dog Feeding Tracker Starting ===")
        print(f"CircuitPython {'.'.join(map(str, sys.implementation.version))}")

        # Track if we woke from deep sleep
        self.woke_from_sleep = woke_from_sleep

        # Components
        self.display = DisplayManager()
        self.network = NetworkManager(on_feeding_trigger=self.on_feeding_trigger)
        self.buttons = None  # Initialized after setup

        # Timing
        self.last_sync = 0
        self.last_status_fetch = 0

    def on_feeding_trigger(self, topic, message):
        """Handle MQTT feeding trigger"""
        # Fetch latest status from API
        status_data = self.network.fetch_dog_feed_status()
        if status_data:
            # Force refresh on MQTT trigger
            self.display.update_status(
                status_data.get('morning'),
                status_data.get('evening'),
                force_refresh=True
            )
        else:
            print("Failed to fetch status after MQTT trigger")

    def check_sleep_schedule(self):
        """Check if device should enter deep sleep"""
        # Get current time
        current = rtc.RTC().datetime
        now = datetime.datetime(
            current.tm_year, current.tm_mon, current.tm_mday,
            current.tm_hour, current.tm_min, current.tm_sec
        )

        print(f"Sleep check - Time: {now.hour:02d}:{now.minute:02d}:{now.second:02d}", end="")
        print(
            f" (Hours: Morning {Config.MORNING_START}-{Config.MORNING_END}, Evening {Config.EVENING_START}-{Config.EVENING_END})")

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
            self.enter_deep_sleep(seconds_to_sleep, sleep_reason)

    def enter_deep_sleep(self, seconds, reason):
        """Enter deep sleep mode"""
        hours = seconds / 3600
        print(f"\n{'=' * 50}")
        print(f"ENTERING DEEP SLEEP")
        print(f"Reason: {reason}")
        print(f"Duration: {hours:.1f} hours ({seconds:.0f} seconds)")
        print(f"Display will remain visible, LEDs will turn off")
        print(f"{'=' * 50}\n")

        # Turn off LEDs only (display persists on e-ink)
        self.display.shutdown()

        # Give LEDs time to actually turn off
        time.sleep(0.5)

        # Disconnect network
        print("Disconnecting network...")
        self.network.disconnect_mqtt()

        # Clean up memory
        gc.collect()

        print("Creating wake alarm and entering deep sleep NOW...")

        # Create time alarm
        time_alarm = alarm.time.TimeAlarm(
            monotonic_time=time.monotonic() + seconds
        )

        # Enter deep sleep
        alarm.exit_and_deep_sleep_until_alarms(time_alarm)

    def setup(self):
        """Initialize all components"""
        # Show startup animation first
        self.display.startup_animation()

        # Connect to WiFi
        if not self.network.connect_wifi():
            print("Failed to connect to WiFi, will retry after reset...")
            time.sleep(30)
            microcontroller.reset()

        # Sync time
        if not self.network.sync_time():
            print("Warning: Could not sync device time")

        # Test connectivity
        self.network.test_connectivity()

        # Setup display
        self.display.setup()

        # Setup MQTT
        if self.network.setup_mqtt():
            self.network.connect_mqtt()

        # Initialize button manager (after network and display are ready)
        self.buttons = ButtonManager(self.network, self.display)

        # Fetch initial status
        print("\nFetching initial feeding status...")
        initial_status = self.network.fetch_dog_feed_status()
        if initial_status:
            # Always force refresh on startup, especially after deep sleep wake
            self.display.update_status(
                initial_status.get('morning'),
                initial_status.get('evening'),
                force_refresh=True
            )
        elif self.woke_from_sleep:
            # Even if fetch failed, force a display refresh after deep sleep
            # to ensure the display is updated with current state
            print("Status fetch failed but forcing refresh after deep sleep wake")
            self.display.refresh_display()

        # If we woke from deep sleep, do an extra explicit refresh
        # This ensures the e-ink display is fully updated after potentially
        # many hours of sleep
        if self.woke_from_sleep:
            print("\n*** Woke from deep sleep - ensuring display is refreshed ***")
            # Small delay to let any pending display operations complete
            time.sleep(1)
            # Force another refresh to ensure display is current
            self.display.refresh_display()

    def run(self):
        """Main application loop"""
        self.setup()

        print("\nEntering main loop...")
        print("=" * 50)

        while True:
            try:
                self.check_sleep_schedule()

                # Periodic time sync
                if time.monotonic() - self.last_sync > Config.TIME_SYNC_INTERVAL:
                    print("\nSyncing device time...")
                    if self.network.sync_time():
                        self.last_sync = time.monotonic()

                # Handle MQTT
                self.network.loop_mqtt()

                # Periodic status fetch
                if time.monotonic() - self.last_status_fetch > Config.STATUS_FETCH_INTERVAL:
                    print("\nPeriodic status check...")
                    status_data = self.network.fetch_dog_feed_status()
                    if status_data:
                        self.display.update_status(
                            status_data.get('morning'),
                            status_data.get('evening'),
                            force_refresh=False
                        )
                    self.last_status_fetch = time.monotonic()

                # Check connection health
                if not self.network.check_connection_health():
                    print(f"\nToo many connection failures, resetting...")
                    microcontroller.reset()

                # Free memory periodically
                if time.monotonic() % 300 < 3:  # Every 5 minutes
                    gc.collect()

                # Poll for button presses during wait period
                # This replaces the simple sleep(3) to catch button presses
                wait_end = time.monotonic() + 3
                while time.monotonic() < wait_end:
                    if self.buttons and self.buttons.check_buttons():
                        # Button was pressed, brief pause then continue
                        time.sleep(0.3)
                    time.sleep(0.05)  # 50ms polling interval

            except MemoryError as e:
                print(f"Memory error: {e}")
                gc.collect()
                time.sleep(5)

            except KeyboardInterrupt:
                print("\n\nShutdown requested...")
                self.display.shutdown()
                self.network.disconnect_mqtt()
                break

            except Exception as e:
                print(f"Main loop error: {e}")
                time.sleep(5)


def main():
    """Entry point"""
    # Check if waking from deep sleep
    print("\n" + "=" * 50)
    woke_from_sleep = False
    if alarm.wake_alarm:
        print("Woke from deep sleep!")
        woke_from_sleep = True
    else:
        print("Fresh start (not from deep sleep)")

    try:
        tracker = DogFeedingTracker(woke_from_sleep=woke_from_sleep)
        tracker.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        # Wait before reset to allow reading error
        time.sleep(10)
        microcontroller.reset()


if __name__ == '__main__':
    main()