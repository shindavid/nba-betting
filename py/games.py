"""
Provides utilities to download and parse games data.

This includes past game results (from which standings are computed) and future games (on which predictions are made).
"""
import csv
import datetime
import itertools
from collections import defaultdict
from functools import total_ordering
from typing import List, Optional, Dict

from teams import Team, EASTERN_CONFERENCE_TEAMS, WESTERN_CONFERENCE_TEAMS, TEAMS
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

    def other_team(self, team: Team) -> Team:
        if self.home_team == team:
            return self.away_team
        if self.away_team == team:
            return self.home_team
        raise Exception(f"Team {team} is not in game {self}")

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

    def __add__(self, other):
        record = WinLossRecord()
        record.wins = self.wins + other.wins
        record.losses = self.losses + other.losses
        return record

    def __iadd__(self, other):
        self.wins += other.wins
        self.losses += other.losses
        return self

    def __str__(self):
        return '%2d-%-2d [%.3f]' % (self.wins, self.losses, self.win_pct)

    def __lt__(self, other):
        return self.win_pct < other.win_pct

    def __eq__(self, other):
        return self.win_pct == other.win_pct

    def __hash__(self):
        return hash(self.win_pct)


class Record:
    def __init__(self, team: Team):
        self.team: Team = team
        self.overall_win_loss = WinLossRecord()
        self.win_loss_by_team = defaultdict(WinLossRecord)
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
        won = game.was_won_by(self.team)

        self.overall_win_loss.update(won)
        self.win_loss_by_team[game.other_team(self.team)].update(won)
        if game.teams_are_in_same_conference():
            self.conference_win_loss.update(won)
        if game.teams_are_in_same_division():
            self.division_win_loss.update(won)
        self.point_differential += game.get_point_differential(self.team)

    def head_to_head_record(self, teams: List[Team]) -> WinLossRecord:
        """
        Returns the head-to-head record against the given teams.
        """
        record = WinLossRecord()
        for team in teams:
            record += self.win_loss_by_team.get(team, WinLossRecord())
        return record


class PlayoffSeeding:
    """
    The top-10 teams in each conference, sorted by playoff seeding using the official NBA tiebreaker rules.
    """
    def __init__(self, east_seeding: List[Team], west_seeding: List[Team]):
        self.east_seeding = east_seeding
        self.west_seeding = west_seeding

    def dump(self):
        print('')
        print('PLAYOFF SEEDING')
        for descr, teams in [('EASTERN', self.east_seeding), ('WESTERN', self.west_seeding)]:
            print('')
            print(f'{descr} CONFERENCE')
            for i, team in enumerate(teams):
                print(f'{i+1:2d}. {team}')


TieBreakerSet = List[Team]


class Standings:
    def __init__(self, games: List[Game]):
        self.records = {team: Record(team) for team in TEAMS}
        for game in games:
            if game.completed:
                self.records[game.home_team].update(game)
                self.records[game.away_team].update(game)

    def dump(self):
        east_records = {team: self.records[team] for team in EASTERN_CONFERENCE_TEAMS}
        west_records = {team: self.records[team] for team in WESTERN_CONFERENCE_TEAMS}

        for descr, subdict in [('EASTERN', east_records), ('WESTERN', west_records)]:
            print('')
            print(f'{descr} CONFERENCE')
            for record in sorted(subdict.values(), key=lambda r: r.overall_win_loss, reverse=True):
                print(record)

    def _tiebreaker_tuple(self, team: Team, tied_group: TieBreakerSet, own_conference_playoff_teams: List[Team],
                          opposing_conference_playoff_teams: List[Team]):
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
        """
        record = self.records[team]
        components = [
            record.overall_win_loss,  # allows for reuse of this method for finals-home-court calculation
            record.head_to_head_record(tied_group),
        ]
        same_division = all(team.division == tied_team.division for tied_team in tied_group)
        if same_division:
            components.append(record.division_win_loss)

        components.extend([
            record.conference_win_loss,
            record.head_to_head_record(own_conference_playoff_teams),
            record.head_to_head_record(opposing_conference_playoff_teams),
            record.point_differential
        ])
        return tuple(components)

    def _break_tie(self, tied_group: TieBreakerSet, own_conference_playoff_teams: List[Team],
                   opposing_conference_playoff_teams: List[Team]) -> List[Team]:
        """
        Accepts a list of teams that are tied by overall record. Applies the playoff tiebreaker rules on these teams
        to determine the playoff seeding. Returns the seeding.
        """
        tuple_teams = [(self._tiebreaker_tuple(team, tied_group, own_conference_playoff_teams,
                                               opposing_conference_playoff_teams), team) for team in tied_group]
        return [team for _, team in sorted(tuple_teams, reverse=True)]

    def _break_ties(self, east_groups: List[TieBreakerSet], west_groups: List[TieBreakerSet]) -> PlayoffSeeding:
        """
        Applies the playoff tiebreaker rules on east_groups and west_groups and outputs the resultant seeding.
        """
        east_teams = list(itertools.chain(*east_groups))
        west_teams = list(itertools.chain(*west_groups))

        east_seeding = []
        west_seeding = []

        for east_group in east_groups:
            east_seeding.extend(self._break_tie(east_group, east_teams, west_teams))

        for west_group in west_groups:
            west_seeding.extend(self._break_tie(west_group, west_teams, east_teams))

        return PlayoffSeeding(east_seeding[:10], west_seeding[:10])

    def _get_tiebreaker_sets(self, teams: List[Team]) -> List[TieBreakerSet]:
        """
        Returns a list of lists of teams. Each list represents a group of teams that are tied by overall record. The
        lists are sorted from the best overall record to the worst overall record.

        Only includes teams whose overall record are in the top-10. This can consist of more than 10 teams if the 10th
        and 11th place teams have the same overall record.
        """
        teams_by_overall_win_loss = defaultdict(list)
        for team in teams:
            teams_by_overall_win_loss[self.records[team].overall_win_loss].append(team)

        n_teams = 0
        tiebreaker_sets: List[List[Team]] = []
        for _, group in sorted(teams_by_overall_win_loss.items(), reverse=True):
            tiebreaker_sets.append(group)
            n_teams += len(group)
            if n_teams >= 10:
                break
        return tiebreaker_sets

    def playoff_seeding(self) -> PlayoffSeeding:
        east_groups = self._get_tiebreaker_sets(EASTERN_CONFERENCE_TEAMS)
        west_groups = self._get_tiebreaker_sets(WESTERN_CONFERENCE_TEAMS)

        return self._break_ties(east_groups, west_groups)

    def determine_finals_home_court_advantage(self, team1: Team, team2: Team) -> Team:
        """
        The rules here are not clear. I'm doing what I think makes most sense.
        """
        tuple1 = self._tiebreaker_tuple(team1, [team1, team2], [], [])
        tuple2 = self._tiebreaker_tuple(team2, [team1, team2], [], [])
        return team2 if tuple1 < tuple2 else team1


if __name__ == '__main__':
    _standings = Standings(get_games())
    _standings.dump()
    _standings.playoff_seeding().dump()
