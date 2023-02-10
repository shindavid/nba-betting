#!/usr/bin/env python3
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
import argparse
import copy
import math
from enum import Enum
from typing import Dict, List

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

    def dump_roster(self):
        print('%8s %8s %5s %5s %5s %s' % ('ProjMPG', 'MPG', 'Off', 'Def', 'Tot', 'Player'))
        for p, raptor in sorted(self.raptor_stats.items(), key=lambda x: x[1].raptor_total, reverse=True):
            print('%5.1fmin %5.1fmin %+5.1f %+5.1f %+5.1f %s' % (
                self.projected_minutes[p],
                self.roster.stats[p].mpg,
                raptor.raptor_offense,
                raptor.raptor_defense,
                raptor.raptor_total,
                p,
            ))
        pass

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
        worst until all 48.3*5 minutes are used up. The maximum amount of minutes any player can be allocated is
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


class PlayoffRecord:
    def __init__(self, standings: Standings, east_teams: List[Team], west_teams: List[Team]):
        self.standings = standings
        self.east_teams = east_teams
        self.west_teams = west_teams
        self.seeds = {}
        for t, team in enumerate(east_teams):
            self.seeds[team] = t+1
        for t, team in enumerate(west_teams):
            self.seeds[team] = t+1

        self.win_counts = {team: 0 for team in east_teams + west_teams}
        self.log: List[str] = []

    def update(self, teams: List[Team], win_counts: Dict[Team, int]):
        for team, count in win_counts.items():
            self.win_counts[team] += count

        n = len(teams)
        for k in range(n // 2):
            top_team = teams[k]
            bot_team = teams[n-k-1]
            top_seed = self.seeds[top_team]
            bot_seed = self.seeds[bot_team]
            top_wins = win_counts[top_team]
            bot_wins = win_counts[bot_team]

            if top_wins == 4:
                self.log.append(f'{top_team}({top_seed}) def. {bot_team}({bot_seed}) {top_wins}-{bot_wins}')
            else:
                self.log.append(f'{bot_team}({bot_seed}) def. {top_team}({top_seed}) {bot_wins}-{top_wins}')
            assert max(top_wins, bot_wins) == 4
            assert min(top_wins, bot_wins) < 4, (teams, win_counts)


class TeamSimResults:
    def __init__(self, team: Team):
        self.team = team
        self.made_playoffs_count = 0
        self.regular_season_wins_distribution = defaultdict(int)  # wins -> count
        self.seed_distribution = defaultdict(int)  # seed -> count
        self.playoff_wins_distribution = defaultdict(int)  # win_count -> count

    def score(self):
        return sum(k * v for k, v in self.playoff_wins_distribution.items())

    def title_count(self):
        return self.playoff_wins_distribution.get(16, 0)

    @staticmethod
    def distribution_dump(descr: str, distribution: Dict[int, int], denominator: int, playoff_wins: bool = False):
        distribution_total = sum(distribution.values())
        mean = sum(k * v for k, v in distribution.items()) / denominator
        distribution_values = list(distribution.values())
        if playoff_wins:
            distribution_values.append(denominator - distribution_total)

        star_weight = 100.0 / sum(distribution_values)

        print('')
        print(descr)
        print('Mean: %.2f' % mean)
        print('')

        playoff_prefix_distr = {
            -1: 'MISSED PLAYOFFS',
            0:  '1ST ROUND',
            4:  'CONF SEMIS',
            8:  'CONF FINALS',
            12: 'FINALS',
            16: 'CHAMPIONS',
        }
        prefix_len = max(len(s) for s in playoff_prefix_distr.values())

        keys = list(sorted(distribution.keys()))
        min_key = -1 if playoff_wins else keys[0]
        max_key = 16 if playoff_wins else keys[-1]
        for key in range(min_key, max_key + 1):
            count = distribution.get(key, 0)
            prefix = ''
            if playoff_wins:
                if key == -1:
                    count = denominator - distribution_total
                prefix_fmt = '%%-%ds' % prefix_len
                prefix = prefix_fmt % playoff_prefix_distr.get(key, '')

            key_str = '%2d' % key if key >= 0 else '  '
            stars = '*' * int(math.ceil(count * star_weight))
            print('%s%s: %s' % (prefix, key_str, stars))

    def dump(self, model: TeamModel, num_sims: int):
        print('-' * 80)
        print(f'{self.team} sim results')
        print('Title probability: %.2f%%' % (self.title_count() * 100.0 / num_sims))
        TeamSimResults.distribution_dump('Playoff wins', self.playoff_wins_distribution, num_sims, True)
        TeamSimResults.distribution_dump('Regular season wins', self.regular_season_wins_distribution, num_sims)
        if self.made_playoffs_count > 0:
            TeamSimResults.distribution_dump('Playoff seed', self.seed_distribution, self.made_playoffs_count)

        print('')
        model.dump_roster()


class OverallSimResults:
    def __init__(self):
        self.count = 0
        self.david_win_count = 0
        self.chris_win_count = 0
        self.tie_count = 0
        self.team_results: Dict[Team, TeamSimResults] = {t: TeamSimResults(t) for t in TEAMS}

    def update(self, playoff_record: PlayoffRecord):
        self.count += 1

        david_team_wins = 0
        chris_team_wins = 0
        for team, win_count in playoff_record.win_counts.items():
            if team in DAVID_TEAMS:
                david_team_wins += win_count
            elif team in CHRIS_TEAMS:
                chris_team_wins += win_count
            else:
                raise Exception(f'Unknown team {team}')

            team_results = self.team_results[team]
            team_results.made_playoffs_count += 1
            team_results.seed_distribution[playoff_record.seeds[team]] += 1
            team_results.playoff_wins_distribution[win_count] += 1

        for team in TEAMS:
            team_results = self.team_results[team]
            team_results.regular_season_wins_distribution[playoff_record.standings.wins(team)] += 1

        if david_team_wins > chris_team_wins:
            self.david_win_count += 1
        elif david_team_wins < chris_team_wins:
            self.chris_win_count += 1
        else:
            self.tie_count += 1

    def dump(self, team_models: Dict[Team, TeamModel], minutes_projection_method: MinutesProjectionMethod):
        print('')
        print('Overall results:')
        print('----------------')
        print('Number of simulations: {}'.format(self.count))
        print('MPG Projection Method: {}'.format(str(minutes_projection_method).split('.')[-1]))
        print('Pr[David wins]: {:.2f}%'.format(100 * self.david_win_count / self.count))
        print('Pr[Chris wins]: {:.2f}%'.format(100 * self.chris_win_count / self.count))
        print('Pr[Tie]:        {:.2f}%'.format(100 * self.tie_count / self.count))

        for results in sorted(self.team_results.values(), key=lambda r: r.score(), reverse=True):
            results.dump(team_models[results.team], self.count)


class BetPredictor:
    def __init__(self, minutes_projection_method: MinutesProjectionMethod):
        self.minutes_projection_method = minutes_projection_method
        self.games = get_games()
        self.standings = Standings(self.games)
        self.rosters = get_rosters()
        self.raptor_stats = get_raptor_stats()
        self.team_models = {roster.team: TeamModel(roster, self.standings, self.raptor_stats, minutes_projection_method)
                            for roster in self.rosters.values()}

    def simulate(self):
        standings = copy.deepcopy(self.standings)
        games = copy.deepcopy(self.games)
        for game in games:
            if game.completed:
                continue
            home_team_win_pct = self.predict_home_team_win_pct(game, GameType.REGULAR_SEASON)
            game.simulate(home_team_win_pct)
            standings.update(game)

        for team, record in standings.records.items():
            assert record.num_games == 82, record

        seeding = standings.playoff_seeding()
        east_seeding8 = self.simulate_play_in_tournament(seeding.east_seeding)
        west_seeding8 = self.simulate_play_in_tournament(seeding.west_seeding)

        playoff_record = PlayoffRecord(standings, east_seeding8, west_seeding8)

        east_seeding4 = self.simulate_playoff_round(east_seeding8, playoff_record)
        west_seeding4 = self.simulate_playoff_round(west_seeding8, playoff_record)

        east_seeding2 = self.simulate_playoff_round(east_seeding4, playoff_record)
        west_seeding2 = self.simulate_playoff_round(west_seeding4, playoff_record)

        east_seeding1 = self.simulate_playoff_round(east_seeding2, playoff_record)
        west_seeding1 = self.simulate_playoff_round(west_seeding2, playoff_record)

        east_champion = east_seeding1[0]
        west_champion = west_seeding1[0]
        home_team = standings.determine_finals_home_court_advantage(east_champion, west_champion)
        away_team = east_champion if home_team == west_champion else west_champion
        self.simulate_playoff_round([home_team, away_team], playoff_record)

        return playoff_record

    def simulate_playoff_round(self, teams: List[Team], playoff_record: PlayoffRecord) -> List[Team]:
        """
        Expects a power-of-two number of teams, in sorted order of seed.

        Simulates a best-of-seven, recording the results in playoff_record.
        """
        win_counts = { t: 0 for t in teams }
        top_seed_home_court_list = [1, 1, 0, 0, 1, 0, 1]  # 2 - 2 - 1 - 1 - 1 format

        n = len(teams)

        for i in range(0, n // 2):
            top_seed = teams[i]
            bot_seed = teams[n - i - 1]

            for top_seed_home_court in top_seed_home_court_list:
                home_team = top_seed if top_seed_home_court else bot_seed
                away_team = bot_seed if top_seed_home_court else top_seed
                game = Game('Sim', home_team, away_team)
                game.simulate(self.predict_home_team_win_pct(game, GameType.PLAYOFFS))
                win_counts[game.winner] += 1
                if win_counts[game.winner] == 4:
                    break

        winners = [t for t in teams if win_counts[t] == 4]
        assert len(winners) == n // 2, win_counts
        playoff_record.update(teams, win_counts)
        return winners

    def simulate_play_in_tournament(self, seeding: List[Team]):
        assert len(seeding) == 10, seeding
        game_7_v_8 = Game('Sim', seeding[6], seeding[7])
        game_9_v_10 = Game('Sim', seeding[8], seeding[9])
        game_7_v_8.simulate(self.predict_home_team_win_pct(game_7_v_8, GameType.PLAYOFFS))
        game_9_v_10.simulate(self.predict_home_team_win_pct(game_9_v_10, GameType.PLAYOFFS))

        seven_seed = game_7_v_8.winner
        eighth_seed_game = Game('Sim', game_7_v_8.loser, game_9_v_10.winner)
        eighth_seed_game.simulate(self.predict_home_team_win_pct(eighth_seed_game, GameType.PLAYOFFS))
        eighth_seed = eighth_seed_game.winner

        return seeding[:6] + [seven_seed, eighth_seed]

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

    def aux_dump(self):
        print('')
        print('PACE')
        pace_list = [(model.possessions_per_game, team) for team, model in self.team_models.items()]
        for p, t in sorted(pace_list, reverse=True):
            print('%5.1f %s' % (p, t))

        print('')
        print('OFFENSE')
        offensive_list = [(model.offensive_efficiency, team) for team, model in self.team_models.items()]
        for p, t in sorted(offensive_list, reverse=True):
            print('%5.1f %s' % (p, t))

        print('')
        print('DEFENSE')
        defense_list = [(model.defensive_efficiency, team) for team, model in self.team_models.items()]
        for p, t in sorted(defense_list, reverse=True):
            print('%5.1f %s' % (p, t))

        print('')
        print('TOTAL')
        total_list = [(model.offensive_efficiency - model.defensive_efficiency, team) for team, model in self.team_models.items()]
        for p, t in sorted(total_list, reverse=True):
            print('%5.1f %s' % (p, t))

        for team in TEAMS:
            print('')
            print(team)
            self.team_models[team].dump_minutes()


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--num-sims', type=int, default=10000, help='num sims (default: %(default)s)')
    parser.add_argument('-m', '--minutes-projection-method', type=str, default='RAPTOR_RANK',
                        help='minutes projection method (default: %(default)s)')
    return parser.parse_args()


def main():
    args = get_args()
    minutes_projection_method = MinutesProjectionMethod[args.minutes_projection_method]
    predictor = BetPredictor(minutes_projection_method)
    sim_results = OverallSimResults()
    for _ in range(args.num_sims):
        sim_results.update(predictor.simulate())
    sim_results.dump(predictor.team_models, predictor.minutes_projection_method)


if __name__ == '__main__':
    main()
