"""
Provides utilities to download and parse roster data.

"""
from typing import Optional, Dict, List

import bs4

import web
from teams import Team, TEAMS

STUFFER_URL = 'https://www.nbastuffer.com/2022-2023-nba-player-stats/'


class Roster:
    def __init__(self, team: Team):
        self.team = team
        self.players: List[str] = []

    def add(self, player: str):
        self.players.append(player)
        self.sort()

    def sort(self):
        self.players.sort(key=lambda name: (tuple(name.split()[1:]), name.split()[0]))

    def __str__(self):
        return f'{self.team}: {", ".join(self.players)}'


def extract_stuffer_column(x) -> Optional[str]:
    """
    Extracts the column name from a header component.
    """
    if isinstance(x, bs4.element.NavigableString):
        return str(x).strip()
    if x.contents:
        return extract_stuffer_column(x.contents[0])
    return None


def get_rosters() -> Dict[Team, Roster]:
    """
    This is a bit nasty as I'm parsing raw HTML.

    Unfortunately, I could not find a website that provides a simple CSV or JSON file with the rosters.

    Example line:

       <td class="column-1"></td><td class="column-2">Precious Achiuwa</td><td class="column-3">Tor</td><td class="column-4">F</td><td class="column-5">23.39</td><td class="column-6">32</ td><td class="column-7">22.8</td><td class="column-8">47.5</td><td class="column-9">19.6</td><td class="column-10">11</td><td class="column-11">89</td><td class="column-12">0.697</   td><td class="column-13">192</td><td class="column-14">0.568</td><td class="column-15">67</td><td class="column-16">0.239</td><td class="column-17">0.514</td><td class="column-18">0. 55</td><td class="column-19">10.3</td><td class="column-20">6.5</td><td class="column-21">16</td><td class="column-22">1</td><td class="column-23">6.2</td><td class="column-24">0.    75</td><td class="column-25">0.72</td><td class="column-26">1.16</td><td class="column-27">7.1</td><td class="column-28">112.6</td><td class="column-29">106.7</td>
    """
    html = web.fetch(STUFFER_URL)

    current_team = {}
    header_columns = []
    name_index = None
    team_index = None
    found_header = False
    for line in html.splitlines():
        line = line.strip()
        if line.startswith('<th ') and line.find('"column-1"') != -1:
            # header line
            assert not found_header
            found_header = True
            # <th class="column-1">RANK</th><th class="column-2">FULL NAME</th><th class="column-3">TEAM</th>...

            # here, we parse the xml and map columns to names
            header = bs4.BeautifulSoup(line, features='html.parser')
            header_columns = [extract_stuffer_column(c) for c in header]
            header_column_indices = {c: i for i, c in enumerate(header_columns)}
            name_index = header_column_indices['FULL NAME']
            team_index = header_column_indices['TEAM']
            continue
        if line.startswith('<td ') and line.find('"column-1"') != -1:
            data = bs4.BeautifulSoup(line, features='html.parser')
            columns = [extract_stuffer_column(c) for c in data]
            assert len(columns) == len(header_columns)
            name = columns[name_index]
            team = columns[team_index]
            current_team[name] = Team.parse(team)

    rosters = {}
    for team in TEAMS:
        rosters[team] = Roster(team)

    for player, team in current_team.items():
        rosters[team].add(player)

    return rosters


if __name__ == '__main__':
    for _roster in get_rosters().values():
        print(_roster)
