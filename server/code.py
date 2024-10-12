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

from game import Game
from game import LedBar

my_mac = wifi.radio.mac_address
my_mac_str = ":".join(["{:02x}".format(b) for b in my_mac])
game_id = str(random.random())
print(f"I'm the server and this is my MAC address: {my_mac_str}")
broadcast_mac = b'\xff\xff\xff\xff\xff\xff'

esp_now_connection = espnow.ESPNow()
broadcast_peer = espnow.Peer(mac=broadcast_mac, channel=1)
esp_now_connection.peers.append(broadcast_peer)
player_peers = {}

async def receive_serial_message(game, message):
    print(f"Received: {message}")
    try:
        message = json.loads(message)
        if "enable" not in message or "disable" not in message:
            print("Invalid message received")
            return

        players_to_enable = game.enable_players(message["enable"])
        for player in players_to_enable:
            esp_now_connection.send(json.dumps({"action": "enable"}).encode('utf-8'), peer=player_peers[player.mac_address])

        players_to_disable = game.disable_players(message["disable"])
        for player in players_to_disable:
            esp_now_connection.send(json.dumps({"action": "disable"}).encode('utf-8'), peer=player_peers[player.mac_address])

    except ValueError:
        print("Invalid JSON received {0}".format(message))
    except Exception as e:
        print("Error processing message {0}".format(str(e)))


async def broadcast_mac_address():
    esp_now_connection.send(json.dumps({
        "action": "announce",
        "server_mac": my_mac_str.encode(),
        "game_id": game_id}
    ).encode('utf-8'), peer=broadcast_peer)
    print("Broadcasted MAC address")


def register_peer_with_espnow(mac_address):
    for peer in esp_now_connection.peers:
        if peer.mac == mac_address:
            return peer
    player_peer = espnow.Peer(mac=mac_address, channel=1)
    esp_now_connection.peers.append(player_peer)
    return player_peer


async def handle_wireless_message(packet, game:Game,led_bar:LedBar):
    message = json.loads(packet.msg.decode('UTF-8'))
    if "action" in message:
        print("received action {0}".format(message["action"]))
        mac_address = packet.mac
        if message["action"] == "request_registration":
            player_name = message['name']

            player = game.register_player(mac_address, player_name)

            player_peers[mac_address] = register_peer_with_espnow(mac_address)
            esp_now_connection.send(json.dumps({"action": "registration_ack"}).encode('UTF-8'), peer=player_peers[mac_address])
            led_bar.flash_player(player.player_index, player.get_color())
            return

        if message["action"] == "pong":
            game.register_heartbeat(mac_address)
            return

        if message["action"] == "pressed":
            player = game.get_player(mac_address)

            if player:
                print("Player {0} has pressed!".format(player.name))
                message = {"buzzer": player.player_index}
                usb_cdc.console.write(json.dumps(message).encode() + b'\n')
                return

            print("Unknown player with MAC address {0} pressed".format(mac_address))
            return


async def player_management(game:Game, led_bar:LedBar):
    last_ping = time.time()
    while True:
        if time.time() - last_ping > 6:
            print(f"Pinging {len(player_peers)} players")

            for player_peer in player_peers.values():
                esp_now_connection.send(json.dumps({"action": "ping"}).encode('UTF-8'), peer=player_peer)

            last_ping = time.time()

        for player in game.players:
            led_bar.set_player_status(player.player_index,player.get_color() if player.is_online() else (0,0,0))

        await asyncio.sleep(0.1)  # Adjust this interval as needed


async def communication_handler(game: Game, led_bar:LedBar) -> None:
    last_broadcast = time.time()
    while True:
        try:
            # Handle wireless messages
            packet = esp_now_connection.read()
            if packet:
                await handle_wireless_message(packet, game, led_bar)

            # Handle serial messages
            if usb_cdc.console and usb_cdc.console.in_waiting > 0:
                try:
                    message = usb_cdc.console.readline().decode().strip()
                    if message.startswith("{"):
                        await receive_serial_message(game, message)
                except Exception as e:
                    print(f"Error processing serial message: {str(e)}")

            # Broadcast MAC address
            if time.time() - last_broadcast > 4:
                await broadcast_mac_address()
                last_broadcast = time.time()

        except Exception as e:
            raise e

        await asyncio.sleep(0.1)  # Small delay to prevent tight looping


async def button_listener(game: Game):
    enable_all_button = digitalio.DigitalInOut(board.A1)
    enable_all_button.switch_to_input(pull=digitalio.Pull.UP)
    disable_all_button = digitalio.DigitalInOut(board.A0)
    disable_all_button.switch_to_input(pull=digitalio.Pull.UP)
    enable_all_pressed = time.time()
    disable_all_pressed = time.time()
    while True:
        if not enable_all_button.value and time.time() - enable_all_pressed > 0.5:
            enable_all_pressed = time.time()
            players = game.enable_all_players()
            print(game.state())
            print("Enabling all players {0}".format(players))
            for player in players:
                print(f"Enabling player {player.name}")
                print(player)
                esp_now_connection.send(json.dumps({"action": "enable"}).encode('utf-8'), peer=player_peers[player.mac_address])

            continue

        if not disable_all_button.value and time.time() - disable_all_pressed > 0.5:
            disable_all_pressed = time.time()
            players = game.disable_all_players()
            print(game.state())
            print("Disabling all players {0}".format(players))
            for player in players:
                print(f"Disabling player {player.name}")
                print(player)
                esp_now_connection.send(json.dumps({"action": "disable"}).encode('utf-8'),
                                        peer=player_peers[player.mac_address])

            continue

        await asyncio.sleep(0.1)


async def main():
    usb_cdc.console.write_timeout = 1
    game = Game()
    led_bar = LedBar(pin=board.MOSI)
    led_bar.set_all_pixels((0, 0, 255))
    led_bar.flash(2, (0, 255, 0))
    communication_task = asyncio.create_task(communication_handler(game, led_bar))
    player_management_task = asyncio.create_task(player_management(game, led_bar))
    button_task = asyncio.create_task(button_listener(game))
    try:

        print("Starting main loop")
        await asyncio.gather(communication_task, player_management_task, button_task)
    except BaseException as e:
        print("Shutting down because of an exception {0}".format(str(e)))
        esp_now_connection.deinit()
        raise e


asyncio.run(main())
