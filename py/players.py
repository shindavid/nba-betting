import datetime


PlayerName = str


class Player:
    def __init__(self, name: str, birthdate: datetime.date, url: str):
        self.name = name
        self.birthdate = birthdate
        self.url = url

    def __repr__(self):
        return f'Player({self.name}, {self.birthdate.strftime("%Y-%m-%d")})'

    def __str__(self):
        return self.name


def normalize_player_name(player_name: PlayerName) -> PlayerName:
    """
    Normalizes a player name to a standard format.
    """
    return player_name.replace('.', '')


def looks_like_player_name(s: str) -> bool:
    """
    Heuristically determines if the given string looks like a player name.

    "Justin Holiday" -> True
    "2029 second round pick (?-?)" -> False
    "cash" -> False
    "Timberwolves option to swap 2024 second round picks with Lakers (?-?)" -> False

    Note that some names have a lower-case "de" in them, e.g. "Remon Van de Hare".
    """
    if s == 'Nene':
        return True
    tokens = s.split()

    # "a" for "Luc Mbah a Moute"
    return 1 < len(tokens) < 6 and all(t[0].isupper() or t in ('de', 'a') for t in tokens)
