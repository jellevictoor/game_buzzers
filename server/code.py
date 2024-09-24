import asyncio
import json
import random
import time

import board
import espnow
import neopixel
import wifi

led_bar_size = 6
led_bar = neopixel.NeoPixel(board.RX, led_bar_size)
status_pixel = led_bar[0]
broadcast_pixel = led_bar[1]
player_pixels = led_bar[2:]

my_mac = wifi.radio.mac_address
my_mac_str = ":".join(["{:02x}".format(b) for b in my_mac])
game_id = str(random.random())
print(f"I'm the server and this is my MAC address: {my_mac_str}")
broadcast_mac = b'\xff\xff\xff\xff\xff\xff'

esp_now_connection = espnow.ESPNow()
broadcast_peer = espnow.Peer(mac=broadcast_mac, channel=1)
esp_now_connection.peers.append(broadcast_peer)

packets = []

players = []
BRIGHTNESS = 50
PLAYER_COLORS = {
    "RED": (255, 0, 0, BRIGHTNESS),
    "GREEN": (0, 255, 0, BRIGHTNESS),
    "BLUE": (0, 0, 255, BRIGHTNESS),
    "YELLOW": (255, 255, 0, BRIGHTNESS),
}


class Player:
    def __init__(self, mac_address, name):
        self.mac_address = mac_address
        self.name = name
        self.last_seen = time.time()

    def __str__(self):
        return f"Player {self.name} with MAC address {self.mac_address}"

    def get_color(self):
        name = self.name.upper()
        return PLAYER_COLORS.get(name, (255, 255, 255, BRIGHTNESS))

    def is_online(self):
        return (time.time() - self.last_seen) < 10


async def update_leds():
    index = 0
    YELLOW = (255, 255, 0)
    while False:
        led_bar[index] = YELLOW

        led_bar.show()
        await asyncio.sleep(0.2)
        led_bar[index] = (0, 0, 0)
        led_bar.show()
        await asyncio.sleep(0.2)
        index += 1
        if index >= led_bar_size:
            index = 0


async def broadcast_mac_address(interval):
    while True:
        led_bar[1] = (255, 0, 0)
        esp_now_connection.send(json.dumps({
            "action": "announce",
            "server_mac": my_mac_str.encode(),
            "game_id": game_id}
        ).encode('utf-8'), peer=broadcast_peer)
        led_bar[1] = (0, 0, 0)
        await asyncio.sleep(interval)


def register_peer(mac_address):
    for peer in esp_now_connection.peers:
        if peer.mac == mac_address:
            return peer
    player_peer = espnow.Peer(mac=mac_address, channel=1)
    esp_now_connection.peers.append(player_peer)
    return player_peer


async def receive_messages():
    known_macs = []
    while True:
        packet = esp_now_connection.read()
        if packet:
            message = json.loads(packet.msg.decode('UTF-8'))
            if "action" in message:
                print("received action", message["action"])
                if message["action"] == "request_registration":
                    player_name = message['name']
                    mac_address = packet.mac

                    player_index = await register_player(mac_address, player_name, known_macs)
                    led_bar[player_index + 2] = players[player_index].get_color()
                    led_bar.show()
                    continue

                if message["action"] == "pong":
                    mac_address = packet.mac
                    player_index = [player.mac_address for player in players].index(mac_address)
                    players[player_index].last_seen = time.time()
                    continue

        await asyncio.sleep(0.1)


async def register_player(mac_address, player_name, known_macs) -> int:
    print("received registration request from ", player_name)
    if not mac_address in known_macs:
        players.append(Player(mac_address, player_name))
        known_macs.append(mac_address)

    player_peer = register_peer(mac_address)
    print("sending registration ack")
    esp_now_connection.send(json.dumps({"action": "registration_ack"}).encode('UTF-8'), peer=player_peer)
    print("Player ", player_name, " registered and has index ", len(players) - 1)
    player_index = [player.mac_address for player in players].index(mac_address)
    players[player_index].last_seen = time.time()
    return player_index


async def ping_players():
    while True:
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
    broadcast_task = asyncio.create_task(broadcast_mac_address(5))  # Broadcast every 5 seconds
    receive_task = asyncio.create_task(receive_messages())
    led_task = asyncio.create_task(update_leds())
    ping_task = asyncio.create_task(ping_players())
    update_player_status_task = asyncio.create_task(update_player_status())
    await asyncio.gather(broadcast_task, receive_task, led_task, ping_task, update_player_status_task)


asyncio.run(main())
