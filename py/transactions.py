"""
Provides utilities to download and parse historical transaction data. This includes signings, waivers, trades, and
injuries.
"""
import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Iterable
from urllib.parse import urlencode

import bs4

import web
from rosters import PlayerName, normalize_player_name, looks_like_player_name, RosterData
from teams import Team

TRANSACTIONS_URL = 'https://prosportstransactions.com/basketball/Search/SearchResults.php'


class Transaction:
    def __init__(self, date: datetime.date, team: Team, player: str, notes: str):
        self.date = date
        self.team = team
        self.player = player
        self.notes = notes


class Acquisition(Transaction):
    """
    An Acquisition is a transaction that adds a player to a team.
    """
    def __init__(self, date: datetime.date, team: Team, player: str, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'Acquisition({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class Relinquishing(Transaction):
    """
    A Relinquishing is a transaction that removes a player from a team.
    """
    def __init__(self, date: datetime.date, team: Team, player: str, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'Relinquishing({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class ILPlacement(Transaction):
    """
    An ILPlacement is a transaction that places a player on the Injured List.
    """
    def __init__(self, date: datetime.date, team: Team, player: str, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'ILPlacement({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class ILActivation(Transaction):
    """
    An ILActivation is a transaction that activates a player from the Injured List.
    """
    def __init__(self, date: datetime.date, team: Team, player: str, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'ILActivation({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class TransactionCategory(Enum):
    PlayerMovement = 'PlayerMovement'
    IL = 'IL'
    Injuries = 'Injuries'
    Personal = 'Personal'
    Disciplinary = 'Disciplinary'


@dataclass
class RawTransactionData:
    date: datetime.date
    team: Team
    acquired_player: Optional[PlayerName]
    relinquished_player: Optional[PlayerName]
    notes: str


class PlayerNameExtractionError(Exception):
    def __init__(self, player_name_str: str, detail: str = ''):
        msg = 'Could not extract player name from string "{}"'.format(player_name_str)
        if detail:
            msg += ' ' + detail
        super().__init__(msg)


def extract_player_names(html_str: str) -> Iterable[PlayerName]:
    """
    Accepts a string from either the "Acquired" or "Relinquished" column of the search results page. Parses a list of
    players from the string and returns them.

    The string is a bulleted list of player names and other traded assets. These other assets include strings like,

    "2029 second round pick (?-?)"
    "cash"
    "Timberwolves option to swap 2024 second round picks with Lakers (?-?)"

    Only the players are returned.

    Also, some players go by multiple names. The website writes these in a format like these:

    "Nah'Shon Hyland / Bones Hyland"
    "Justin Jackson (Aaron)"
    "Herbert Jones / Herb Jones (Keyshawn)"

    In these cases, the multiple names are checked against the names in RosterData (fetched from nbastuffer.com). If
    one of them match, that one is returned. Otherwise, the first name provided is returned.

    Finally, some players have naming collisions with other names, which the website resolves by adding the player's
    birthdate in parentheses:

    Brandon Williams (b. 1975-02-27)

    I am not sure how to handle this at present, as nbastuffer.com does not provide birthdates. Just ignoring the
    birthdates for now.
    """
    if not html_str:
        return []
    dot = '•'
    tokens = [t.strip() for t in html_str.split(dot) if t]
    all_player_names = RosterData.get_all_player_names()
    for t in tokens:
        non_player = False
        subtokens = t.split()
        for word in ('cash', 'pick', 'picks', 'option', 'group', 'rights'):
            if word in subtokens:
                non_player = True
                break
        if non_player:
            continue

        raw_names = [n.strip() for n in t.split('/')]
        names = []
        for name in raw_names:
            if name.find('(') == -1:
                names.append(name)
                continue

            # Justin Jackson (Aaron)
            # Brandon Williams (b. 1975-02-27)
            primary_name = name[:name.find('(')].strip()
            names.append(primary_name)
            last_name = primary_name.split()[-1]
            if len(primary_name.split()) != 2:
                raise PlayerNameExtractionError(html_str)
            alternate_first_name = name[name.find('(') + 1:name.find(')')]
            if alternate_first_name.startswith('b. '):
                # this is a birthdate disambiguation, ignore it for now
                pass
            else:
                names.append(f'{alternate_first_name} {last_name}')

        names = [normalize_player_name(n) for n in names]

        for name in names:
            if not looks_like_player_name(name):
                raise PlayerNameExtractionError(html_str)

        if len(names) == 1:
            yield names[0]
            continue

        # multiple names, look for one that matches RosterData
        matched_names = [n for n in names if n in all_player_names]
        if not matched_names:
            yield names[0]
            continue
        if len(matched_names) > 1:
            raise PlayerNameExtractionError(html_str, f'Multiple names matched: {matched_names} for "{t}"')
        yield matched_names[0]


def _get_raw_data(dt: datetime.date, category: TransactionCategory) -> List[RawTransactionData]:
    category_str = category.value
    dt_str = dt.strftime('%Y-%m-%d')
    params = {
        'BeginDate': dt_str,
        'EndDate': dt_str,
        f'{category_str}ChkBx': 'yes',
        'Submit': 'Search',
    }

    url = f'{TRANSACTIONS_URL}?{urlencode(params)}'
    return list(_get_raw_data_from_url(url, dt))


def _get_raw_data_from_url(url, dt: datetime.date) -> Iterable[RawTransactionData]:
    stale_is_ok = dt < datetime.date.today() - datetime.timedelta(days=3)
    html = web.fetch(url, stale_is_ok=stale_is_ok, verbose=False)

    if html.find('There were no matching transactions found.') != -1:
        return []
    soup = bs4.BeautifulSoup(html, features='html.parser')
    table = soup.find('table', class_='datatable center')
    assert table is not None

    header_tokens = []
    for tr in table.find_all('tr'):
        if not header_tokens:
            header_tokens = [td.text.strip() for td in tr.find_all('td')]
            assert header_tokens[0] == 'Date', tr
            assert header_tokens[1] == 'Team'
            assert header_tokens[2] == 'Acquired'
            assert header_tokens[3] == 'Relinquished'
            assert header_tokens[4] == 'Notes'
            continue
        tokens = [td.text.strip() for td in tr.find_all('td')]
        assert len(tokens) == len(header_tokens), (tokens, header_tokens)
        date = datetime.datetime.strptime(tokens[0], '%Y-%m-%d').date()
        if tokens[1] == '':
            # player without team retires
            continue
        team = Team.parse(tokens[1])
        try:
            acquired_players = list(extract_player_names(tokens[2]))
        except PlayerNameExtractionError as e:
            if tokens[2].find('placed on IL') > -1:
                # some dates mistakenly put this descr in the player column
                continue
            raise e

        try:
            relinquished_players = list(extract_player_names(tokens[3]))
        except PlayerNameExtractionError as e:
            if dt == datetime.date(2023, 1, 6) and tokens[3].find(' strained left quadriceps ') > -1:
                # this is a known error, ignore it for now
                continue
            raise e

        notes = tokens[4]
        for acquired_player in acquired_players:
            yield RawTransactionData(date, team, acquired_player, None, notes)
        for relinquished_player in relinquished_players:
            yield RawTransactionData(date, team, None, relinquished_player, notes)

    next_tags = [a for a in soup.find_all('a') if a.text == 'Next']
    assert len(next_tags) <= 1
    for tag in next_tags:
        href = tag['href']
        query_str = href[href.find('?'):]
        yield from _get_raw_data_from_url(f'{TRANSACTIONS_URL}{query_str}', dt)


def get_transactions(dt: datetime.date) -> Iterable[Transaction]:
    """
    Returns all transactions on the given date.
    """
    moves = _get_raw_data(dt, TransactionCategory.PlayerMovement)
    for move in moves:
        assert None in (move.acquired_player, move.relinquished_player), move
        assert move.acquired_player is not None or move.relinquished_player is not None, move
        if move.relinquished_player is not None:
            yield Relinquishing(move.date, move.team, move.relinquished_player, move.notes)
        else:
            yield Acquisition(move.date, move.team, move.acquired_player, move.notes)

    results = _get_raw_data(dt, TransactionCategory.IL)
    for result in results:
        assert None in (result.acquired_player, result.relinquished_player), result
        assert result.acquired_player is not None or result.relinquished_player is not None, result
        if result.acquired_player is not None:
            assert result.notes.startswith('activated from IL'), result
            yield ILActivation(result.date, result.team, result.acquired_player, result.notes)
        else:
            assert result.notes.startswith('placed on IL'), result
            yield ILPlacement(result.date, result.team, result.relinquished_player, result.notes)


if __name__ == '__main__':
    dt = datetime.date(2023, 2, 1)
    for _ in range(300):
        dt -= datetime.timedelta(days=1)
        for t in get_transactions(dt):
            print(t)
