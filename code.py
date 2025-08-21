import errno

import alarm  # for deep sleep
import json
import ssl
import time
import board
import rtc  # real time clock - set the time on the device
import displayio
import terminalio
import socketpool
import neopixel
import wifi
import adafruit_datetime as datetime
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import adafruit_requests
import adafruit_imageload
from adafruit_display_text import label

from secrets import secrets

last_refresh = None

# URL for time API
TIME_URL = "http://worldtimeapi.org/api/timezone/America/New_York"
# URL for dog feeding status
DOG_FEED_STATUS_URL = "http://ha-server2:1880/dog-feed-status"

# bitmap locations
BACKGROUND = "/bmps/background.bmp"
BOWL_SPRITE = "/bmps/bowl_tile.bmp"

# needs to be a global, so it's accessible from mqtt callbacks
pixels = neopixel.NeoPixel(board.NEOPIXEL, 4, brightness=0.05)

# globals for updating the status
morning_sprite = None
morning_sprite_label = None
evening_sprite = None
evening_sprite_label = None

# global requests session
requests = None

# neopixel colors
RED = (150, 0, 0)  # less intense red
GREEN = (0, 150, 0)  # less intense green


# hours on a 24 hour clock
class TimeWindow():
    MORNING_START = 7
    MORNING_END = 11
    EVENING_START = 16
    EVENING_END = 21


# bowl icon and palette
bowl_icon, bowl_icon_pal = adafruit_imageload.load(BOWL_SPRITE)

# mqtt topics - now used as triggers only
dog_fed_morning_topic = 'dog/fed/morning'
dog_fed_evening_topic = 'dog/fed/evening'


def set_device_time(pool):
    """connect to webservice, and get time information (JSON), and set device Real Time Clock"""
    global requests
    try:
        # call webservice
        if not requests:
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
        response = requests.get(TIME_URL)

        # parse JSON data
        data = json.loads(response.text)

        d = datetime.datetime.fromisoformat(data['datetime'])
        day_of_year = data['day_of_year']
        dst = data['dst']
        now = time.struct_time((
            d.year,
            d.month,
            d.day,
            d.hour,
            d.minute,
            d.second,
            d.weekday(),
            day_of_year,
            dst))

        if rtc is not None:
            rtc.RTC().datetime = now
    except Exception as e:
        print(f"Error setting device time: {e}")
        pass


def fetch_dog_feed_status():
    """Fetch dog feeding status from REST API"""
    global requests
    try:
        if not requests:
            return None

        print("Fetching dog feed status from API...")
        response = requests.get(DOG_FEED_STATUS_URL)

        if response.status_code == 200:
            data = json.loads(response.text)
            return data.get('dog_feed_status', {})
        else:
            print(f"API returned status code: {response.status_code}")
            return None

    except Exception as e:
        print(f"Error fetching dog feed status: {e}")
        return None


def update_display_from_status(status_data):
    """Update the display based on the API response"""
    global morning_sprite, morning_sprite_label
    global evening_sprite, evening_sprite_label
    global last_refresh

    if not status_data:
        print("No status data available")
        return

    morning_status = status_data.get('morning')
    evening_status = status_data.get('evening')

    # Update morning status
    if morning_status:
        pixels[3] = GREEN
        morning_sprite[0] = 1
        # Extract time from the status if it's a timestamp, otherwise use as-is
        display_time = morning_status
        if 'T' in morning_status:  # ISO format timestamp
            try:
                dt = datetime.datetime.fromisoformat(morning_status.replace('Z', '+00:00'))
                display_time = dt.strftime('%H:%M')
            except:
                pass
        morning_sprite_label.text = f"Fed at {display_time}"
    else:
        pixels[3] = RED
        morning_sprite[0] = 0
        morning_sprite_label.text = "Not fed"

    # Update evening status
    if evening_status:
        pixels[0] = GREEN
        evening_sprite[0] = 1
        # Extract time from the status if it's a timestamp, otherwise use as-is
        display_time = evening_status
        if 'T' in evening_status:  # ISO format timestamp
            try:
                dt = datetime.datetime.fromisoformat(evening_status.replace('Z', '+00:00'))
                display_time = dt.strftime('%H:%M')
            except:
                pass
        evening_sprite_label.text = f"Fed at {display_time}"
    else:
        pixels[0] = RED
        evening_sprite[0] = 0
        evening_sprite_label.text = "Not fed"

    # Refresh display with rate limiting
    now = time.time()
    if not last_refresh or now > last_refresh + 5:
        board.DISPLAY.refresh()
        last_refresh = time.time()
        print("Display updated")


def check_time_window():
    """checks current time to see if device should be "on", or set to deep sleep"""
    now = datetime.datetime.now()

    morning = datetime.time(TimeWindow.MORNING_START, 0, 0)
    evening = datetime.time(TimeWindow.EVENING_START, 0, 0)

    seconds = 0
    if now.hour < TimeWindow.MORNING_START:
        target = datetime.datetime.combine(now, morning)
        diff = target - now
        seconds = diff.total_seconds()
    elif now.hour >= TimeWindow.MORNING_END and now.hour < TimeWindow.EVENING_START:
        target = datetime.datetime.combine(now, evening)
        diff = target - now
        seconds = diff.total_seconds()
    elif now.hour >= TimeWindow.EVENING_END:
        print("It is time to sleep!")

        tomorrow = now + datetime.timedelta(days=1)
        tomorrow = datetime.datetime.combine(tomorrow, morning)

        diff = tomorrow - now
        seconds = diff.total_seconds()

    if seconds > 0:
        print(f"Sleeping for {seconds} seconds.")
        # Create a an alarm that will trigger some amount of seconds from now.
        time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + seconds)
        # Exit the program, and then deep sleep until the alarm wakes us.
        alarm.exit_and_deep_sleep_until_alarms(time_alarm)


def setup_panel(x_offset=0):
    sprite = displayio.TileGrid(
        bowl_icon,
        pixel_shader=bowl_icon_pal,
        x=5 + x_offset,
        y=20,
        width=1,
        height=1,
        tile_width=140,
        tile_height=82,
    )

    sprite_label = label.Label(terminalio.FONT, text="Not fed", color=0x000000)
    sprite_label.anchor_point = (0, 0)
    sprite_label.anchored_position = (13 + x_offset, 95)

    group = displayio.Group()
    group.append(sprite)
    group.append(sprite_label)

    return group, sprite, sprite_label


def setup_mqtt_client(pool):
    """create a mqtt client with information from secrets, set up callbacks"""

    # Set up a MiniMQTT Client
    mqtt_client = MQTT.MQTT(
        broker=secrets["mqtt_broker"],
        port=secrets["mqtt_port"],
        username=secrets["mqtt_username"],
        password=secrets["mqtt_password"],
        socket_pool=pool,
        is_ssl=False
    )

    # Connect callback handlers to mqtt_client
    mqtt_client.on_connect = connect
    mqtt_client.on_disconnect = disconnect
    mqtt_client.add_topic_callback(dog_fed_morning_topic, dog_feeding_trigger)
    mqtt_client.add_topic_callback(dog_fed_evening_topic, dog_feeding_trigger)

    return mqtt_client


def connect(mqtt_client, userdata, flags, rc):
    """callback when connection made to MQTT broker"""
    print("Connected to MQTT Broker!")
    mqtt_client.subscribe(dog_fed_morning_topic)
    mqtt_client.subscribe(dog_fed_evening_topic)


def disconnect(mqtt_client, userdata, rc):
    """callback when disconnected from MQTT broker"""
    print("Disconnected from MQTT Broker!")


def subscribe(mqtt_client, userdata, topic, granted_qos):
    """This method is called when the mqtt_client subscribes to a new feed."""
    print(f"Subscribed to {topic} with QOS level {granted_qos}")


def dog_feeding_trigger(client, topic, message):
    """MQTT callback that triggers a REST API call to update status"""
    print(f"Received trigger on {topic}: {message}")

    # Fetch latest status from API
    status_data = fetch_dog_feed_status()
    if status_data:
        update_display_from_status(status_data)
    else:
        print("Failed to fetch status from API")


def main():
    global morning_sprite, morning_sprite_label
    global evening_sprite, evening_sprite_label
    global last_refresh, requests

    print(f'Connecting to {secrets["ssid"]}')
    wifi.radio.connect(secrets["ssid"], secrets["password"])
    print(f'Connected to {secrets["ssid"]}')

    # Create a socket pool
    pool = socketpool.SocketPool(wifi.radio)

    # Initialize requests session
    requests = adafruit_requests.Session(pool, ssl.create_default_context())

    # set up default state for neopixels
    pixels[3] = RED
    pixels[0] = RED

    # Set up display
    splash = displayio.Group(scale=1)
    bg_group = displayio.Group()
    position = (0, 0)
    background = displayio.OnDiskBitmap(BACKGROUND)
    bg_sprite = displayio.TileGrid(
        background,
        pixel_shader=background.pixel_shader,
        x=position[0],
        y=position[1],
    )
    bg_group.append(bg_sprite)
    splash.append(bg_group)

    morning_group, morning_sprite, morning_sprite_label = setup_panel()
    evening_group, evening_sprite, evening_sprite_label = setup_panel(147)
    splash.append(morning_group)
    splash.append(evening_group)

    board.DISPLAY.show(splash)
    board.DISPLAY.refresh()
    last_refresh = time.time()

    # Set up MQTT client for triggers
    mqtt_client = setup_mqtt_client(pool)

    print(f"Attempting to connect to {mqtt_client.broker}")
    mqtt_client.connect()

    # Initial status fetch
    print("Fetching initial dog feed status...")
    initial_status = fetch_dog_feed_status()
    if initial_status:
        update_display_from_status(initial_status)

    last_sync = None
    last_status_fetch = None

    while True:
        # Sync device time once an hour
        if not last_sync or (time.monotonic() - last_sync) > 3600:
            print("Syncing device time")
            set_device_time(pool)
            last_sync = time.monotonic()

        # Check if it's time to sleep
        check_time_window()

        # Handle MQTT messages (triggers)
        try:
            mqtt_client.loop()
        except Exception as e:
            print(f"MQTT error: {e}")
            try:
                mqtt_client.connect()
            except:
                pass

        # Periodic status fetch (every 5 minutes) as fallback
        now = time.monotonic()
        if not last_status_fetch or (now - last_status_fetch) > 300:  # 5 minutes
            print("Periodic status fetch...")
            status_data = fetch_dog_feed_status()
            if status_data:
                update_display_from_status(status_data)
            last_status_fetch = now

        time.sleep(3)


if __name__ == '__main__':
    main()