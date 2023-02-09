"""
Provides utilities to download and parse games data.

This includes past game results (from which standings are computed) and future games (on which predictions are made).
"""
import csv
import datetime
from functools import total_ordering
from typing import List, Optional, Dict

from teams import Team, EASTERN_CONFERENCE_TEAMS, WESTERN_CONFERENCE_TEAMS, TEAMS_BY_CONFERENCE, TEAMS
import web


FIXTURE_URL = 'https://fixturedownload.com/download/nba-2022-UTC.csv'


class Game:
    def __init__(self, row):
        self.date: datetime.date = datetime.datetime.strptime(row['Date'].split()[0], '%d/%m/%Y').date()
        self.home_team: Team = Team.parse(row['Home Team'])
        self.away_team: Team = Team.parse(row['Away Team'])
        self.winner: Optional[Team] = None
        self.loser: Optional[Team] = None
        self.points: Dict[Team, int] = {}

        result_str = row['Result']  # "126 - 117"
        if result_str:
            result_str_tokens = result_str.split()
            assert len(result_str_tokens) == 3 and result_str_tokens[1] == '-', row

            home_score = int(result_str_tokens[0])
            away_score = int(result_str_tokens[2])

            self.points[self.home_team] = home_score
            self.points[self.away_team] = away_score

            self.winner = self.home_team if home_score > away_score else self.away_team
            self.loser = self.home_team if home_score < away_score else self.away_team

    def __str__(self):
        s = f"{self.date.strftime('%Y-%m-%d')} {self.away_team}@{self.home_team}"
        if self.completed:
            s += f" {self.points[self.away_team]}-{self.points[self.home_team]}"
        return s

    def teams_are_in_same_conference(self) -> bool:
        """
        Returns whether the teams in this game are in the same conference.
        """
        return self.home_team.conference == self.away_team.conference

    def teams_are_in_same_division(self) -> bool:
        """
        Returns whether the teams in this game are in the same division.
        """
        return self.home_team.division == self.away_team.division

    def was_won_by(self, team: Team) -> bool:
        """
        Returns whether the given team won this game.
        """
        assert self.completed and team in self.points, self
        return self.winner == team

    def get_point_differential(self, team: Team) -> int:
        """
        Returns the point differential for the given team.
        """
        assert self.completed and team in self.points, self
        diff = self.points[self.winner] - self.points[self.loser]
        return diff if team == self.winner else -diff

    @property
    def completed(self) -> bool:
        return self.winner is not None


def get_games() -> List[Game]:
    """
    Returns all games.
    """
    csv_text = web.fetch(FIXTURE_URL)
    reader = csv.DictReader(csv_text.splitlines())
    games = []
    for row in reader:
        game = Game(row)
        games.append(game)

    return games


@total_ordering
class WinLossRecord:
    def __init__(self):
        self.wins: int = 0
        self.losses: int = 0

    def update(self, won: bool):
        if won:
            self.wins += 1
        else:
            self.losses += 1

    @property
    def win_pct(self) -> float:
        return self.wins / (self.wins + self.losses)

    def __str__(self):
        return '%2d-%-2d [%.3f]' % (self.wins, self.losses, self.win_pct)

    def __lt__(self, other):
        return self.win_pct < other.win_pct

    def __eq__(self, other):
        return self.win_pct == other.win_pct


@total_ordering
class Record:
    def __init__(self, team: Team):
        self.team: Team = team
        self.overall_win_loss = WinLossRecord()
        self.division_win_loss = WinLossRecord()
        self.conference_win_loss = WinLossRecord()
        self.point_differential: int = 0

    def __str__(self):
        return f"{self.team} {self.overall_win_loss} " \
               f"D:{self.division_win_loss} " \
               f"C:{self.conference_win_loss} " \
               f"P:{self.avg_point_differential:+5.1f}"

    @property
    def avg_point_differential(self) -> float:
        return self.point_differential / self.num_games

    @property
    def num_games(self) -> int:
        return self.overall_win_loss.wins + self.overall_win_loss.losses

    def update(self, game: Game):
        self.point_differential += game.get_point_differential(self.team)
        won = game.was_won_by(self.team)
        self.overall_win_loss.update(won)
        if game.teams_are_in_same_conference():
            self.conference_win_loss.update(won)
        if game.teams_are_in_same_division():
            self.division_win_loss.update(won)

    def to_tuple(self):
        """
        Tiebreaker criteria:

        1. Head-to-head record; better record in games with the tied teams.
        2. Division record; better record in games against teams in its own division (Only if the teams are in the
           same division).
        3. Conference record; better record in game against teams in its own conference.
        4. Winning percentage against playoff teams in its own conference.
        5. Winning percentage against playoff teams in the opposing conference.
        6. Point differential in all games.

        Source: https://en.wikipedia.org/wiki/NBA_playoffs

        Criteria 4 and 5 are confusing to me, the definition feels circular. So I'm just leaving it at 1-3.
        """
        return (
            self.overall_win_loss,
            self.division_win_loss,
            self.conference_win_loss
        )

    def __lt__(self, other):
        return self.to_tuple() < other.to_tuple()

    def __eq__(self, other):
        return self.to_tuple() == other.to_tuple()


class Standings:
    def __init__(self, games: List[Game]):
        self.records = {team: Record(team) for team in TEAMS}
        for game in games:
            if game.completed:
                self.records[game.home_team].update(game)
                self.records[game.away_team].update(game)

    def dump(self):
        east_win_loss = {team: self.records[team] for team in EASTERN_CONFERENCE_TEAMS}
        west_win_loss = {team: self.records[team] for team in WESTERN_CONFERENCE_TEAMS}

        for descr, subdict in [('EASTERN CONFERENCE', east_win_loss), ('WESTERN CONFERENCE', west_win_loss)]:
            print('')
            print(descr)
            for record in sorted(subdict.values(), reverse=True):
                print(record)

    def playoff_rankings(self, conference: str) -> List[Team]:
        return list(sorted(TEAMS_BY_CONFERENCE[conference], reverse=True))[:10]


if __name__ == '__main__':
    Standings(get_games()).dump()