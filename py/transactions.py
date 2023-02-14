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


def extract_player_names(html_str: str) -> List[PlayerName]:
    """
    Accepts a string from either the "Acquired" or "Relinquished" column of the search results page. Parses a list of
    players from the string and returns them.

    The string is a bulleted list of player names and other traded assets. These other assets include strings like,

    "2029 second round pick (?-?)"
    "cash"
    "Timberwolves option to swap 2024 second round picks with Lakers (?-?)"

    Only the players are returned.

    Also, some players go by multiple names. The website writes these in either of the below formats:

    "Nah'Shon Hyland / Bones Hyland"
    "Justin Jackson (Aaron)"

    In these cases, the multiple names are checked against the names in RosterData (fetched from nbastuffer.com). If
    one of them match, that one is returned. Otherwise, the first name provided is returned.

    Finally, some players have naming collisions with other names, which the website resolves by adding the player's
    birthdate in parantheses:

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

        names = [n.strip() for n in t.split('/')]
        if len(names) == 1 and names[0].find('(') > -1:
            # Justin Jackson (Aaron)
            # Brandon Williams (b. 1975-02-27)
            name = names[0]
            primary_name = name[:name.find('(')].strip()
            last_name = primary_name.split()[-1]
            assert len(primary_name.split()) == 2, name
            alternate_first_name = name[name.find('(') + 1:name.find(')')]
            if alternate_first_name.startswith('b. '):
                # this is a birthdate disambiguation, ignore it for now
                names = [primary_name]
            else:
                names = [primary_name, f'{alternate_first_name} {last_name}']

        names = [normalize_player_name(n) for n in names]

        for name in names:
            assert looks_like_player_name(name), (t, name, html_str)

        if len(names) == 1:
            yield names[0]
            continue

        # multiple names, look for one that matches RosterData
        matched_names = [n for n in names if n in all_player_names]
        if not matched_names:
            yield names[0]
            continue
        if len(matched_names) > 1:
            raise ValueError(f'Multiple names matched: {matched_names} for "{t}"')
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
        acquired_players = extract_player_names(tokens[2])
        relinquished_players = extract_player_names(tokens[3])
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


def get_transactions(dt: datetime.date):
    """
    Returns all transactions on the given date.
    """
    moves = _get_raw_data(dt, TransactionCategory.PlayerMovement)
    for move in moves:
        pass
        # print(move)


if __name__ == '__main__':
    dt = datetime.date(2023, 2, 1)
    for _ in range(300):
        dt -= datetime.timedelta(days=1)
        get_transactions(dt)
