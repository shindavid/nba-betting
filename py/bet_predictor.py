"""
Chris Andersen and David Shin made a bet prior to the 2022-2023 NBA season. Each NBA team was claimed by exactly one
of the two bettors. At the end of the 2022-2023 playoffs, each team scores 1 point per playoff game won. The bettor
with the most points wins the bet. The play-in game does not count.

This script predicts the outcome of the bet.

At a high-level, the prediction is currently made in the following manner:

* 538's RAPTOR model is used to estimate each individual player's contribution to their team per-100 possessions, as
  well as to their team's average possessions per game.

* Season minutes data is used to model each player's expected minutes per game.

* The above is used to model each team's expected points for/against per game.

* Pythagorean expectation is used to model each team's expected win percentage based on the expected points for/against
  per game.

* Expected win percentage is plugged into the Log5 formula to model any given game outcome. The model may adjust the
  raw win percentage based on home court advantage, rest, etc.

* A Monte Carlo simulation is performed to model the remainder of the regular season and playoffs. The simulation
  results are used to predict the final outcome of the bet.
"""
from enum import Enum
from typing import Dict

from games import get_games, Standings
from raptor import get_raptor_stats, PlayerName, RaptorStats
from rosters import get_rosters, Roster
from teams import *


DAVID_TEAMS = [ MIL, PHX, DAL, MIA, PHI, CLE, CHI, LAC, POR, NYK, CHA, IND, SAC, OKC, HOU ]
CHRIS_TEAMS = [ GSW, MEM, BOS, BKN, DEN, UTA, MIN, NOP, ATL, TOR, LAL, SAS, WAS, ORL, DET ]


class MinutesProjectionMethod(Enum):
    """
    Describes the method used to project minutes for each player.
    """
    RAPTOR_RANK = 1
    SEASON_MINUTES = 2


class TeamModel:
    avg_min_per_game = 48.3  # 0.3 fudge factor to account for OT
    players_on_court = 5

    def __init__(self, roster: Roster, standings: Standings, raptor_stats: Dict[PlayerName, RaptorStats],
                 minutes_projection_method: MinutesProjectionMethod):
        self.roster = roster
        self.record = standings.records[roster.team]
        self.raptor_stats = { p: raptor_stats[p] for p in roster.players }

        if minutes_projection_method == MinutesProjectionMethod.RAPTOR_RANK:
            self.projected_minutes = self._project_minutes_via_raptor_rank()
        elif minutes_projection_method == MinutesProjectionMethod.SEASON_MINUTES:
            self.projected_minutes = self._project_minutes_via_season_minutes()
        else:
            raise ValueError('Invalid minutes projection method: %s' % minutes_projection_method)

        self.possessions_per_game = self._get_possessions_per_game()

    @property
    def team(self) -> Team:
        return self.roster.team

    def dump_minutes(self):
        """
        Prints the projected minutes per game for each player on the team.
        """
        for p, m in sorted(self.projected_minutes.items(), key=lambda x: x[1], reverse=True):
            print('%5.1fmin %s' % (m, p))

    def _project_minutes_via_raptor_rank(self, alpha=2) -> Dict[PlayerName, float]:
        """
        Returns a dictionary mapping each player to their projected minutes per game.

        This method ranks the players by their raptor_total, and greedily allocate minutes to the players from best to
        worst until all 48.3*5 = 240 minutes are used up. The maximum amount of minutes any player can be allocated is
        their adjusted season mpg, defined as total_minutes / (games_played + alpha). The alpha factor helps to mute
        the mpg of players who have played in a small number of games.
        """
        ordered_players = list(sorted(self.raptor_stats.keys(), key=lambda p: self.raptor_stats[p].raptor_total,
                                      reverse=True))

        minutes_total = TeamModel.avg_min_per_game * TeamModel.players_on_court
        minutes = {}
        remaining_minutes = minutes_total
        for player in ordered_players:
            mpg = min(self.roster.stats[player].adjusted_mpg(alpha), remaining_minutes)
            remaining_minutes -= mpg
            minutes[player] = mpg

        if remaining_minutes:
            raise ValueError('Remaining minutes: %f' % remaining_minutes)
        return minutes

    def _project_minutes_via_season_minutes(self) -> Dict[PlayerName, float]:
        """
        Returns a dictionary mapping each player to their projected minutes per game.

        This method simply allocates minutes to each player proportionally to their season minutes.
        """
        minutes = { p: self.raptor_stats[p].minutes for p in self.roster.players }
        scaling_factor = TeamModel.avg_min_per_game * TeamModel.players_on_court / sum(minutes.values())
        return { p: m * scaling_factor for p, m in minutes.items() }

    def _get_possessions_per_game(self) -> float:
        """
        Returns the average number of possessions per game for the team.

        This is modeled based on the RAPTOR pace_impact values scaled by the projected minutes for each player.
        """
        pace_adjustment = 0.0
        for p in self.roster.players:
            pace_adjustment += self.raptor_stats[p].pace_impact * self.projected_minutes[p] / TeamModel.avg_min_per_game

        baseline = 100.0
        return baseline + pace_adjustment


class BetPredictor:
    def __init__(self, minutes_projection_method: MinutesProjectionMethod):
        self.games = get_games()
        self.standings = Standings(self.games)
        self.rosters = get_rosters()
        self.raptor_stats = get_raptor_stats()
        self.team_models = {roster.team: TeamModel(roster, self.standings, self.raptor_stats, minutes_projection_method)
                            for roster in self.rosters.values()}


def main():
    predictor = BetPredictor(MinutesProjectionMethod.SEASON_MINUTES)

    pace_list = [(model.possessions_per_game, team) for team, model in predictor.team_models.items()]
    for p, t in sorted(pace_list, reverse=True):
        print('%5.1f %s' % (p, t))

    # for team in TEAMS:
    #     print('')
    #     print(team)
    #     predictor.team_models[team].dump_minutes()


if __name__ == '__main__':
    main()
