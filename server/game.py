import asyncio
import time

import neopixel

PLAYER_COLORS = {
    "RED": (255, 0, 0),
    "GREEN": (0, 255, 0),
    "BLUE": (0, 0, 255),
    "YELLOW": (255, 255, 0),
}


class Game:
    def __init__(self):
        self.players = []
        self.players_per_mac = {}
        self.current_player = None

    def add_player(self, player):
        self.players.append(player)

    def register_player(self, mac_address, player_name) -> "Player":
        print("received registration request from {0}".format(player_name))
        if not mac_address in self.players_per_mac.keys():
            player = Player(mac_address, player_name, len(self.players))
            self.players.append(player)
            self.players_per_mac[mac_address] = player

        player = self.players_per_mac[mac_address]
        print("Player {0} registered and has index {1}".format(player_name, player.player_index))
        player.last_seen = time.time()

        return player

    def get_player(self, mac_address):
        if not mac_address in self.players_per_mac.keys():
            return None

        player = self.players_per_mac[mac_address]
        if player:
            return player

    def enable_players(self, player_indexes: list[int]):
        enabled_players = []
        for player in self.players:
            if -1 in player_indexes or player.player_index in player_indexes:
                if not player.enabled:
                    player.enable()
                    enabled_players.append(player)

        return enabled_players

    def disable_players(self, player_indexes: list[int]):
        disabled_players = []
        for player in self.players:
            if -1 in player_indexes or player.player_index in player_indexes:
                if player.enabled:
                    player.disable()
                    disabled_players.append(player)

        return disabled_players

    def register_heartbeat(self, mac_address):
        if mac_address in self.players_per_mac.keys():
            self.players_per_mac[mac_address].last_seen = time.time()
        else:
            print("Received heartbeat from unknown player with MAC address {0}".format(mac_address))

    def enable_all_players(self):
        return self.enable_players([-1])

    def disable_all_players(self):
        return self.disable_players([-1])

    def state(self):
        return {
            "players": [player.__dict__ for player in self.players]
        }


class LedBar:
    BROADCAST_INDEX = 0
    PING_INDEX = 1
    PLAYER_INDEX = [5, 4, 3, 2]

    def __init__(self, pin):
        self.color = None
        self.size = 6
        self.pin = pin
        self.neopixels = neopixel.NeoPixel(pin, self.size)
        self.neopixels.brightness = 0.1
        self.waiting = True
        asyncio.create_task(self._show_waiting())


    def _set_all_pixels(self, color):
        self.color = color
        self.neopixels.fill(self.color)
        self.neopixels.show()

    async def _show_waiting(self):
        index = 0
        direction = 1
        while self.waiting:
            self._set_all_pixels((0, 0, 0))
            self._set_led_color((255, 128, 0), index)
            await asyncio.sleep(0.1)
            index = index + direction
            if index == self.size -1 :
                direction = -1
            if index == 0:
                direction = 1
        self._set_all_pixels((0, 0, 0))

    def flash(self, times, color):
        asyncio.create_task(self._flash(times, color))

    def flash_player(self, player_index, color):
        asyncio.create_task(self._flash_player(color, player_index))

    def set_player_status(self, player_index: int, player_color: tuple[3]):
        self.waiting = False
        led_index_mapping = self.PLAYER_INDEX[player_index]
        self._set_led_color(player_color, led_index_mapping)

    async def _flash_player(self, color, player_index):
        led_index_mapping = self.PLAYER_INDEX[player_index]
        await self._flash(2, color, led_index_mapping)
        self._set_led_color(color, led_index_mapping)

    async def _flash(self, times, color, index=None):
        for i in range(times):
            if index is None:
                self._set_all_pixels(color)
            else:
                self._set_led_color(color, index)
            await asyncio.sleep(0.5)

            if index is None:
                self._set_all_pixels((0, 0, 0))
            else:
                self._set_led_color((0, 0, 0), index)

            await asyncio.sleep(0.5)

    def _set_led_color(self, color, index):
        self.neopixels[index] = color
        self.neopixels.show()


class Player:
    def __init__(self, mac_address, name, player_index):
        self.mac_address = mac_address
        self.name = name
        self.player_index = player_index
        self.last_seen = time.time()
        self.enabled = True

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def __str__(self):
        return f"Player {self.name} with MAC address {self.mac_address} is {'enabled' if self.enabled else 'disabled'}"

    def get_color(self):
        name = self.name.upper()
        return PLAYER_COLORS.get(name, (255, 255, 255))

    def is_online(self):
        return (time.time() - self.last_seen) < 10
