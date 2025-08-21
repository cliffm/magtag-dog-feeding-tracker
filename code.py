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

# mqtt topics
dog_fed_morning_topic = 'dog/fed/morning'
dog_fed_evening_topic = 'dog/fed/evening'


def set_device_time(pool):
    """connect to webservice, and get time information (JSON), and set device Real Time Clock"""
    try:
        # call webservice
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
    except:
        print("There was an error")
        pass


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
    mqtt_client.add_topic_callback(dog_fed_morning_topic, dog_fed_morning)
    mqtt_client.add_topic_callback(dog_fed_evening_topic, dog_fed_evening)

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


def dog_fed_morning(client, topic, message):
    global morning_sprite, morning_sprite_label
    global last_refresh

    if len(message) > 0:
        print(f"{topic} called with {message}")
        pixels[3] = GREEN
        morning_sprite[0] = 1
        morning_sprite_label.text = f"Fed at {message}"
    else:
        pixels[3] = RED
        morning_sprite[0] = 0
        morning_sprite_label.text = f"Not fed"

    now = time.time()
    if now <= last_refresh + 5:
        time.sleep(5)

    board.DISPLAY.refresh()
    last_refresh = time.time()


def dog_fed_evening(client, topic, message):
    global evening_sprite, evening_sprite_label
    global last_refresh

    if len(message) > 0:
        print(f"{topic} called with {message}")
        pixels[0] = GREEN
        evening_sprite[0] = 1
        evening_sprite_label.text = f"Fed at {message}"
    else:
        pixels[0] = RED
        evening_sprite[0] = 0
        evening_sprite_label.text = f"Not fed"

    now = time.time()
    if now <= last_refresh + 5:
        time.sleep(5)

    board.DISPLAY.refresh()
    last_refresh = time.time()


def main():
    global morning_sprite, morning_sprite_label
    global evening_sprite, evening_sprite_label
    global last_refresh

    print(f'Connecting to {secrets["ssid"]}')
    wifi.radio.connect(secrets["ssid"], secrets["password"])
    print(f'Connected to {secrets["ssid"]}')

    # Create a socket pool
    pool = socketpool.SocketPool(wifi.radio)

    # set up default state for neopixels
    pixels[3] = RED
    pixels[0] = RED

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

    mqtt_client = setup_mqtt_client(pool)

    print(f"Attempting to connect to {mqtt_client.broker}")
    mqtt_client.connect()

    last_sync = None
    while True:
        if not last_sync or (time.monotonic() - last_sync) > 3600:
            # at start or once an hour
            print("Syncing device time")
            set_device_time(pool)
            last_sync = time.monotonic()

        check_time_window()

        try:
            mqtt_client.loop()
        except:
            mqtt_client.connect()

        time.sleep(3)


if __name__ == '__main__':
    # TODO: Sprites
    main()
