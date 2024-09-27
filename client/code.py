import asyncio
import binascii
import json
from time import time

import board
import digitalio
import espnow
import neopixel

from client_name import name

RED = (255, 0, 0)
YELLOW = (255, 255, 0)
PURPLE = (128, 0, 128)
GREEN = (0, 255, 0)

CLIENT_STARTING_UP = 0
CLIENT_REGISTRATION_SENT = 1
CLIENT_REGISTERED = 2

BUTTON_DISABLED = 1
BUTTON_ENABLED = 2
BUTTON_PRESSED = 3
button_pressed_time = None



client_status = CLIENT_STARTING_UP
button_status = BUTTON_DISABLED


esp_now_connection = espnow.ESPNow()
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
button = digitalio.DigitalInOut(board.A0)
button.switch_to_input(pull=digitalio.Pull.UP)

button_light = digitalio.DigitalInOut(board.TX)
button_light.switch_to_output()

game_server_peer = None
game_id = None

print("buzzer ", name, " started")
blink_color = RED


async def blink(refresh_interval):
    global blink_color
    while True:
        pixel.fill(blink_color)
        pixel.show()
        await asyncio.sleep(refresh_interval)
        pixel.fill((0, 0, 0))
        pixel.show()
        await asyncio.sleep(refresh_interval)


async def receive_messages(refresh_interval):
    global blink_color
    global client_status
    global game_server_peer
    global game_id
    registration_send = None

    while True:

        if client_status == CLIENT_REGISTRATION_SENT and time() - registration_send > 10:
            print("No ack received, going back to STARTUP")
            await update_client_status(CLIENT_STARTING_UP)
            blink_color = RED

        if esp_now_connection:
            packet = esp_now_connection.read()
            if not packet:
                print("received but no packet")
                continue

            if not packet.msg:
                print("packet without msg")
                continue

            decoded_message = packet.msg.decode('UTF-8')
            message = json.loads(decoded_message)

            if "action" in message:
                action = message["action"]
                print("received action", action)
                if action == "announce":
                    if message['game_id'] != game_id:
                        print("game id mismatch, server has rebooted, need to re-register")
                        await update_client_status(CLIENT_STARTING_UP)

                        game_id = message['game_id']

                    if client_status == CLIENT_STARTING_UP:
                        server_mac = binascii.unhexlify(message['server_mac'].encode('UTF-8').replace(b':', b''))

                        if [peer.mac for peer in esp_now_connection.peers].count(server_mac) == 0:
                            game_server_peer = espnow.Peer(mac=server_mac, channel=1)
                            esp_now_connection.peers.append(game_server_peer)

                        esp_now_connection.send(
                            json.dumps({"action": "request_registration", "name": name}).encode('UTF-8'),
                            peer=game_server_peer)
                        print("registration requested")
                        blink_color = PURPLE
                        await update_client_status(CLIENT_REGISTRATION_SENT)
                        registration_send = time()
                    continue
                if action == "registration_ack":
                    blink_color = GREEN
                    await update_client_status(CLIENT_REGISTERED)
                    await update_button_status(BUTTON_ENABLED)

                    print("Registered with the server!")
                    continue

                if action == "ping":
                    if client_status != CLIENT_STARTING_UP:
                        esp_now_connection.send(json.dumps({"action": "pong", "name": name}).encode('UTF-8'),
                                                peer=game_server_peer)
                        continue

                if action == "disable":
                    await update_button_status(BUTTON_DISABLED)
                    continue

                if action == "enable":
                    await update_button_status(BUTTON_ENABLED)
                    continue

            print("unknown packet ", packet)
        await asyncio.sleep(refresh_interval)


async def button_listener(refresh_interval):
    global client_status
    global button_light
    global button_pressed_time
    while True:
        await handle_button(button_light, client_status)

        await asyncio.sleep(refresh_interval)  # avoid starvation


async def handle_button(button_light, client_status):
    global button_pressed_time
    if button_status == BUTTON_DISABLED:
        button_light.value = False
        return

    if button_status == BUTTON_ENABLED:
        button_light.value = True
        # button is active low
        if not button.value:
            esp_now_connection.send(json.dumps({"action": "pressed", "name": name}).encode('UTF-8'),
                                    peer=game_server_peer)
            await update_button_status(BUTTON_PRESSED)
            button_pressed_time = time()
        return

    if button_status == BUTTON_PRESSED:
        button_light.value = False
        if time() - button_pressed_time > 0.1:
            await update_button_status(BUTTON_ENABLED)
        return


async def update_client_status(status):
    global client_status
    print("client status changed to ", status)
    client_status = status

async def update_button_status(status):
    global button_status
    print("button status changed to ", status)
    button_status = status


async def main():
    refresh_interval = 0.001
    receive_task = asyncio.create_task(receive_messages(refresh_interval))
    button_pushed_task = asyncio.create_task(button_listener(refresh_interval))
    status_task = asyncio.create_task(blink(0.2))
    await asyncio.gather(
        receive_task,
        button_pushed_task,
        status_task)


asyncio.run(main())
