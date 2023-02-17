import datetime
from typing import Union, List

from unidecode import unidecode


PlayerName = str


class Player:
    def __init__(self, name: str, birthdate: datetime.date, active: bool, url: str):
        self.name = name
        self.birthdate = birthdate
        self.active = active
        self.url = url

    def __repr__(self):
        dt_str = f'datetime.date({self.birthdate.year}, {self.birthdate.month}, {self.birthdate.day})'
        return f'Player("{self.name}", {dt_str}, {self.active}, "{self.url}")'

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.url == other.url

    def __hash__(self):
        return hash(self.url)


class FakePlayer(Player):
    def __init__(self, name: Union[str, List[str]]):
        names = name if isinstance(name, list) else [name]
        name_str = ' or '.join(names)
        super().__init__(name_str, datetime.date(1900, 1, 1), False, '')
        self.names = names


def normalize_player_name(player_name: PlayerName) -> PlayerName:
    """
    Normalizes a player name to a standard format.
    """
    name = unidecode(player_name.replace('.', ''))  # "B.J. Johnson" -> "BJ Johnson"

    # always capitalize the letter following an apostrophe
    chars = list(name)
    for i, c in enumerate(chars):
        if c == "'":
            chars[i + 1] = chars[i + 1].upper()
    name = ''.join(chars)

    # ...except for single-letter post-apostrophe cases like "Amar'e Stoudemire"
    tokens = name.split()
    for i, t in enumerate(tokens):
        if len(t)>1 and t[-2] == "'":
            tokens[i] = t[:-2] + t[-2:].lower()
    name = ' '.join(tokens)

    special_cases = {
        # 'Linton Johnson III': 'Linton Johnson',
        # 'Roger Mason Jr': 'Roger Mason',
        'Britton Johnson': 'Britton Johnsen',  # typo in prosporttransactions.com (this probably belongs elsewhere)
        'Ruben Boumtje Boumtje': 'Ruben Boumtje-Boumtje',
    }
    return special_cases.get(name, name)


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
