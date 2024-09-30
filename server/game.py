import time

import board
import usb_cdc

PLAYER_COLORS = {
    "RED": (255, 0, 0),
    "GREEN": (0, 255, 0),
    "BLUE": (0, 0, 255),
    "YELLOW": (255, 255, 0),
}


class SerialListener:
    def __init__(self):
        self.serial = usb_cdc.console

    def listen(self):
        pass


class Game:
    def __init__(self):
        self.players = []
        self.players_per_mac = {}
        self.led_bar = LedBar(None)
        self.current_player = None
        self.serial_console = None

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
    PLAYER_INDEX = [2, 3, 4, 5]

    def __init__(self, pin):
        self.color = None
        self.size = 6
        self.pin = board.MOSI

    def set_color(self, color):
        self.color = color


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
