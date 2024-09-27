import asyncio
import json
import random
import time

import board
import digitalio
import espnow
import neopixel
import usb_cdc
import wifi


def log_to_serial(message):
    if usb_cdc.data:
        usb_cdc.data.write(b"LOG: {0}\n".format(message))

    if usb_cdc.console:
        print(message)


led_bar_size = 6
led_bar = neopixel.NeoPixel(board.MOSI, led_bar_size, brightness=0.2)
enable_all_button = digitalio.DigitalInOut(board.A1)
enable_all_button.switch_to_input(pull=digitalio.Pull.UP)
disable_all_button = digitalio.DigitalInOut(board.A0)
disable_all_button.switch_to_input(pull=digitalio.Pull.UP)

broadcast_pixel = led_bar[1]
player_pixels = led_bar[2:]
status_pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)

my_mac = wifi.radio.mac_address
my_mac_str = ":".join(["{:02x}".format(b) for b in my_mac])
game_id = str(random.random())
log_to_serial(f"I'm the server and this is my MAC address: {my_mac_str}")
broadcast_mac = b'\xff\xff\xff\xff\xff\xff'

esp_now_connection = espnow.ESPNow()
broadcast_peer = espnow.Peer(mac=broadcast_mac, channel=1)
esp_now_connection.peers.append(broadcast_peer)

packets = []

players = []
players_per_mac = {}
BRIGHTNESS = 0.2
PLAYER_COLORS = {
    "RED": (255, 0, 0, BRIGHTNESS),
    "GREEN": (0, 255, 0, BRIGHTNESS),
    "BLUE": (0, 0, 255, BRIGHTNESS),
    "YELLOW": (255, 255, 0, BRIGHTNESS),
}


class Player:
    def __init__(self, mac_address, name, player_index):
        self.mac_address = mac_address
        self.name = name
        self.player_index = player_index
        self.last_seen = time.time()

        self.peer = None
        self.enabled = False

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def set_peer(self, peer):
        self.peer = peer

    def __str__(self):
        return f"Player {self.name} with MAC address {self.mac_address}"

    def get_color(self):
        name = self.name.upper()
        return PLAYER_COLORS.get(name, (255, 255, 255))

    def is_online(self):
        return (time.time() - self.last_seen) < 10

class LEDSequence:
    def __init__(self, led_bar, led_index, color, duration):
        self.led_bar = led_bar
        self.led_index = led_index
        self.color = color
        self.duration = duration

# Replace Queue with a list and an Event
led_sequences = []
led_sequence_event = asyncio.Event()

async def add_led_sequence(sequence):
    led_sequences.append(sequence)
    led_sequence_event.set()

async def handle_led_sequences():
    while True:
        await led_sequence_event.wait()
        while led_sequences:
            sequence = led_sequences.pop(0)
            led_index = len(led_bar) - sequence.led_index - 1
            original_color = sequence.led_bar[led_index]

            # Blink twice
            for _ in range(2):
                sequence.led_bar[led_index] = sequence.color
                sequence.led_bar.show()
                await asyncio.sleep(0.5)
                sequence.led_bar[led_index] = (0, 0, 0)
                sequence.led_bar.show()
                await asyncio.sleep(0.5)

            # Restore original color
            sequence.led_bar[led_index] = original_color
            sequence.led_bar.show()

        led_sequence_event.clear()

async def receive_serial_message(refresh_time):
    input_serial_connection = usb_cdc.console
    usb_cdc.console.write_timeout = 1
    while True:
        if input_serial_connection and input_serial_connection.in_waiting > 0:
            # Read the incoming message
            message = input_serial_connection.readline().decode().strip()
            log_to_serial(f"Received: {message}")
            try:
                message = json.loads(message)
                for player_index in message['enable']:

                    if player_index >= len(players):
                        log_to_serial(f"Invalid player index {player_index}")
                        continue
                    await add_led_sequence(LEDSequence(led_bar, player_index + 2, players[player_index].get_color(), 1))
                    esp_now_connection.send(json.dumps({"action": "enable"}).encode('utf-8'),
                                            peer=players[player_index].peer)

                for player_index in message['disable']:

                    if player_index >= len(players):
                        log_to_serial(f"Invalid player index {player_index}")
                        continue
                    await add_led_sequence(LEDSequence(led_bar, player_index + 2, players[player_index].get_color(), 1))
                    esp_now_connection.send(json.dumps({"action": "disable"}).encode('utf-8'),
                                            peer=players[player_index].peer)

            except ValueError:
                log_to_serial("Invalid JSON received {0}".format(message))
            except Exception as e:
                log_to_serial("Error processing message {0}".format(str(e)))

        await asyncio.sleep(refresh_time)


async def broadcast_mac_address(interval):
    while True:

        esp_now_connection.send(json.dumps({
            "action": "announce",
            "server_mac": my_mac_str.encode(),
            "game_id": game_id}
        ).encode('utf-8'), peer=broadcast_peer)

        await add_led_sequence(LEDSequence(led_bar, 0, (128,0,128), 2))
        await asyncio.sleep(interval)


def register_peer(mac_address):
    for peer in esp_now_connection.peers:
        if peer.mac == mac_address:
            return peer
    player_peer = espnow.Peer(mac=mac_address, channel=1)
    esp_now_connection.peers.append(player_peer)
    return player_peer


def disable_other_players(player):
    for other_player in [player for player in players if player != player]:
        esp_now_connection.send(json.dumps({"action": "disable"}).encode('utf-8'), peer=other_player.peer)


async def receive_wireless_message(refresh_time):
    while True:
        try:
            packet = esp_now_connection.read()
            if packet:
                message = json.loads(packet.msg.decode('UTF-8'))
                if "action" in message:
                    log_to_serial("received action {0}".format(message["action"]))
                    if message["action"] == "request_registration":
                        player_name = message['name']
                        mac_address = packet.mac

                        player_index = await register_player(mac_address, player_name)
                        led_bar[player_index + 2] = players[player_index].get_color()
                        led_bar.show()
                        continue

                    if message["action"] == "pong":
                        mac_address = packet.mac
                        player_index = players_per_mac[mac_address].player_index
                        players[player_index].last_seen = time.time()
                        continue

                    if message["action"] == "pressed":
                        mac_address = packet.mac
                        player = players_per_mac[mac_address]
                        log_to_serial("Player {0} has pressed!".format(player.name))
                        disable_other_players(player)
                        usb_cdc.console.write(json.dumps({"buzzer": player_index + 1}).encode() + b'\n')
                        led_bar[0] = player.get_color()
                        led_bar.show()
                        await asyncio.sleep(1)
                        led_bar[0] = (0, 0, 0)
                        led_bar.show()

                        continue
        except Exception as e:
            log_to_serial("Error processing message {0}".format(str(e)))

        await asyncio.sleep(refresh_time)


async def register_player(mac_address, player_name) -> int:
    log_to_serial("received registration request from {0}".format(player_name))
    if not mac_address in players_per_mac.keys():
        player = Player(mac_address, player_name, len(players))
        player_peer = register_peer(mac_address)
        player.set_peer(player_peer)
        players.append(player)
        players_per_mac[mac_address] = player

    player = players_per_mac[mac_address]

    log_to_serial("sending registration ack")
    esp_now_connection.send(json.dumps({"action": "registration_ack"}).encode('UTF-8'), peer=player.peer)

    log_to_serial("Player {0} registered and has index {1}".format(player_name, player.player_index))
    player.last_seen = time.time()

    return player.player_index


async def ping_players():
    while True:
        log_to_serial("Pinging {0} players".format(len(players)))
        for player in players:
            player_peer = register_peer(player.mac_address)
            esp_now_connection.send(json.dumps({"action": "ping"}).encode('UTF-8'), peer=player_peer)
        await asyncio.sleep(5)


async def update_player_status():
    offline_color = (0, 0, 0)
    while True:
        for player in players:
            player_index = players.index(player)
            status_color = player.get_color() if player.is_online() else offline_color
            led_bar[player_index + 2] = status_color
            led_bar.show()

        await asyncio.sleep(1)


async def main():
    global status_pixel
    refresh_interval = 0.1
    broadcast_task = asyncio.create_task(broadcast_mac_address(5))  # Broadcast every 5 seconds
    receive_task = asyncio.create_task(receive_wireless_message(refresh_interval))
    ping_task = asyncio.create_task(ping_players())
    handle_serial_data_task = asyncio.create_task(receive_serial_message(refresh_interval))
    handle_led_sequences_task = asyncio.create_task(handle_led_sequences())
    update_player_status_task = asyncio.create_task(update_player_status())
    try:
        await add_led_sequence(LEDSequence(led_bar, 0, (0, 255, 0), 2))

        log_to_serial("Starting main loop")
        await asyncio.gather(broadcast_task, receive_task, ping_task, update_player_status_task,
                             handle_serial_data_task,handle_led_sequences_task)
    except BaseException as e:
        log_to_serial("Shutting down because of an exception {0}".format(str(e)))
        await add_led_sequence(LEDSequence(led_bar, 0, (0, 0, 0), 2))
        esp_now_connection.deinit()
        raise e


asyncio.run(main())
