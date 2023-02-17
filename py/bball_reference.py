"""
Provides utilities to download and parse data from basketball-reference.com.
"""
import datetime
from collections import defaultdict, Counter
from enum import Enum
from typing import Iterable, List, Dict, Optional, Set, Union

import bs4
from joblib import Memory

import repo
import web
from players import Player, normalize_player_name, PlayerName
from str_util import extract_parenthesized_strs, remove_parenthesized_strs
from teams import Team
from web import check_url

BASKETBALL_REFERENCE_URL = 'https://www.basketball-reference.com'
CACHE_HOT_DAYS = 7
Season = int  # 2002-2003 season is represented by 2003
FIRST_FULL_SEASON_POST_NBA_ABA_MERGER: Season = 1977


memory = Memory(repo.joblib_cache(), verbose=0)


INACTIVE_REASONS = {
    'Inactive',
    'Did Not Dress',
    'Not With Team',
    'Player Suspended',
}


class GameType(Enum):
    REGULAR_SEASON = 1
    PLAYOFFS = 2


class GameData:
    def __init__(self, dt: datetime.date, game_type: GameType, home_team: Team, away_team: Team,
                 home_score: Optional[int] = None, away_score: Optional[int] = None):
        self.dt = dt
        self.game_type = game_type
        self.home_team = home_team
        self.away_team = away_team
        self.home_score = home_score
        self.away_score = away_score
        self.home_team_days_rest: Optional[int] = None
        self.away_team_days_rest: Optional[int] = None

    def __eq__(self, other: 'GameData'):
        return (self.dt, self.home_team, self.away_team) == (other.dt, other.home_team, other.away_team)

    def __hash__(self):
        return hash((self.dt, self.home_team, self.away_team))

    def __repr__(self):
        return f'{self.__class__.__name__}({self.dt}, {self.game_type}, {self.home_team}, {self.away_team}, {self.home_score}, {self.away_score})'

    def __str__(self):
        return f'{self.away_team}@{self.home_team} on {self.dt.strftime("%Y-%m-%d")}'

    def set_days_rest(self, team: Team, days_rest: int):
        assert days_rest >= 0, (self, team, days_rest)
        if team == self.home_team:
            self.home_team_days_rest = days_rest
        elif team == self.away_team:
            self.away_team_days_rest = days_rest
        else:
            raise ValueError(f'Unknown team: {team}')

    @property
    def completed(self) -> bool:
        return self.home_score is not None

    @property
    def winning_team(self) -> Optional[Team]:
        return None if not self.completed else self.home_team if self.home_score > self.away_score else self.away_team

    @property
    def losing_team(self) -> Optional[Team]:
        return None if not self.completed else self.away_team if self.home_score > self.away_score else self.home_team


class GameLog:
    def __init__(self, player: Player, tag: Optional[bs4.element.Tag] = None, game: Optional[GameData] = None):
        """
        Pass tag for normal construction.

        In early NBA seasons, when players were injured, there appears to not be a game log entry for them. We want
        inactive GameLog's for these cases. In these cases, pass game to construct a GameLog.
        """
        self.player = player
        self.minutes = 0
        self.game = game
        self.inactive = (game is not None)
        self.dnp = False

        if tag is None:
            return

        game_directory = GameDirectory.instance()

        td_list = tag.find_all('td')

        reason_tds = [td for td in td_list if td.get('data-stat', None) == 'reason']
        if reason_tds:
            assert len(reason_tds) == 1, (player, tag)
            reason = reason_tds[0].text
            if reason in INACTIVE_REASONS:
                self.inactive = True
            elif reason == 'Did Not Play':
                self.dnp = True
            else:
                raise ValueError(reason)

        mp_tds = [td for td in td_list if td.get('data-stat', None) == 'mp']
        if mp_tds:
            mp_td = mp_tds[0]
            mp_text = mp_td.text
            if not mp_text:
                # old games are missing mp data. skip out
                self.game = None
                return
            m, s = map(int, mp_text.split(':'))
            self.minutes = m + s / 60

        dt_str = td_list[1].find('a').text
        dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d').date()
        team_abbrev = td_list[3].find('a').text
        team = Team.parse(team_abbrev)

        home_away_str = td_list[4].text  # @
        assert home_away_str in ('@', '')
        home = home_away_str != '@'

        opp_abbrev = td_list[5].find('a').text
        opp = Team.parse(opp_abbrev)

        home_team = team if home else opp
        away_team = opp if home else team

        game = game_directory.get_game(team, dt)
        if game is None:
            # play-in tournament games are missing from basketball-reference.com
            # this must be that case
            pass
        else:
            assert game.home_team == home_team
            assert game.away_team == away_team

        self.game = game

    def __str__(self):
        return f'GameLog({self.player}, {self.game})'

    def __repr__(self):
        return str(self)


class SeasonGameLog:
    def __init__(self, player: Player, season: int):
        self.player = player
        self.season = season
        self.games: List[GameLog] = []

    def add_game(self, game: GameLog):
        self.games.append(game)

    def __str__(self):
        return f'SeasonGameLog({self.player}, {self.season})'

    def __repr__(self):
        return str(self)


class CareerGameLog:
    def __init__(self, player: Player):
        self.player = player
        self.season_game_logs: Dict[Season, SeasonGameLog] = {}

    def add_game(self, season: Season, game: GameLog):
        season_log = self.season_game_logs.get(season, None)
        if season_log is None:
            season_log = SeasonGameLog(self.player, season)
            self.season_game_logs[season] = season_log

        season_log.add_game(game)

    def empty(self) -> bool:
        return len(self.season_game_logs) == 0

    def __str__(self):
        return f'CareerGameLog({self.player})'

    def __repr__(self):
        return str(self)


def _get_career_game_log_uncached(player: Player) -> Optional[CareerGameLog]:
    career_game_log = CareerGameLog(player)
    html = web.fetch(player.url, stale_window_in_days=CACHE_HOT_DAYS, verbose=True)
    soup = bs4.BeautifulSoup(html, features='html.parser')

    current_season = get_current_season()
    a_list = soup.find_all('a')
    game_log_urls = [BASKETBALL_REFERENCE_URL + a['href'] for a in a_list if a.get('href', '').find('/gamelog/') != -1]
    for game_log_url in sorted(set(game_log_urls)):
        # https://www.basketball-reference.com/players/d/duranke01/gamelog/2023
        gamelog_indices = [i for i, s in enumerate(game_log_url.split('/')) if s == 'gamelog']
        assert len(gamelog_indices) == 1, game_log_url
        gamelog_index = gamelog_indices[0]
        season = int(game_log_url.split('/')[gamelog_index + 1])
        if season < FIRST_FULL_SEASON_POST_NBA_ABA_MERGER:
            # exclude players whose career started before the NBA/ABA merger
            return None
        stale_ok = season < current_season

        game_log_html = web.fetch(game_log_url, stale_is_ok=stale_ok, verbose=True)
        game_log_html = web.uncomment_commented_out_sections(game_log_html, game_log_url, limit=1)
        game_log_soup = bs4.BeautifulSoup(game_log_html, features='html.parser')
        game_log_rows = game_log_soup.find_all('th', scope='row')
        for row in game_log_rows:
            game_log = GameLog(player, row.parent)
            if game_log.game is None:
                # this must be play-in tournament game, omit it.
                continue
            career_game_log.add_game(season, game_log)

    return career_game_log


@memory.cache
def _get_career_game_log_cached(player: Player) -> Optional[CareerGameLog]:
    return _get_career_game_log_uncached(player)


def get_career_game_log(player: Player) -> Optional[CareerGameLog]:
    if player.active:
        if web.check_url(player.url, stale_window_in_days=CACHE_HOT_DAYS):
            return _get_career_game_log_cached(player)
        else:
            return _get_career_game_log_uncached(player)
    else:
        return _get_career_game_log_cached(player)


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

            strong = tr.find('strong')
            active = bool(strong)
            yield Player(name, birthdate, active, player_url)
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


def get_season(dt: datetime.date) -> Season:
    cutoff = datetime.date(dt.year, 9, 1)
    if dt < cutoff:
        return dt.year
    else:
        return dt.year + 1


def get_current_season() -> Season:
    return get_season(datetime.date.today())


def get_season_games(season: Season) -> List[GameData]:
    return list(_get_season_games_iterable(season))


def _get_season_games_iterable(season) -> Iterable[GameData]:
    if season < get_current_season():
        yield from _get_season_games_iterable_cached(season)
    else:
        yield from _get_season_games_iterable_uncached(season)


@memory.cache
def _get_season_games_iterable_cached(season: Season) -> Iterable[GameData]:
    return list(_get_season_games_iterable_uncached(season))


def _get_season_games_iterable_uncached(season: Season) -> Iterable[GameData]:
    url = f'{BASKETBALL_REFERENCE_URL}/leagues/NBA_{season}_standings.html'
    stale_is_ok = season < get_current_season()
    html = web.fetch(url, stale_is_ok=stale_is_ok)
    html = web.uncomment_commented_out_sections(html, url, limit=2)
    soup = bs4.BeautifulSoup(html, features='html.parser')
    divs = [d for d in soup.find_all('div') if d.get('id', None) == 'div_expanded_standings']
    assert len(divs) == 1, url
    div = divs[0]
    a_list = div.find_all('a')

    abbrevs = set()
    for a in a_list:
        # <a href="/teams/PHO/2022.html">Phoenix Suns</a>
        abbrev = a.get('href').split('/')[2]  # PHO
        abbrevs.add(abbrev)

    teams = [Team.parse(abbrev) for abbrev in sorted(abbrevs)]

    game_by_team = defaultdict(set)
    for team in teams:
        for game in _get_season_team_games_iterable(team, season):
            game_by_team[game.home_team].add(game)
            game_by_team[game.away_team].add(game)

    games = set()
    for team, game_set in game_by_team.items():
        game_list = list(sorted(game_set, key=lambda g: g.dt))
        for i, game in enumerate(game_list):
            if i == 0:
                game.set_days_rest(team, 7)  # default for first game of season
            else:
                days_rest = (game.dt - game_list[i - 1].dt).days - 1
                game.set_days_rest(team, days_rest)
            games.add(game)

    yield from sorted(games, key=lambda g: g.dt)


def extract_games_from_tbody(team: Team, tbody: bs4.element.Tag, url: str, game_type: GameType) -> Iterable[GameData]:
    tr_id_prefix: str = 'tgl_basic_playoffs.' if game_type == GameType.PLAYOFFS else 'tgl_basic.'
    game_rows = tbody.find_all('tr')
    for game_row in game_rows:
        tr_id = game_row.get('id')
        if not tr_id:
            continue
        assert tr_id and tr_id.startswith(tr_id_prefix), (url, team, game_row)
        td_list = game_row.find_all('td')
        if not td_list:
            continue

        dt_td = td_list[1]  # <td class="left" data-stat="date_game"><a href="/boxscores/202211280BOS.html">2022-11-28</a></td>
        dt_str = dt_td.find('a').text  # 2022-11-28
        dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d').date()
        # box_score_url = BASKETBALL_REFERENCE_URL + dt_td.find('a')['href']  # /boxscores/202211280BOS.html

        home_away_str = td_list[2].text  # @
        assert home_away_str in ('@', ''), url
        home = home_away_str != '@'

        opp_td = td_list[3]  # <td class="left" data-stat="opp_id"><a href="/teams/BOS/2022.html">BOS</a></td>
        opp_abbrev = opp_td.find('a').text  # BOS
        opp = Team.parse(opp_abbrev)

        home_team = team if home else opp
        away_team = opp if home else team

        my_score = int(td_list[5].text)  # 123
        opp_score = int(td_list[6].text)  # 124

        home_score = my_score if home else opp_score
        away_score = opp_score if home else my_score

        data = GameData(dt, game_type, home_team, away_team, home_score, away_score)
        yield data


def _get_season_team_games_iterable(team: Team, season: Season) -> Iterable[GameData]:
    url = f'{BASKETBALL_REFERENCE_URL}/teams/{team.abbrev}/{season}/gamelog/'
    stale_is_ok = season < get_current_season()
    html = web.fetch(url, stale_is_ok=stale_is_ok)
    html = web.uncomment_commented_out_sections(html, url, limit=1)
    soup = bs4.BeautifulSoup(html, features='html.parser')
    tbodies = soup.find_all('tbody')
    assert 1 <= len(tbodies) <= 2, url  # 1 for regular season, 1 for playoffs

    yield from extract_games_from_tbody(team, tbodies[0], url, GameType.REGULAR_SEASON)
    if len(tbodies) == 2:
        yield from extract_games_from_tbody(team, tbodies[1], url, GameType.PLAYOFFS)


def get_all_players() -> List[Player]:
    return list(_get_all_players_iterable())


class PlayerMatchException(Exception):
    pass


class InvalidPlayerException(PlayerMatchException):
    def __init__(self, name: Union[PlayerName, List[PlayerName]], birthdate: Optional[datetime.date] = None,
                 valid_birthdates: Optional[Set[datetime.date]] = None):
        names = name if isinstance(name, list) else [name]
        msg = f'No player named {" or ".join(names)}'
        if birthdate is not None:
            msg += f' with birthdate {birthdate.strftime("%Y-%m-%d")}'
            if valid_birthdates:
                valid_birthdates_str = ', '.join(d.strftime('%Y-%m-%d') for d in sorted(valid_birthdates))
                msg += f' (valid birthdates: {valid_birthdates_str})'
        super().__init__(msg)
        self.names = names


class AmbiguousPlayerException(PlayerMatchException):
    def __init__(self, name: PlayerName, valid_birthdates: Set[datetime.date]):
        msg = f'Multiple players in NBA history named "{name}", birthdate disambiguation required'
        valid_birthdates_str = ', '.join(d.strftime('%Y-%m-%d') for d in sorted(valid_birthdates))
        msg += f' (valid birthdates: {valid_birthdates_str})'
        super().__init__(msg)


class GameDirectory:
    _instance = None

    @staticmethod
    def instance() -> 'GameDirectory':
        if GameDirectory._instance is None:
            GameDirectory._instance = GameDirectory()
        return GameDirectory._instance

    def __init__(self):
        self.games: Dict[Season, Dict[Team, Dict[datetime.date, GameData]]] = defaultdict(lambda: defaultdict(dict))
        season = FIRST_FULL_SEASON_POST_NBA_ABA_MERGER
        current_season = get_current_season()
        while season <= current_season:
            self.load(season)
            season += 1

    def load(self, season: Season):
        games = get_season_games(season)
        for game in games:
            assert None not in (game.away_team_days_rest , game.home_team_days_rest), game
            self.games[season][game.home_team][game.dt] = game
            self.games[season][game.away_team][game.dt] = game

    def get_games(self, team: Team, season: Season) -> List[GameData]:
        return list(self.games.get(season, {}).get(team, {}).values())

    def get_game(self, team: Team, dt: datetime.date) -> Optional[GameData]:
        season = get_season(dt)
        assert isinstance(dt, datetime.date)
        return self.games.get(season, {}).get(team, {}).get(dt, None)


class PlayerDirectory:
    _instance = None

    @staticmethod
    def instance() -> 'PlayerDirectory':
        if PlayerDirectory._instance is None:
            PlayerDirectory._instance = PlayerDirectory()
        return PlayerDirectory._instance

    def __init__(self):
        self._fragments_lookup: Dict[str, List[Player]] = defaultdict(list)
        self._lookup: Dict[PlayerName, Dict[datetime.date, Player]] = defaultdict(dict)
        self._career_logs: Dict[Player, CareerGameLog] = {}
        for player in get_all_players():
            subdict = self._lookup[player.name]
            if player.birthdate in subdict:
                raise Exception(f'Duplicate player: {player}')
            subdict[player.birthdate] = player
            for fragment in player.name.split():
                self._fragments_lookup[fragment].append(player)

            career_game_log = get_career_game_log(player)
            if career_game_log is None or career_game_log.empty():
                continue
            self._career_logs[player] = career_game_log

    def get_career_log(self, player: Player) -> CareerGameLog:
        return self._career_logs[player]

    def get_candidate_matches(self, name: PlayerName) -> List[Player]:
        """
        Finds best-attempt matches for the given name.
        """
        parenthesized_strs = list(extract_parenthesized_strs(name))
        name_tokens = remove_parenthesized_strs(name).split()

        if len(parenthesized_strs) == 0 and '/' not in name_tokens:
            # This is a vanilla name, so we should try a direct lookup
            normalized_name = normalize_player_name(name)
            subdict = self._lookup.get(normalized_name, None)
            if subdict is not None:
                return list(subdict.values())

        tokens = set(name_tokens + parenthesized_strs)
        counts: Counter[Player] = Counter()
        for token in tokens:
            token = normalize_player_name(token)
            for player in self._fragments_lookup[token]:
                counts[player] += 1

        if not counts:
            return []
        max_count = max(counts.values())
        return [p for p, c in counts.items() if c == max_count]

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
