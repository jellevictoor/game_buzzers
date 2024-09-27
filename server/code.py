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
    def __init__(self, esp_connection,mac_address, name, player_index):
        self.esp_connection = esp_connection
        self.mac_address = mac_address
        self.name = name
        self.player_index = player_index
        self.last_seen = time.time()
        self.peer = None
        self.enabled = True

    def enable(self):
        if self.enabled:
            return

        log_to_serial(f"Enabling player {self.name}")

        esp_now_connection.send(json.dumps({"action": "enable"}).encode('utf-8'),
                                peer=self.peer)
        self.enabled = True

    def disable(self):
        if not self.enabled:
            return

        log_to_serial(f"Disabling player {self.name}")
        esp_now_connection.send(json.dumps({"action": "disable"}).encode('utf-8'),
                                peer=self.peer)
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
    def __init__(self, led_bar, led_index, color, duration, blinks = 2):
        self.led_bar = led_bar
        self.led_index = led_index
        self.color = color
        self.duration = duration
        self.blinks = blinks

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
            for _ in range(sequence.blinks):
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

async def receive_serial_message(message):
    log_to_serial(f"Received: {message}")
    try:
        message = json.loads(message)
        for player_index in message['enable']:

            if player_index >= len(players):
                log_to_serial(f"Invalid player index {player_index}")
                continue
            await add_led_sequence(LEDSequence(led_bar, player_index + 2, players[player_index].get_color(), 1))
            players[player_index].enable()
        for player_index in message['disable']:

            if player_index >= len(players):
                log_to_serial(f"Invalid player index {player_index}")
                continue
            await add_led_sequence(LEDSequence(led_bar, player_index + 2, players[player_index].get_color(), 1))
            players[player_index].disable()

    except ValueError:
        log_to_serial("Invalid JSON received {0}".format(message))
    except Exception as e:
        log_to_serial("Error processing message {0}".format(str(e)))



async def broadcast_mac_address():
    esp_now_connection.send(json.dumps({
        "action": "announce",
        "server_mac": my_mac_str.encode(),
        "game_id": game_id}
    ).encode('utf-8'), peer=broadcast_peer)
    log_to_serial("Broadcasted MAC address")
    await add_led_sequence(LEDSequence(led_bar, 0, (128,0,128), 2, blinks=1))


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


async def handle_wireless_message(packet):
    message = json.loads(packet.msg.decode('UTF-8'))
    if "action" in message:
        log_to_serial("received action {0}".format(message["action"]))
        if message["action"] == "request_registration":
            player_name = message['name']
            mac_address = packet.mac

            player_index = await register_player(mac_address, player_name)
            led_bar[len(led_bar) - (player_index + 2) - 1] = players[player_index].get_color()
            led_bar.show()
            return

        if message["action"] == "pong":
            mac_address = packet.mac
            player_index = players_per_mac[mac_address].player_index
            players[player_index].last_seen = time.time()
            return

        if message["action"] == "pressed":
            mac_address = packet.mac
            player = players_per_mac[mac_address]
            log_to_serial("Player {0} has pressed!".format(player.name))
            disable_other_players(player)
            usb_cdc.console.write(json.dumps({"buzzer": players_per_mac[mac_address].player_index + 1}).encode() + b'\n')
            led_bar[0] = player.get_color()
            led_bar.show()
            await asyncio.sleep(1)
            led_bar[0] = (0, 0, 0)
            led_bar.show()

            return


async def register_player(mac_address, player_name) -> int:
    log_to_serial("received registration request from {0}".format(player_name))
    if not mac_address in players_per_mac.keys():
        player = Player(esp_now_connection, mac_address, player_name, len(players))
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


async def player_management():
    last_ping = time.time()
    while True:
        if time.time() - last_ping > 6:
            # Ping players
            log_to_serial(f"Pinging {len(players)} players")
            await add_led_sequence(LEDSequence(led_bar, 0, (0,247,255), 2, blinks=1))

            for player in players:
                player_peer = register_peer(player.mac_address)
                esp_now_connection.send(json.dumps({"action": "ping"}).encode('UTF-8'), peer=player_peer)

            last_ping = time.time()

        # Update player status
        offline_color = (0, 0, 0)
        for player in players:
            player_index = players.index(player)
            status_color = player.get_color() if player.is_online() else offline_color
            await add_led_sequence(LEDSequence(led_bar, player_index + 2, status_color, 0))

        await asyncio.sleep(0.1)  # Adjust this interval as needed

async def communication_handler():
    last_broadcast = time.time()
    while True:
        try:
            # Handle wireless messages
            packet = esp_now_connection.read()
            if packet:
                await handle_wireless_message(packet)

            # Handle serial messages
            if usb_cdc.console and usb_cdc.console.in_waiting > 0:
                try:
                    message = usb_cdc.console.readline().decode().strip()
                    await receive_serial_message(message)
                except Exception as e:
                    log_to_serial(f"Error processing serial message: {str(e)}")

            # Broadcast MAC address
            if time.time() - last_broadcast > 4:
                await broadcast_mac_address()
                last_broadcast = time.time()

        except Exception as e:
            log_to_serial(f"Error in communication handler: {str(e)}")


        await asyncio.sleep(0.1)  # Small delay to prevent tight looping
async def button_listener():
    enable_all_button = digitalio.DigitalInOut(board.A1)
    enable_all_button.switch_to_input(pull=digitalio.Pull.UP)
    disable_all_button = digitalio.DigitalInOut(board.A0)
    disable_all_button.switch_to_input(pull=digitalio.Pull.UP)

    while True:
        if not enable_all_button.value:
            log_to_serial("Enable all button pressed")
            for player in players:
                player.enable()
            await add_led_sequence(LEDSequence(led_bar, 0, (0, 255, 0), 2))
            await asyncio.sleep(0.5)
            continue

        if not disable_all_button.value:
            log_to_serial("Disable all button pressed")
            for player in players:
                player.disable()
            await add_led_sequence(LEDSequence(led_bar, 0, (255, 0, 0), 2))
            await asyncio.sleep(0.5)
            continue

        await asyncio.sleep(0.1)
async def main():
    global status_pixel
    usb_cdc.console.write_timeout = 1

    communication_task = asyncio.create_task(communication_handler())
    player_management_task = asyncio.create_task(player_management())
    handle_led_sequences_task = asyncio.create_task(handle_led_sequences())
    button_task = asyncio.create_task(button_listener())
    try:
        await add_led_sequence(LEDSequence(led_bar, 0, (0, 255, 0), 2))

        log_to_serial("Starting main loop")
        await asyncio.gather(communication_task, player_management_task,
                             handle_led_sequences_task, button_task)
    except BaseException as e:
        log_to_serial("Shutting down because of an exception {0}".format(str(e)))
        await add_led_sequence(LEDSequence(led_bar, 0, (0, 0, 0), 2))
        esp_now_connection.deinit()
        raise e


asyncio.run(main())
