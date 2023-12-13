#!/usr/bin/env python3
"""
Chris Andersen and David Shin made a bet prior to the 2023-2024 NBA season. Each NBA team was
claimed by exactly one of the two bettors. At the end of the 2023-2024 playoffs, each team scores 1
point per playoff game won. The bettor with the most points wins the bet. The play-in game does not
count.

This script predicts the outcome of the bet.

At a high-level, the prediction is currently made in the following manner:

* The Bradley-Terry model is used on the season's game results up to the present date, to estimate
  each team's strength, along with a home court advantage factor and a rest factor. Each result is
  exponentially weighted by the number of days since the game was played, so that recent results are
  weighted more heavily.

* The model is then used to perform a Monte Carlo simulation to predict the remainder of the season
  and then playoffs. The simulation results are used to predict the final outcome of the bet.
"""
import argparse
import copy
import datetime
import math
from enum import Enum
from typing import Dict, List

from games import get_games, Standings, Game
from raptor import get_raptor_stats, RaptorStats
from rosters import RosterData, Roster
from players import PlayerName
from teams import *

import numpy as np
from typing import Optional

# 100-point difference corresponds to 64% win-rate to match Elo
BETA_SCALE_FACTOR = 100.0 / np.log(1/.36 - 1)

TEAM_DICT = { t : i for i, t in enumerate(TEAMS) }


DAVID_TEAMS = [DEN, MEM, SAC, LAC, PHI, CLE, NYK, NOP, IND, BRK, MIN, UTA, ORL, WAS, HOU]
CHRIS_TEAMS = [MIL, BOS, PHO, GSW, DAL, MIA, LAL, ATL, OKC, CHI, TOR, SAS, CHH, DET, POR]


WinLossMatrix = np.ndarray
RatingArray = np.ndarray


class Constants:
    back_to_back_win_pct = 0.436  # https://www.fastbreakbets.com/betting-tips/betting-nba-teams-back-back/
    rested_win_pct = 0.518  # https://www.fastbreakbets.com/betting-tips/betting-nba-teams-back-back/
    home_court_win_pct = 0.606  # https://bleacherreport.com/articles/1520496-how-important-is-home-court-advantage-in-the-nba


def make_win_loss_matrix(games: List[Game], half_life: Optional[float]) -> WinLossMatrix:
    today = datetime.date.today()
    n = len(TEAMS)
    w = np.zeros((n, n))
    for game in games:
        if game.completed:
            home_team = game.home_team
            away_team = game.away_team
            home_team_idx = TEAM_DICT[home_team]
            away_team_idx = TEAM_DICT[away_team]

            x = 1.0
            if half_life is not None:
                n_days_ago = (today - game.dt).days
                x = 2 ** (-n_days_ago / half_life)
            if game.was_won_by(home_team):
                w[home_team_idx, away_team_idx] += x
            else:
                w[away_team_idx, home_team_idx] += x
    return w


def compute_ratings(w: WinLossMatrix) -> RatingArray:
    """
    Accepts an (n, n)-shaped matrix w, where w[i, j] is the number of wins player i has over
    player j.

    Outputs a length-n array beta, where beta[i] is the rating of player i.

    Fixes beta[0] = 0 arbitrarily.
    """
    eps = 1e-6
    n = w.shape[0]
    assert w.shape == (n, n)
    assert np.all(w >= 0)
    assert w.diagonal().sum() == 0
    ww = w + w.T
    W = np.sum(w, axis=1)

    n_iters = 0
    p = np.ones(n, dtype=np.float64)
    while True:
        n_iters += 1
        pp = p.reshape((-1, 1)) + p.reshape((1, -1))
        wp_sum = np.sum(ww / pp, axis=1)
        gradient = W / p - wp_sum
        max_gradient = np.max(np.abs(gradient))
        if max_gradient < eps:
            break

        q = W / wp_sum
        q /= min(q)  # so that worst team's rating is 0
        p = q

    return p


# def compute_ratings2(w: WinLossMatrix) -> RatingArray:
#     """
#     Accepts an (n, n)-shaped matrix w, where w[i, j] is the number of wins player i has over
#     player j.

#     Outputs a length-n array beta, where beta[i] is the rating of player i.

#     Fixes beta[0] = 0 arbitrarily.
#     """
#     eps = 1e-6
#     n = w.shape[0]
#     assert w.shape == (n, n)
#     assert np.all(w >= 0)
#     assert w.diagonal().sum() == 0
#     ww = w + w.T
#     W = np.sum(w, axis=1)

#     n_iters = 0
#     p = np.ones(n, dtype=np.float64)
#     while True:
#         n_iters += 1
#         pp = p.reshape((-1, 1)) + p.reshape((1, -1))
#         wp_sum = np.sum(ww / pp, axis=1)
#         gradient = W / p - wp_sum
#         max_gradient = np.max(np.abs(gradient))
#         if max_gradient < eps:
#             break

#         N = np.sum(w * p.reshape((-1, 1)) / pp, axis=1)
#         D = np.sum(w / pp, axis=0)
#         q = N / D

#         q /= q[0]  # so that worst team's rating is 0
#         p = q

#     print(f'compute_ratings2 converged after {n_iters} iterations')
#     beta = np.log(p) * BETA_SCALE_FACTOR
#     return beta


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

    def playoff_count(self):
        return self.made_playoffs_count

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

    def dump(self, num_sims: int):
        print('-' * 80)
        print(f'{self.team} sim results')
        print('Playoff probability: %6.2f%%' % (self.playoff_count() * 100.0 / num_sims))
        print('Title probability:   %6.2f%%' % (self.title_count() * 100.0 / num_sims))
        TeamSimResults.distribution_dump('Playoff wins', self.playoff_wins_distribution, num_sims, True)
        TeamSimResults.distribution_dump('Regular season wins', self.regular_season_wins_distribution, num_sims)
        if self.made_playoffs_count > 0:
            TeamSimResults.distribution_dump('Playoff seed', self.seed_distribution, self.made_playoffs_count)

        print('')


class OverallSimResults:
    def __init__(self):
        self.count = 0
        self.david_team_wins = 0
        self.chris_team_wins = 0
        self.david_bet_wins = 0
        self.chris_bet_wins = 0
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

        self.david_team_wins += david_team_wins
        self.chris_team_wins += chris_team_wins
        if david_team_wins > chris_team_wins:
            self.david_bet_wins += 1
        elif david_team_wins < chris_team_wins:
            self.chris_bet_wins += 1
        else:
            self.tie_count += 1

    def dump(self):
        print('')
        print('Overall results:')
        print('----------------')
        print('Number of simulations: {}'.format(self.count))
        print('Pr[David wins]:        {:5.2f}%'.format(100 * self.david_bet_wins / self.count))
        print('Pr[Chris wins]:        {:5.2f}%'.format(100 * self.chris_bet_wins / self.count))
        print('Pr[Tie]:               {:5.2f}%'.format(100 * self.tie_count / self.count))
        print('Avg David team wins:   {:.2f}'.format(self.david_team_wins / self.count))
        print('Avg Chris team wins:   {:.2f}'.format(self.chris_team_wins / self.count))

        for results in sorted(self.team_results.values(), key=lambda r: r.score(), reverse=True):
            results.dump(self.count)


class BetPredictor:
    def __init__(self, half_life_in_days: Optional[float]):
        self.half_life_in_days = half_life_in_days
        self.games: List[Game] = get_games()
        self.standings = Standings(self.games)

        self.w = make_win_loss_matrix(self.games, half_life_in_days)
        self.p = compute_ratings(self.w)

    def simulate(self) -> PlayoffRecord:
        standings = copy.deepcopy(self.standings)
        games = copy.deepcopy(self.games)
        for game in games:
            if game.completed:
                continue
            home_team_win_pct = self.predict_home_team_win_pct(game)
            game.simulate(home_team_win_pct)
            standings.update(game)

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
                game.simulate(self.predict_home_team_win_pct(game))
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
        game_7_v_8.simulate(self.predict_home_team_win_pct(game_7_v_8))
        game_9_v_10.simulate(self.predict_home_team_win_pct(game_9_v_10))

        seven_seed = game_7_v_8.winner
        eighth_seed_game = Game('Sim', game_7_v_8.loser, game_9_v_10.winner)
        eighth_seed_game.simulate(self.predict_home_team_win_pct(eighth_seed_game))
        eighth_seed = eighth_seed_game.winner

        return seeding[:6] + [seven_seed, eighth_seed]

    def predict_home_team_win_pct(self, game: Game, debug: bool = False) -> float:
        home_team = game.home_team
        away_team = game.away_team

        home_p = self.p[TEAM_DICT[home_team]]
        away_p = self.p[TEAM_DICT[away_team]]

        raw_home_team_win_pct = home_p / (home_p + away_p)
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
            print('  p:            %+5.1f' % home_p)
            print('Away team: %s (days rest: %s)' % (away_team, game.days_rest_for_away_team))
            print('  p:            %+5.1f' % away_p)
            print('Raw home team win pct:             %5.1f%%' % (raw_home_team_win_pct * 100))
            print('Raw home team win log odds:      %+.5f' % raw_home_team_win_log_odds)
            print('Home court advantage log odds:   %+.5f' % home_court_advantage_log_odds)
            print('Schedule log odds:               %+.5f' % schedule_log_odds)
            print('Adjusted home team win log odds: %+.5f' % home_team_win_log_odds)
            print('Adjusted home team win pct:        %5.1f%%' % (home_team_win_pct * 100))

        return home_team_win_pct


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--num-sims', type=int, default=1000,
                        help='num sims (default: %(default)s)')
    parser.add_argument('-H', '--half-life-in-days', type=float,
                        help='half life in days for exponential weighting '
                        '(default: uniform weighting)')
    return parser.parse_args()


def main():
    args = get_args()

    predictor = BetPredictor(args.half_life_in_days)
    sim_results = OverallSimResults()
    for _ in range(args.num_sims):
        playoff_record = predictor.simulate()
        sim_results.update(playoff_record)

    sim_results.dump()


if __name__ == '__main__':
    main()
