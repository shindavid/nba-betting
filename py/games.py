"""
Provides utilities to download and parse games data.

This includes past game results (from which standings are computed) and future games (on which predictions are made).
"""
import csv
import datetime
from collections import defaultdict
from dataclasses import dataclass
from functools import total_ordering
from typing import List, Optional

from teams import Team, EASTERN_CONFERENCE_TEAMS, WESTERN_CONFERENCE_TEAMS
import web


FIXURE_URL = 'https://fixturedownload.com/download/nba-2022-UTC.csv'


class Game:
    def __init__(self, row):
        self.date: datetime.date = datetime.datetime.strptime(row['Date'].split()[0], '%d/%m/%Y').date()
        self.home_team: Team = Team.parse(row['Home Team'])
        self.away_team: Team = Team.parse(row['Away Team'])
        self.winner: Optional[Team] = None
        self.loser: Optional[Team] = None

        result_str = row['Result']  # "126 - 117"
        if result_str:
            result_str_tokens = result_str.split()
            assert len(result_str_tokens) == 3 and result_str_tokens[1] == '-', row

            home_score = int(result_str_tokens[0])
            away_score = int(result_str_tokens[2])

            self.winner = self.home_team if home_score > away_score else self.away_team
            self.loser = self.home_team if home_score < away_score else self.away_team


def get_games() -> List[Game]:
    """
    Returns all games.
    """
    csv_text = web.fetch(FIXURE_URL)
    reader = csv.DictReader(csv_text.splitlines())
    games = []
    for row in reader:
        game = Game(row)
        games.append(game)

    return games


@total_ordering
@dataclass
class WinLoss:
    wins: int = 0
    losses: int = 0

    @property
    def win_pct(self) -> float:
        return self.wins / (self.wins + self.losses)

    def __lt__(self, other):
        return (self.win_pct, self.wins) < (other.win_pct, other.wins)

    def __eq__(self, other):
        return (self.win_pct, self.wins) == (other.win_pct, other.wins)


class Standings:
    def __init__(self, games: List[Game]):
        self.win_loss = defaultdict(WinLoss)
        for game in games:
            if game.winner is not None:
                self.win_loss[game.winner].wins += 1
                self.win_loss[game.loser].losses += 1

    def dump(self):
        east_win_loss = {team: self.win_loss[team] for team in EASTERN_CONFERENCE_TEAMS}
        west_win_loss = {team: self.win_loss[team] for team in WESTERN_CONFERENCE_TEAMS}

        for descr, subdict in [('EASTERN CONFERENCE', east_win_loss), ('WESTERN CONFERENCE', west_win_loss)]:
            print('')
            print(descr)
            for team, win_loss in sorted(subdict.items(), key=lambda x: x[1], reverse=True):
                print(f"{team} {win_loss.wins}W {win_loss.losses}L {win_loss.win_pct:.3f}")


if __name__ == '__main__':
    games = get_games()
    standings = Standings(games)
    standings.dump()
