"""
Provides utilities to download and parse data from basketball-reference.com.
"""
import datetime
from collections import defaultdict
from typing import Iterable, List, Dict, Optional, Set

import bs4
from joblib import Memory

from players import Player, normalize_player_name, PlayerName
import repo
import web
from web import check_url

BASKETBALL_REFERENCE_URL = 'https://www.basketball-reference.com'
CACHE_HOT_DAYS = 7


memory = Memory(repo.joblib_cache(), verbose=0)


def _get_all_players_from_url(url: str) -> Iterable[Player]:
    html = web.fetch(url, stale_window_in_days=CACHE_HOT_DAYS, verbose=True)
    soup = bs4.BeautifulSoup(html, features='html.parser')
    tbody = soup.find('tbody')
    for tr in tbody.find_all('tr'):
        try:
            th = tr.find('th')
            a = th.find('a')
            href = a['href']
            name = normalize_player_name(a.text)
            player_url = BASKETBALL_REFERENCE_URL + href

            td_list = list(tr.find_all('td'))
            birthday_td = td_list[5]
            birthday_a = birthday_td.find('a')
            if birthday_a is None:
                # Some old-timers have missing birthdays. Ok to skip these.
                continue
            birthday_str = birthday_a.text  # June 24, 1968
            birthdate = datetime.datetime.strptime(birthday_str, '%B %d, %Y').date()
            yield Player(name, birthdate, player_url)
        except Exception:
            raise Exception(f'Failed to parse player from:\n\n{tr}')


@memory.cache
def _get_all_players_from_url_cached(url: str) -> List[Player]:
    return list(_get_all_players_from_url(url))


def _get_all_players_iterable() -> Iterable[Player]:
    # iterate over chars of alphabet
    for c in 'abcdefghijklmnopqrstuvwxyz':
        url = f'{BASKETBALL_REFERENCE_URL}/players/{c}/'
        if check_url(url, stale_window_in_days=CACHE_HOT_DAYS):
            yield from _get_all_players_from_url_cached(url)
        else:
            yield from _get_all_players_from_url(url)


def get_all_players() -> List[Player]:
    return list(_get_all_players_iterable())


class InvalidPlayerException(Exception):
    def __init__(self, name: PlayerName, birthdate: Optional[datetime.date] = None,
                 valid_birthdates: Optional[Set[datetime.date]] = None):
        msg = f'No player named {name}'
        if birthdate is not None:
            msg += f' with birthdate {birthdate.strftime("%Y-%m-%d")}'
            if valid_birthdates:
                valid_birthdates_str = ', '.join(d.strftime('%Y-%m-%d') for d in sorted(valid_birthdates))
                msg += f' (valid birthdates: {valid_birthdates_str})'
        super().__init__(msg)


class AmbiguousPlayerException(Exception):
    def __init__(self, name: PlayerName, valid_birthdates: Set[datetime.date]):
        msg = f'Multiple players in NBA history named "{name}", birthdate disambiguation required'
        valid_birthdates_str = ', '.join(d.strftime('%Y-%m-%d') for d in sorted(valid_birthdates))
        msg += f' (valid birthdates: {valid_birthdates_str})'
        super().__init__(msg)


class PlayerDirectory:
    def __init__(self):
        self._lookup: Dict[PlayerName, Dict[datetime.date, Player]] = defaultdict(dict)
        for player in get_all_players():
            subdict = self._lookup[player.name]
            if player.birthdate in subdict:
                raise Exception(f'Duplicate player: {player}')
            subdict[player.birthdate] = player

    def get(self, name: PlayerName, birthdate: Optional[datetime.date] = None) -> Player:
        subdict = self._lookup.get(name, None)
        assert subdict is None or len(subdict) > 0, 'Unexpected PlayerDirectory state'

        if subdict is None:
            raise InvalidPlayerException(name)

        if birthdate is None:
            if len(subdict) == 1:
                return list(subdict.values())[0]
            raise AmbiguousPlayerException(name, set(subdict.keys()))

        player = subdict.get(birthdate, None)
        if player is None:
            raise InvalidPlayerException(name, birthdate, set(subdict.keys()))

        return player


if __name__ == '__main__':
    directory = PlayerDirectory()
