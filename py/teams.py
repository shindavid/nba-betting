"""
List of all teams.

Note that different sources use different abbreviations for the same team. I am using this as the official source:

https://en.wikipedia.org/wiki/Wikipedia:WikiProject_National_Basketball_Association/National_Basketball_Association_team_abbreviations
"""

from collections import defaultdict
from dataclasses import dataclass


@dataclass(eq=True, frozen=True)
class Team:
    abbrev: str
    full_name: str
    conference: str
    division: str

    alternative_abbrevs = {
        'GOL': 'GSW',
        'BRO': 'BKN',
        'NOR': 'NOP',
        'PHO': 'PHX',
        'SAN': 'SAS',
    }

    @staticmethod
    def parse(s: str) -> 'Team':
        s = Team.alternative_abbrevs.get(s.upper(), s)
        if len(s) == 3:
            return TEAMS_BY_ABBREV[s.upper()]
        return TEAMS_BY_FULL_NAME[s]

    def __repr__(self):
        return f'Team({self.abbrev})'

    def __str__(self):
        return self.abbrev


ATL = Team('ATL', 'Atlanta Hawks', 'Eastern', 'Southeast')
BOS = Team('BOS', 'Boston Celtics', 'Eastern', 'Atlantic')
BKN = Team('BKN', 'Brooklyn Nets', 'Eastern', 'Atlantic')
CHA = Team('CHA', 'Charlotte Hornets', 'Eastern', 'Southeast')
CHI = Team('CHI', 'Chicago Bulls', 'Eastern', 'Central')
CLE = Team('CLE', 'Cleveland Cavaliers', 'Eastern', 'Central')
DAL = Team('DAL', 'Dallas Mavericks', 'Western', 'Southwest')
DEN = Team('DEN', 'Denver Nuggets', 'Western', 'Northwest')
DET = Team('DET', 'Detroit Pistons', 'Eastern', 'Central')
GSW = Team('GSW', 'Golden State Warriors', 'Western', 'Pacific')
HOU = Team('HOU', 'Houston Rockets', 'Western', 'Southwest')
IND = Team('IND', 'Indiana Pacers', 'Eastern', 'Central')
LAC = Team('LAC', 'LA Clippers', 'Western', 'Pacific')
LAL = Team('LAL', 'Los Angeles Lakers', 'Western', 'Pacific')
MEM = Team('MEM', 'Memphis Grizzlies', 'Western', 'Southwest')
MIA = Team('MIA', 'Miami Heat', 'Eastern', 'Southeast')
MIL = Team('MIL', 'Milwaukee Bucks', 'Eastern', 'Central')
MIN = Team('MIN', 'Minnesota Timberwolves', 'Western', 'Northwest')
NOP = Team('NOP', 'New Orleans Pelicans', 'Western', 'Southwest')
NYK = Team('NYK', 'New York Knicks', 'Eastern', 'Atlantic')
OKC = Team('OKC', 'Oklahoma City Thunder', 'Western', 'Northwest')
ORL = Team('ORL', 'Orlando Magic', 'Eastern', 'Southeast')
PHI = Team('PHI', 'Philadelphia 76ers', 'Eastern', 'Atlantic')
PHX = Team('PHX', 'Phoenix Suns', 'Western', 'Pacific')
POR = Team('POR', 'Portland Trail Blazers', 'Western', 'Northwest')
SAC = Team('SAC', 'Sacramento Kings', 'Western', 'Pacific')
SAS = Team('SAS', 'San Antonio Spurs', 'Western', 'Southwest')
TOR = Team('TOR', 'Toronto Raptors', 'Eastern', 'Atlantic')
UTA = Team('UTA', 'Utah Jazz', 'Western', 'Northwest')
WAS = Team('WAS', 'Washington Wizards', 'Eastern', 'Southeast')


TEAMS = [ ATL, BOS, BKN, CHA, CHI, CLE, DAL, DEN, DET, GSW, HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL,
          PHI, PHX, POR, SAC, SAS, TOR, UTA, WAS ]


TEAMS_BY_ABBREV = { team.abbrev: team for team in TEAMS }
TEAMS_BY_FULL_NAME = { team.full_name: team for team in TEAMS }

TEAMS_BY_CONFERENCE = defaultdict(list)
[TEAMS_BY_CONFERENCE[team.conference].append(team) for team in TEAMS]

TEAMS_BY_DIVISION = defaultdict(list)
[TEAMS_BY_DIVISION[team.division].append(team) for team in TEAMS]

WESTERN_CONFERENCE_TEAMS = TEAMS_BY_CONFERENCE['Western']
EASTERN_CONFERENCE_TEAMS = TEAMS_BY_CONFERENCE['Eastern']

NORTHWEST_DIVISION_TEAMS = TEAMS_BY_DIVISION['Northwest']
PACIFIC_DIVISION_TEAMS = TEAMS_BY_DIVISION['Pacific']
SOUTHWEST_DIVISION_TEAMS = TEAMS_BY_DIVISION['Southwest']
ATLANTIC_DIVISION_TEAMS = TEAMS_BY_DIVISION['Atlantic']
CENTRAL_DIVISION_TEAMS = TEAMS_BY_DIVISION['Central']
SOUTHEAST_DIVISION_TEAMS = TEAMS_BY_DIVISION['Southeast']

WESTERN_CONFERENCE_DIVISIONS = ('Northwest', 'Pacific', 'Southwest')
EASTERN_CONFERENCE_DIVISIONS = ('Atlantic', 'Central', 'Southeast')


def dump_teams():
    for team in TEAMS:
        print(f'{team.abbrev}: {team.full_name}')

    print('Western Conference Teams:')
    for team in WESTERN_CONFERENCE_TEAMS:
        print(f'    {team.abbrev}: {team.full_name}')
    print('Eastern Conference Teams:')
    for team in EASTERN_CONFERENCE_TEAMS:
        print(f'    {team.abbrev}: {team.full_name}')

    for division, teams in TEAMS_BY_DIVISION.items():
        print(f'{division} Division Teams:')
        for team in teams:
            print(f'    {team.abbrev}: {team.full_name}')


if __name__ == '__main__':
    dump_teams()
