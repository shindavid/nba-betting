"""
List of all teams.

Note that different sources use different abbreviations for the same team. I am using this as the official source:

https://en.wikipedia.org/wiki/Wikipedia:WikiProject_National_Basketball_Association/National_Basketball_Association_team_abbreviations
"""

from collections import defaultdict
from dataclasses import dataclass


class TeamNameParseError(Exception):
    def __init__(self, team_str: str):
        super().__init__(f'Could not parse team: {team_str}')


@dataclass(eq=True, frozen=True)
class Team:
    abbrev: str
    full_name: str
    conference: str
    division: str
    defunct: bool = False

    alternative_abbrevs = {
        'BKN': 'BRK',
        'BRO': 'BRK',
        'GOL': 'GSW',
        'NOR': 'NOP',
        'PHX': 'PHO',
        'SAN': 'SAS',
    }

    @property
    def nickname(self) -> str:
        """
        Returns "Blazers" for "Portland Trail Blazers".
        """
        return self.full_name.split()[-1]

    @staticmethod
    def parse(s: str) -> 'Team':
        orig_s = s
        s = Team.alternative_abbrevs.get(s.upper(), s)

        team = TEAMS_BY_ABBREV.get(s.upper(), None)
        if team is not None:
            return team

        team = TEAMS_BY_NICKNAME.get(s, None)
        if team is not None:
            return team

        team = TEAMS_BY_FULL_NAME.get(s, None)
        if team is None:
            raise TeamNameParseError(orig_s)
        return team

    def __repr__(self):
        if self.defunct:
            return f'DefunctTeam({self.abbrev})'
        return f'Team({self.abbrev})'

    def __str__(self):
        return self.abbrev


ATL = Team('ATL', 'Atlanta Hawks', 'Eastern', 'Southeast')
BOS = Team('BOS', 'Boston Celtics', 'Eastern', 'Atlantic')
BRK = Team('BRK', 'Brooklyn Nets', 'Eastern', 'Atlantic')
CHI = Team('CHI', 'Chicago Bulls', 'Eastern', 'Central')
CHH = Team('CHH', 'Charlotte Hornets', 'Eastern', 'Southeast')
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
PHO = Team('PHO', 'Phoenix Suns', 'Western', 'Pacific')
POR = Team('POR', 'Portland Trail Blazers', 'Western', 'Northwest')
SAC = Team('SAC', 'Sacramento Kings', 'Western', 'Pacific')
SAS = Team('SAS', 'San Antonio Spurs', 'Western', 'Southwest')
TOR = Team('TOR', 'Toronto Raptors', 'Eastern', 'Atlantic')
UTA = Team('UTA', 'Utah Jazz', 'Western', 'Northwest')
WAS = Team('WAS', 'Washington Wizards', 'Eastern', 'Southeast')


BAL = Team('BAL', 'Baltimore Bullets', 'Defunct', 'Defunct', defunct=True)
BUF = Team('BUF', 'Buffalo Braves', 'Defunct', 'Defunct', defunct=True)
CAP = Team('CAP', 'Capital Bullets', 'Defunct', 'Defunct', defunct=True)
CHA = Team('CHA', 'Charlotte Bobcats', 'Defunct', 'Defunct', defunct=True)
# CHH = Team('CHH', 'Charlotte Hornets', 'Defunct', 'Defunct', defunct=True)
CIN = Team('CIN', 'Cincinnati Royals', 'Defunct', 'Defunct', defunct=True)
KCK = Team('KCK', 'Kansas City Kings', 'Defunct', 'Defunct', defunct=True)
NJN = Team('NJN', 'New Jersey Nets', 'Defunct', 'Defunct', defunct=True)
NOH = Team('NOH', 'New Orleans Hornets', 'Defunct', 'Defunct', defunct=True)
NOJ = Team('NOJ', 'New Orleans Jazz', 'Defunct', 'Defunct', defunct=True)
NOK = Team('NOK', 'New Orleans/Oklahoma City Hornets', 'Defunct', 'Defunct', defunct=True)
NYN = Team('NYN', 'New York Nets', 'Defunct', 'Defunct', defunct=True)
SDC = Team('SDC', 'San Diego Clippers', 'Defunct', 'Defunct', defunct=True)
SDR = Team('SDR', 'San Diego Rockets', 'Defunct', 'Defunct', defunct=True)
SEA = Team('SEA', 'Seattle SuperSonics', 'Defunct', 'Defunct', defunct=True)
SFW = Team('SFW', 'San Francisco Warriors', 'Defunct', 'Defunct', defunct=True)
VAN = Team('VAN', 'Vancouver Grizzlies', 'Defunct', 'Defunct', defunct=True)
WSB = Team('WSB', 'Washington Bullets', 'Defunct', 'Defunct', defunct=True)


TEAMS = [ATL, BOS, BRK, CHH, CHI, CLE, DAL, DEN, DET, GSW, HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL,
         PHI, PHO, POR, SAC, SAS, TOR, UTA, WAS]


DEFUNCT_TEAMS = [BAL, BUF, CAP, CHA, CHH, CIN, KCK, NJN, NOH, NOJ, NOK, NYN, SDC, SDR, SEA, SFW, VAN, WSB]


TEAMS_BY_ABBREV = {team.abbrev: team for team in TEAMS + DEFUNCT_TEAMS}
TEAMS_BY_FULL_NAME = {team.full_name: team for team in TEAMS + DEFUNCT_TEAMS}
TEAMS_BY_NICKNAME = {team.nickname: team for team in TEAMS + DEFUNCT_TEAMS}

TEAMS_BY_CONFERENCE = defaultdict(list)
[TEAMS_BY_CONFERENCE[team.conference].append(team) for team in TEAMS + DEFUNCT_TEAMS]

TEAMS_BY_DIVISION = defaultdict(list)
[TEAMS_BY_DIVISION[team.division].append(team) for team in TEAMS + DEFUNCT_TEAMS]

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
