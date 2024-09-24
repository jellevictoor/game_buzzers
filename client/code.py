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

STARTUP = 0
REGISTRATION_SENT = 1
REGISTERED = 2
DISABLED = 3
ENABLED = 4
BUTTON_PRESSED = 5


client_status = STARTUP

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


async def blink():
    global blink_color
    while True:
        pixel.fill(blink_color)
        pixel.show()
        await asyncio.sleep(0.2)
        pixel.fill((0, 0, 0))
        pixel.show()
        await asyncio.sleep(0.2)


async def receive_messages():
    global blink_color
    global client_status
    global game_server_peer
    global game_id
    registration_send = None

    while True:

        if client_status == REGISTRATION_SENT and time() - registration_send > 10:
            print("No ack received, going back to STARTUP")
            client_status = STARTUP
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
                        client_status = STARTUP
                        game_id = message['game_id']

                    if client_status == STARTUP:
                        server_mac = binascii.unhexlify(message['server_mac'].encode('UTF-8').replace(b':', b''))

                        if [peer.mac for peer in esp_now_connection.peers].count(server_mac) == 0:
                            game_server_peer = espnow.Peer(mac=server_mac, channel=1)
                            esp_now_connection.peers.append(game_server_peer)

                        esp_now_connection.send(
                            json.dumps({"action": "request_registration", "name": name}).encode('UTF-8'),
                            peer=game_server_peer)
                        print("registration requested")
                        blink_color = PURPLE
                        client_status = REGISTRATION_SENT
                        registration_send = time()
                    continue
                if action == "registration_ack":
                    blink_color = GREEN
                    client_status = ENABLED
                    print("Registered with the server!")
                    continue

                if action == "ping":
                    esp_now_connection.send(json.dumps({"action": "pong", "name": name}).encode('UTF-8'),
                                            peer=game_server_peer)
                    continue

                if action == "disable":
                    if client_status == REGISTERED:
                        client_status == DISABLED
                    continue

                if action == "enable":
                    if client_status == REGISTERED:
                        client_status == ENABLED
                    continue

            print("unknown packet ", packet)
        await asyncio.sleep(0.001)


async def button_listener():
    global client_status
    global button_light
    while True:
        await asyncio.sleep(0.001)  # avoid starvation

        if client_status == DISABLED:
            button_light.value = False
            continue

        if client_status == ENABLED:
            button_light.value = True
            # button is active low
            if not button.value:
                print("button pressed")
                esp_now_connection.send(json.dumps({"action": "pressed", "name": name}).encode('UTF-8'),
                                        peer=game_server_peer)
                client_status = BUTTON_PRESSED
            continue

        if client_status == BUTTON_PRESSED:
            button_light.value = False
            continue


async def main():
    receive_task = asyncio.create_task(receive_messages())
    button_pushed_task = asyncio.create_task(button_listener())
    status_task = asyncio.create_task(blink())
    await asyncio.gather(
        receive_task,
        button_pushed_task,
        status_task)


asyncio.run(main())
