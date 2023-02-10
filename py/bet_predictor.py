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

* Pythagorean expectation is used to model a baseline win % for any given game. The baseline is adjusted in the
  logit space to account for home court advantage, rest, etc.

* A Monte Carlo simulation is performed to model the remainder of the regular season and playoffs. The simulation
  results are used to predict the final outcome of the bet.
"""
import math
from enum import Enum
from typing import Dict

from games import get_games, Standings, Game
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


class GameType(Enum):
    """
    Describes the type of game.
    """
    REGULAR_SEASON = 1
    PLAYOFFS = 2


class Constants:
    avg_points_per_100_possessions = 114.3  # https://www.basketball-reference.com/leagues/NBA_stats_per_poss.html
    avg_possessions_per_game = 100.0

    avg_min_per_game = 48.3  # 0.3 fudge factor to account for OT
    players_on_court = 5

    back_to_back_win_pct = 0.436  # https://www.fastbreakbets.com/betting-tips/betting-nba-teams-back-back/
    rested_win_pct = 0.518  # https://www.fastbreakbets.com/betting-tips/betting-nba-teams-back-back/

    home_court_win_pct = 0.606  # https://bleacherreport.com/articles/1520496-how-important-is-home-court-advantage-in-the-nba

    pythagorean_exponent = {  # https://fivethirtyeight.com/features/how-our-raptor-metric-works/
        GameType.REGULAR_SEASON: 14.3,
        GameType.PLAYOFFS: 13.2,
    }


def prob_to_log_odds(p: float) -> float:
    """
    Converts a probability to log odds.
    """
    return math.log(p / (1 - p))


def log_odds_to_prob(log_odds: float) -> float:
    """
    Converts log odds to a probability.
    """
    return 1 / (1 + math.exp(-log_odds))


class TeamModel:
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

        self.offensive_efficiency_adjustment = self._get_offensive_efficiency_adjustment()
        self.defensive_efficiency_adjustment = self._get_defensive_efficiency_adjustment()
        self.possessions_per_game_adjustment = self._get_possessions_per_game_adjustment()

        self.offensive_efficiency = Constants.avg_points_per_100_possessions + self.offensive_efficiency_adjustment
        self.defensive_efficiency = Constants.avg_points_per_100_possessions - self.defensive_efficiency_adjustment
        self.possessions_per_game = Constants.avg_possessions_per_game + self.possessions_per_game_adjustment

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

        minutes_total = Constants.avg_min_per_game * Constants.players_on_court
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
        scaling_factor = Constants.avg_min_per_game * Constants.players_on_court / sum(minutes.values())
        return { p: m * scaling_factor for p, m in minutes.items() }

    def _get_possessions_per_game_adjustment(self) -> float:
        """
        Returns the average number of possessions per game for the team relative to league average.

        This is modeled based on the RAPTOR pace_impact values scaled by the projected minutes for each player.
        """
        pace_adjustment = 0.0
        for p in self.roster.players:
            pace_adjustment += self.raptor_stats[p].pace_impact * self.projected_minutes[p] / Constants.avg_min_per_game

        return pace_adjustment

    def _get_offensive_efficiency_adjustment(self) -> float:
        """
        Returns the average points per 100 possessions for the team relative to league average.

        This is modeled based on the RAPTOR values scaled by the projected minutes for each player.
        """
        point_adjustment = 0.0
        for p in self.roster.players:
            point_adjustment += self.raptor_stats[p].raptor_offense * self.projected_minutes[p] / Constants.avg_min_per_game

        return point_adjustment

    def _get_defensive_efficiency_adjustment(self) -> float:
        """
        Returns the average points per 100 possessions allowed for the team relative to league average.

        This is modeled based on the RAPTOR values scaled by the projected minutes for each player.
        """
        point_adjustment = 0.0
        for p in self.roster.players:
            point_adjustment += self.raptor_stats[p].raptor_defense * self.projected_minutes[p] / Constants.avg_min_per_game

        return point_adjustment


class BetPredictor:
    def __init__(self, minutes_projection_method: MinutesProjectionMethod):
        self.games = get_games()
        self.standings = Standings(self.games)
        self.rosters = get_rosters()
        self.raptor_stats = get_raptor_stats()
        self.team_models = {roster.team: TeamModel(roster, self.standings, self.raptor_stats, minutes_projection_method)
                            for roster in self.rosters.values()}

        for game in self.games:
            if game.completed:
                continue
            home_team_win_pct = self.predict_home_team_win_pct(game, GameType.REGULAR_SEASON)

    def predict_home_team_win_pct(self, game: Game, game_type: GameType, debug: bool = False) -> float:
        home_team = game.home_team
        away_team = game.away_team

        home_team_model = self.team_models[home_team]
        away_team_model = self.team_models[away_team]

        expected_possessions = (Constants.avg_possessions_per_game
                                + home_team_model.possessions_per_game_adjustment
                                + away_team_model.possessions_per_game_adjustment)

        home_team_offensive_efficiency = (Constants.avg_points_per_100_possessions
                                          + home_team_model.offensive_efficiency_adjustment
                                          - away_team_model.defensive_efficiency_adjustment)

        away_team_offensive_efficiency = (Constants.avg_points_per_100_possessions
                                          + away_team_model.offensive_efficiency_adjustment
                                          - home_team_model.defensive_efficiency_adjustment)

        home_team_points = expected_possessions * home_team_offensive_efficiency / 100
        away_team_points = expected_possessions * away_team_offensive_efficiency / 100

        exp = Constants.pythagorean_exponent[game_type]
        home = home_team_points ** exp
        away = away_team_points ** exp

        raw_home_team_win_pct = home / (home + away)
        raw_home_team_win_log_odds = prob_to_log_odds(raw_home_team_win_pct)

        home_court_advantage_log_odds = prob_to_log_odds(Constants.home_court_win_pct)

        rested_log_odds = prob_to_log_odds(Constants.rested_win_pct)
        back_to_back_log_odds = prob_to_log_odds(Constants.back_to_back_win_pct)

        schedule_log_odds = 0
        schedule_log_odds += rested_log_odds if game.days_rest_for_home_team > 1 else back_to_back_log_odds
        schedule_log_odds -= rested_log_odds if game.days_rest_for_away_team > 1 else back_to_back_log_odds

        home_team_win_log_odds = raw_home_team_win_log_odds + home_court_advantage_log_odds + schedule_log_odds
        home_team_win_pct = log_odds_to_prob(home_team_win_log_odds)

        if debug:
            print('')
            print('Predicting: %s' % game)
            print('Home team: %s (days rest: %s)' % (home_team, game.days_rest_for_home_team))
            print('  Possession adjustment:            %+5.1f' % home_team_model.possessions_per_game_adjustment)
            print('  Offensive efficiency adjustment:  %+5.1f' % home_team_model.offensive_efficiency_adjustment)
            print('  Defensive efficiency adjustment:  %+5.1f' % home_team_model.defensive_efficiency_adjustment)
            print('Away team: %s (days rest: %s)' % (away_team, game.days_rest_for_away_team))
            print('  Possession adjustment:            %+5.1f' % away_team_model.possessions_per_game_adjustment)
            print('  Offensive efficiency adjustment:  %+5.1f' % away_team_model.offensive_efficiency_adjustment)
            print('  Defensive efficiency adjustment:  %+5.1f' % away_team_model.defensive_efficiency_adjustment)
            print('Raw expected score: %s %5.1f - %5.1f %s' % (home_team, home_team_points, away_team_points, away_team))
            print('Raw home team win pct:             %5.1f%%' % (raw_home_team_win_pct * 100))
            print('Raw home team win log odds:      %+.5f' % raw_home_team_win_log_odds)
            print('Home court advantage log odds:   %+.5f' % home_court_advantage_log_odds)
            print('Schedule log odds:               %+.5f' % schedule_log_odds)
            print('Adjusted home team win log odds: %+.5f' % home_team_win_log_odds)
            print('Adjusted home team win pct:        %5.1f%%' % (home_team_win_pct * 100))

        return home_team_win_pct


def main():
    predictor = BetPredictor(MinutesProjectionMethod.SEASON_MINUTES)

    print('')
    print('PACE')
    pace_list = [(model.possessions_per_game, team) for team, model in predictor.team_models.items()]
    for p, t in sorted(pace_list, reverse=True):
        print('%5.1f %s' % (p, t))

    print('')
    print('OFFENSE')
    offensive_list = [(model.offensive_efficiency, team) for team, model in predictor.team_models.items()]
    for p, t in sorted(offensive_list, reverse=True):
        print('%5.1f %s' % (p, t))

    print('')
    print('DEFENSE')
    defense_list = [(model.defensive_efficiency, team) for team, model in predictor.team_models.items()]
    for p, t in sorted(defense_list, reverse=True):
        print('%5.1f %s' % (p, t))

    print('')
    print('TOTAL')
    total_list = [(model.offensive_efficiency - model.defensive_efficiency, team) for team, model in predictor.team_models.items()]
    for p, t in sorted(total_list, reverse=True):
        print('%5.1f %s' % (p, t))

    for team in TEAMS:
        print('')
        print(team)
        predictor.team_models[team].dump_minutes()


if __name__ == '__main__':
    main()
