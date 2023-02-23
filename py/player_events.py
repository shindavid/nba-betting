"""
Provides utilities to download and parse historical player event data. This includes signings, waivers, trades, and
injuries.
"""
import calendar
import datetime
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Iterable
from urllib.parse import urlencode

import bs4
from joblib import Memory

import repo
import web
from bball_reference import PlayerDirectory, InvalidPlayerException, PlayerMatchException
from cache_util import cached, SEC_PER_DAY
from players import normalize_player_name, looks_like_player_name, Player, FakePlayer
from str_util import strip_punctuation, extract_parenthesized_strs, remove_parenthesized_strs
from teams import Team, TeamNameParseError

TRANSACTIONS_URL = 'https://prosportstransactions.com/basketball/Search/SearchResults.php'
LEBRON_JAMES_DRAFT_DATE = datetime.date(2003, 6, 26)
START_DATE = LEBRON_JAMES_DRAFT_DATE
CACHE_HOT_DAYS = 3  # assume that website data is locked after this many days


memory = Memory(repo.joblib_cache(), verbose=0)
_current_url = None


class PlayerEvent:
    # team = None means that the team no longer exists (e.g., Sonics)
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        self.date = date
        self.team = team
        self.player = player
        self.notes = notes


class Acquisition(PlayerEvent):
    """
    An Acquisition is a transaction that adds a player to a team, by signing, trade, or draft.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'Acquisition({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class Relinquishing(PlayerEvent):
    """
    A Relinquishing is a transaction that removes a player from a team, either via trade or waiver.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'Relinquishing({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class ILPlacement(PlayerEvent):
    """
    An ILPlacement is a transaction that places a player on the Injured List.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'ILPlacement({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class ILActivation(PlayerEvent):
    """
    An ILActivation is a transaction that activates a player from the Injured List.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'ILActivation({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class MissedGame(PlayerEvent):
    """
    A MissedGame is a transaction that indicates a player missed a game due to injury, personal reason, or suspension.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'MissedGame({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class Suspension(PlayerEvent):
    """
    A Suspension is a transaction that indicates a player was suspended for 1 or more games.
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'Suspension({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class ReturnToLineup(PlayerEvent):
    """
    A ReturnToLineup is a transaction that returns a player to the lineup after missing games (MissedGame or
    Suspension).

    TODO: merge with ILActivation?
    """
    def __init__(self, date: datetime.date, team: Optional[Team], player: Player, notes: str):
        super().__init__(date, team, player, notes)

    def __str__(self):
        return f'ReturnToLineup({self.date.strftime("%Y-%m-%d")}, {self.team}, {self.player}, "{self.notes}")'


class PlayerEventCategory(Enum):
    PlayerMovement = 'PlayerMovement'
    IL = 'IL'
    Injuries = 'Injuries'
    Personal = 'Personal'
    Disciplinary = 'Disciplinary'


@dataclass
class RawPlayerEventData:
    date: datetime.date
    team: Team
    acquired_player: Optional[Player]
    relinquished_player: Optional[Player]
    notes: str


class PlayerNameExtractionError(Exception):
    def __init__(self, player_name_str: str, detail: str = ''):
        msg = 'Could not extract player name from string "{}"'.format(player_name_str)
        if detail:
            msg += f' ({detail})'
        super().__init__(msg)


def extract_players(directory: PlayerDirectory, html_str: str) -> Iterable[Player]:
    """
    Accepts a string from either the "Acquired" or "Relinquished" column of the search results page. Parses a list of
    players from the string and returns them.

    The string is a bulleted list of player names and other traded assets. These other assets include strings like,

    "2029 second round pick (?-?)"
    "cash"
    "Timberwolves option to swap 2024 second round picks with Lakers (?-?)"

    Only the players are returned.

    There are a number of complexities to note:

    MULTIPLE NAMES

    Some players go by multiple names. The website writes these in a format like these:

    "Nah'Shon Hyland / Bones Hyland"
    "Justin Jackson (Aaron)"
    "Herbert Jones / Herb Jones (Keyshawn)"
    "(William) Tony Parker"
    "Michael Smith (John) (Providence)"

    In these cases, the multiple names are checked against the names in basketball-reference.com. If exactly
    one of them match, that one is returned. Else, returns a FakePlayer with the name as it appears on the website.

    BIRTHDATE CLARIFIERS

    Some players have naming collisions with other names, which the website resolves by adding the player's
    birthdate in parentheses:

    Brandon Williams (b. 1975-02-27)

    CHARACTER CODES:

    Some players, the website disambiguates collisions by adding a single character identifier in parentheses:

    "Mike Smith (b)"
    """
    if not html_str:
        return []
    if html_str == 'v':  # website typo
        return []

    if html_str.find('2019 conditional second round pick (less favorable of a) Blazers pick and b) most ') != -1:
        # website typo
        return []

    non_player_terms = ('cash',
                        'considerations',
                        'draft',
                        'exception',
                        'exemption',
                        'group',
                        'option',
                        'pick',
                        'picks',
                        'rights',
                        'select',
                        )

    # some players were traded/released but never played a game, and so are missing from
    # basketball-reference.com
    #
    # Most such players are caught elsewhere by checking "drafted" and "waived", but some slip by. Those players
    # are explicitly listed here.
    players_who_never_played = (
        'Danny Forston',
        'Livan Pyfrom',
        'Josh Moore',
        'Jon Stefansson',
        'Chris Marcus',
        '(Sean) Chris Smith',
    )

    disambiguation_special_cases0 = {
        'Roy Devyn Marble / Roy Marble (Devyn)': 'Devyn Marble',
        'Etorre Messina (P) / Ettore Messina (SN)': 'Etorre Messina',
        'Ruben Nembhard / R.J. Nembhard Jr.': ''
    }

    disambiguation_special_cases1 = {
        ('Ken Johnson', 'Allen'): datetime.date(1978, 2, 1),
        ('Mike James', 'Lamont'): datetime.date(1975, 6, 23),
        ('Mike Dunleavy', 'Sr.'): datetime.date(1954, 3, 21),
        ('Luke Jackson', 'Ryan'): datetime.date(1981, 11, 6),
        ('Charles Smith', 'Cornelius'): datetime.date(1975, 8, 22),
        ('Cedric Henderson', 'Earl'): datetime.date(1975, 3, 11),
        ('Marcus Williams', 'D.'): datetime.date(1985, 12, 3),
        ('Marcus Williams', 'Eliot'): datetime.date(1986, 11, 18),
        ('Bobby Jones', 'Ray'): datetime.date(1984, 1, 9),
        ('Mike Smith', 'b'): datetime.date(1976, 4, 15),
        ('Jerry Smith', 'b'): datetime.date(1987, 9, 26),
        ('Mike Scott', 'James'): datetime.date(1988, 7, 16),
        ('Tony Mitchell', 'LaShae'): datetime.date(1992, 4, 7),
        ('Brandon Williams', 'D.'): datetime.date(1975, 2, 27),
        ('Justin Jackson', 'Aaron'): datetime.date(1995, 3, 28),
        ('Mike James', 'Perry'): datetime.date(1990, 8, 18),
    }

    disambiguation_special_cases2 = {
        'Kenyon Martin Sr': ('Kenyon Martin', datetime.date(1977, 12, 30)),
        'Mike Dunleavy Jr': ('Mike Dunleavy', datetime.date(1980, 9, 15)),
    }

    disambiguation_special_cases3 = {
        'Jeffery Taylor': ('Jeff Taylor', datetime.date(1989, 5, 23)),
        'Jeff Taylor': ('Jeff Taylor', datetime.date(1989, 5, 23)),
        'Daniel Nwaelele': ('Daniel Nwaelele', None),
        'Dan Nwaelele': ('Daniel Nwaelele', None),
    }

    dot = '•'
    tokens = [t.strip() for t in html_str.split(dot) if t]
    for t in tokens:
        if True:
            yield normalize_player_name(t)
            continue

        subtokens = [strip_punctuation(w) for w in t.split()]
        non_player = any(t in non_player_terms for t in subtokens)
        if non_player:
            continue

        if t in players_who_never_played:
            continue

        t = disambiguation_special_cases0.get(t, t)

        parenthesized_strs = tuple(extract_parenthesized_strs(t))
        unparenthesized_str = remove_parenthesized_strs(t)
        raw_names = [n.strip() for n in unparenthesized_str.split('/')]
        name_birthdates = []
        for name in raw_names:
            if not parenthesized_strs:
                name_birthdates.append((name, None))
                continue

            primary_name = name

            birthdate = None
            if not primary_name:
                raise PlayerNameExtractionError(html_str, name)
            last_name = primary_name.split()[-1]

            if primary_name in disambiguation_special_cases3:
                primary_name, birthdate = disambiguation_special_cases3[primary_name]
            elif len(parenthesized_strs) > 1:
                if parenthesized_strs == ('John', 'Providence'):
                    birthdate = datetime.date(1972, 3, 28)
            elif parenthesized_strs:
                alternate_first_name = parenthesized_strs[0]
                if alternate_first_name.startswith('b. '):
                    # birthdate disambiguation
                    birthdate = datetime.datetime.strptime(alternate_first_name[3:], '%Y-%m-%d').date()
                elif alternate_first_name.startswith('changed to '):
                    # Marcus Banks (changed to Jumaine Jones on 2004-08-13)
                    pass
                elif alternate_first_name in ('CBC E', 'CBS NBA P R S',):  # weird case for "Daniel Nwaelele"
                    pass
                elif (primary_name, alternate_first_name) in disambiguation_special_cases1:
                    birthdate = disambiguation_special_cases1[(primary_name, alternate_first_name)]
                elif len(alternate_first_name) == 1 and alternate_first_name.islower():
                    continue
                else:
                    name_birthdates.append((f'{alternate_first_name} {last_name}', None))
            name_birthdates.append((primary_name, birthdate))

        name_birthdates = [(normalize_player_name(n), b) for n, b in name_birthdates]
        name_birthdates = [disambiguation_special_cases2.get(n, (n, b)) for n, b in name_birthdates]
        name_birthdates = list(set(name_birthdates))
        for name, _ in name_birthdates:
            if not looks_like_player_name(name):
                raise PlayerNameExtractionError(html_str, name)

        if len(name_birthdates) == 1:
            name, birthdate = name_birthdates[0]
            try:
                yield directory.get(name, birthdate)
            except PlayerMatchException as e:
                if name in players_who_never_played:
                    continue
                return FakePlayer(name)
            continue

        # multiple names, look for one that matches RosterData
        matches = []
        omit_count = 0
        for name, birthdate in name_birthdates:
            try:
                matches.append(directory.get(name, birthdate))
            except InvalidPlayerException as e:
                # if name in players_who_never_played:
                #     omit_count += 1
                #     continue
                continue

        if not matches:
            if omit_count:
                continue
            return FakePlayer(raw_names)

        if len(matches) > 1:
            raise PlayerNameExtractionError(html_str, f'Multiple names matched: {matches} for "{t}" [{name_birthdates}]')
        yield matches[0]


def _get_raw_data(start_dt: datetime.date, end_dt: datetime.date, directory: PlayerDirectory,
                  category: PlayerEventCategory) -> List[RawPlayerEventData]:
    category_str = category.value
    start_dt_str = start_dt.strftime('%Y-%m-%d')
    end_dt_str = end_dt.strftime('%Y-%m-%d')
    params = {
        'BeginDate': start_dt_str,
        'EndDate': end_dt_str,
        f'{category_str}ChkBx': 'yes',
        'Submit': 'Search',
    }

    url = f'{TRANSACTIONS_URL}?{urlencode(params)}'
    return list(_get_raw_data_from_url(url, start_dt, end_dt, directory))


def trust_cached_data_for(dt: datetime.date) -> bool:
    return dt < datetime.date.today() - datetime.timedelta(days=CACHE_HOT_DAYS)


DEBUG = defaultdict(set)


def _get_raw_data_from_url(url, start_dt: datetime.date, end_dt: datetime.date,
                           directory: PlayerDirectory) -> Iterable[RawPlayerEventData]:
    global _current_url
    _current_url = url

    stale_is_ok = trust_cached_data_for(end_dt)
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

        notes = tokens[4]

        acquired_players = list(extract_players(directory, tokens[2]))
        relinquished_players = list(extract_players(directory, tokens[3]))
        for p in acquired_players + relinquished_players:
            try:
                q = directory.get(p)
            except PlayerMatchException as e:
                DEBUG[p].add(notes)

        if True:
            continue

        aux_phrases = ('transfer of ownership',
                       'purchased team',
                       'hired as president',
                       'agreement reached for transfer',
                       'general manager',
                       'owner deceased',)
        if any(notes.find(p) != -1 for p in aux_phrases):
            continue

        if tokens[2] == '• Marion Hillard' and date == datetime.date(2017, 11, 5):
            # website data bug, this player retired in 1976!
            continue

        if tokens[1] == 'Browns':
            # website data bug, NFL data made it in somehow!
            continue

        try:
            team = Team.parse(tokens[1])
        except TeamNameParseError as e:
            if tokens[1] in ('Sonics', 'Bobcats'):
                # Some teams that don't exist anymore, or were renamed. For our purposes, we don't care about matching
                # up old team names with current ones
                team = None
                pass
            else:
                raise e

        try:
            acquired_players = list(extract_players(directory, tokens[2]))
        except PlayerNameExtractionError as e:
            # some known bugs in data
            if date == datetime.date(2018, 4, 1) and tokens[2].endswith(' Cavaliers'):
                continue
            if date == datetime.date(2019, 12, 31) and tokens[2].endswith(' 11/25/2019'):
                continue
            if tokens[2].find('placed on IL') > -1:
                continue
            raise e

        try:
            relinquished_players = list(extract_players(directory, tokens[3]))
        except PlayerNameExtractionError as e:
            # some known bugs in data
            if date == datetime.date(2023, 1, 6) and tokens[3].find(' strained left quadriceps ') > -1:
                continue
            if date == datetime.date(2022, 11, 21) and tokens[3].find(' Heat') > -1:
                continue
            if date == datetime.date(2004, 7, 7) and tokens[3].find(' Kings') > -1:
                continue
            if date == datetime.date(2018, 12, 27) and tokens[3].endswith(' 76ers'):
                continue
            if date == datetime.date(2020, 12, 27) and tokens[3].find('left wrist injury') != -1:
                continue
            if date == datetime.date(2021, 11, 3) and tokens[3].find('NBA health and safety protocols') != -1:
                continue
            raise e

        if any(isinstance(p, FakePlayer) for p in acquired_players):
            phrases = ('round pick',  # drafted but never played
                       'signed free agent',  # signed but never played
                       'assistant coach',
                       'head coach',
                       'general manager',
                       'director',
                       'athletic trainer',
                       'hired as ',
                       'promoted to ',
                       )
            assert any(notes.find(p) != -1 for p in phrases), acquired_players
            acquired_players = []

        if any(isinstance(p, FakePlayer) for p in relinquished_players):
            phrases = ('assistant coach',
                       'head coach',
                       'general manager',
                       'director',
                       'president',
                       'athletic trainer',
                       'fired as ',
                       'demoted ',
                       'waived',  # likely never played a game in the NBA
                       )
            assert any(notes.find(p) != -1 for p in phrases), relinquished_players
            relinquished_players = []

        for acquired_player in acquired_players:
            yield RawPlayerEventData(date, team, acquired_player, None, notes)
        for relinquished_player in relinquished_players:
            yield RawPlayerEventData(date, team, None, relinquished_player, notes)

    next_tags = [a for a in soup.find_all('a') if a.text == 'Next']
    assert len(next_tags) <= 1
    for tag in next_tags:
        href = tag['href']
        query_str = href[href.find('?'):]
        yield from _get_raw_data_from_url(f'{TRANSACTIONS_URL}{query_str}', start_dt, end_dt, directory)


@cached(expires_after_sec=lambda start_dt, end_dt: None if trust_cached_data_for(end_dt) else SEC_PER_DAY)
def get_player_events(start_dt: datetime.date, end_dt: datetime.date) -> List[PlayerEvent]:
    return list(_get_player_events_iterable(start_dt, end_dt))


def _get_player_events_iterable(start_dt: datetime.date, end_dt: datetime.date) -> Iterable[PlayerEvent]:
    """
    Returns all player events on the given date.
    """
    directory = PlayerDirectory.instance()

    non_player_jobs = ('coach', 'manager', 'gm', 'president', 'owner', 'advisor', 'director', 'coordinator', 'scout',
                       'executive', 'trainer', 'assistant', 'vp', 'ownership')
    moves = _get_raw_data(start_dt, end_dt, directory, PlayerEventCategory.PlayerMovement)
    for move in moves:
        assert None in (move.acquired_player, move.relinquished_player), move
        assert move.acquired_player is not None or move.relinquished_player is not None, move
        words = [strip_punctuation(w).lower() for w in move.notes.split()]
        if any(title in words for title in non_player_jobs):
            continue
        if move.relinquished_player is not None:
            assert not isinstance(move.relinquished_player, FakePlayer), move
            yield Relinquishing(move.date, move.team, move.relinquished_player, move.notes)
        else:
            assert not isinstance(move.acquired_player, FakePlayer), move
            yield Acquisition(move.date, move.team, move.acquired_player, move.notes)

    results = _get_raw_data(start_dt, end_dt, directory, PlayerEventCategory.IL)
    for result in results:
        assert None in (result.acquired_player, result.relinquished_player), result
        assert result.acquired_player is not None or result.relinquished_player is not None, result
        notes = result.notes
        if result.acquired_player is not None:
            assert not isinstance(result.acquired_player, FakePlayer), result
            tokens = notes.split()
            if notes.startswith('placed on IL') or notes.find('(out indefinitely)') != -1:
                # website bug, this is mis-categorized as an activation
                yield ILPlacement(result.date, result.team, result.acquired_player, result.notes)
                continue
            if notes == 'IL':
                # website data issue, this is James Harden reactivation
                assert result.date == datetime.date(2018, 11, 3) and result.acquired_player.name == 'James Harden', result
            elif notes.startswith('player returned to team'):
                assert result.date == datetime.date(2019, 1, 22) and result.acquired_player.name == 'Carmelo Anthony', result
            else:
                assert tokens[0].find('activated') != -1 or notes.startswith('returned '), result
            yield ILActivation(result.date, result.team, result.acquired_player, result.notes)
        else:
            assert not isinstance(result.relinquished_player, FakePlayer), result
            if notes.find('(DNP)') != -1:
                # website bug, this is mis-categorized as a placement on IL
                yield MissedGame(result.date, result.team, result.relinquished_player, result.notes)
                continue
            if notes == 'waived':
                # website bug, this is mis-categorized as a placement on IL
                yield Relinquishing(result.date, result.team, result.relinquished_player, result.notes)
                continue
            if notes.startswith('activated '):
                # website bug, this is mis-categorized as a placement on IL
                yield ILActivation(result.date, result.team, result.relinquished_player, result.notes)
                continue
            if notes.find('(DTD)') != -1:
                pass
            else:
                assert any([notes.startswith('placed on I'),
                            notes.startswith('out '),
                            notes.find('(out indefinitely)') != -1,
                            notes.find('(already on IL)') != -1,
                            notes.startswith('player not with team'),  # Carmelo Anthony saga
                            notes.find('(out for season)') != -1]), result
            yield ILPlacement(result.date, result.team, result.relinquished_player, result.notes)

    results = _get_raw_data(start_dt, end_dt, directory, PlayerEventCategory.Injuries)
    for result in results:
        assert None in (result.acquired_player, result.relinquished_player), result
        assert result.acquired_player is not None or result.relinquished_player is not None, result
        if result.acquired_player is not None:
            assert not isinstance(result.acquired_player, FakePlayer), result
            tokens = [strip_punctuation(w).lower() for w in result.notes.split()]
            if result.notes.find('(out for season)') != -1:
                # website bug, this is mis-categorized as a return from IL
                yield ILPlacement(result.date, result.team, result.acquired_player, result.notes)
                continue
            if result.notes.find('(DNP)') != -1:
                # website bug, this is mis-categorized as a return from IL
                yield MissedGame(result.date, result.team, result.acquired_player, result.notes)
                continue
            if all(w in tokens for w in ('coach', 'returned')):
                continue
            phrases = ('returned to lineup', 'activated from',)
            assert any(result.notes.startswith(p) for p in phrases), result
            yield ReturnToLineup(result.date, result.team, result.acquired_player, result.notes)
        else:
            assert not isinstance(result.relinquished_player, FakePlayer), result
            yield MissedGame(result.date, result.team, result.relinquished_player, result.notes)

    results = _get_raw_data(start_dt, end_dt, directory, PlayerEventCategory.Personal)
    for result in results:
        assert None in (result.acquired_player, result.relinquished_player), result
        assert result.acquired_player is not None or result.relinquished_player is not None, result
        if result.acquired_player is not None:
            assert not isinstance(result.acquired_player, FakePlayer), result
            if result.notes.startswith('returned as head coach'):
                continue
            phrases = ('returned to lineup', 'activated from IL',)
            assert any(result.notes.startswith(p) for p in phrases), result
            yield ReturnToLineup(result.date, result.team, result.acquired_player, result.notes)
        else:
            assert not isinstance(result.relinquished_player, FakePlayer), result
            yield MissedGame(result.date, result.team, result.relinquished_player, result.notes)

    results = _get_raw_data(start_dt, end_dt, directory, PlayerEventCategory.Disciplinary)
    for result in results:
        assert None in (result.acquired_player, result.relinquished_player), result
        assert result.acquired_player is not None or result.relinquished_player is not None, result
        if result.acquired_player is not None:
            assert not isinstance(result.acquired_player, FakePlayer), result
            tokens = [strip_punctuation(w) for w in result.notes.split()]
            if tokens[0] == 'suspended':
                # website bug, this is mis-categorized as a return to lineup
                yield Suspension(result.date, result.team, result.acquired_player, result.notes)
                continue
            if tokens[0] == 'GM':
                continue
            if result.notes.startswith('earlier suspension rescinded'):
                pass
            else:
                assert tokens[0] in ('returned', 'reinstated', 'activated'), result
                if len(tokens) == 1:
                    pass
                elif tokens[1] == 'to':
                    assert tokens[2] in ('lineup',), result
                elif tokens[1] == 'by':
                    assert tokens[2] in ('NBA', 'team'), result
                elif tokens[1] == 'from':
                    # "susension"/"supspension": typo in data
                    assert tokens[2] in ('IL', 'suspension', 'susension', 'suspended', 'supspension'), result
                else:
                    raise Exception(result)
            yield ReturnToLineup(result.date, result.team, result.acquired_player, result.notes)
        else:
            assert not isinstance(result.relinquished_player, FakePlayer), result
            tokens = result.notes.split()
            if any(w in tokens for w in ('fined', 'gined')):  # "gined": typo in data
                continue
            if result.notes.find('suspension reduced') != -1:
                continue
            if result.notes.find('(DNP)') != -1:
                # website bug, this is mis-categorized as a suspension
                yield MissedGame(result.date, result.team, result.relinquished_player, result.notes)
                continue
            if result.notes == 'placed on IL':
                # website bug, this is mis-categorized as a suspension
                yield ILPlacement(result.date, result.team, result.relinquished_player, result.notes)
                continue
            if result.notes.startswith('assigned to NBADL'):
                # website bug, this is mis-categorized as a suspension
                yield Relinquishing(result.date, result.team, result.relinquished_player, result.notes)
                continue

            aux_start_phrases = ('assistant coach suspended', 'player issued warning',)
            if any(result.notes.startswith(p) for p in aux_start_phrases):
                continue
            if result.notes.startswith('placed on IL'):
                reasons = ('suspension', 'suspended', 'disciplinary', 'discliplinary')  # "discliplinary": typo in data
                assert any(result.notes.find(w) != -1 for w in reasons), result
            else:
                other_start_phrases = (
                    'suspended ',
                    'placed on suspended list',
                    'team kicked player out',
                    'excused by team',
                    'banned by NBA',
                    'disciplinary reasons',
                    'player began serving suspension',
                    'player excused',
                    'player will not participate',
                    'player began serving',
                    'player became serving',
                    'player not with team',
                    'disciplinary ',
                    'disqualified from ',
                )
                assert any(result.notes.startswith(p) for p in other_start_phrases), result
            yield Suspension(result.date, result.team, result.relinquished_player, result.notes)


@cached(expires_after_sec=SEC_PER_DAY)
def get_all_player_events() -> List[PlayerEvent]:
    return list(_get_all_player_events_iterable())


def _get_all_player_events_iterable():
    # batch older dates into entire months
    today = datetime.date.today()

    last_untrusted_dt = today - datetime.timedelta(days=CACHE_HOT_DAYS)
    last_batch_dt = last_untrusted_dt.replace(day=1) - datetime.timedelta(days=1)

    dt = datetime.date(2018, 9, 1)
#    dt = START_DATE
    while dt <= last_batch_dt:
        start_dt = dt
        end_dt = dt.replace(day=calendar.monthrange(dt.year, dt.month)[1])
        for t in get_player_events(start_dt, end_dt):
            yield t
        dt = end_dt + datetime.timedelta(days=1)

    while dt <= today:
        for t in get_player_events(dt, dt):
            yield t
        dt += datetime.timedelta(days=1)

    directory = PlayerDirectory.instance()
    for p, notes_set in DEBUG.items():
        candidates = directory.get_candidate_matches(p)
        for notes in notes_set:
            print(f'# {notes}')

        if not candidates:
            print(f'EXCEPTIONS["{p}"] = None')
        else:
            for candidate in candidates:
                print(f'EXCEPTIONS["{p}"] = {repr(candidate)}')
        print('')