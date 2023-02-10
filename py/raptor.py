"""
Provides utilities to download and parse RAPTOR data.

See: https://projects.fivethirtyeight.com/nba-player-ratings/
"""

import csv
from typing import Dict

import web
from player_names import normalize_player_name, PlayerName

BY_PLAYER_CSV_URL = 'https://projects.fivethirtyeight.com/nba-model/2023/latest_RAPTOR_by_player.csv'


class RaptorStats:
    def __init__(self, row):
        self.minutes = int(row['mp'])
        self.pace_impact = float(row['pace_impact'])
        self.raptor_offense = float(row['raptor_offense'])
        self.raptor_defense = float(row['raptor_defense'])
        self.raptor_total = float(row['raptor_total'])


def get_raptor_stats() -> Dict[PlayerName, RaptorStats]:
    """
    Returns RAPTOR stats for all players.
    """
    csv_text = web.fetch(BY_PLAYER_CSV_URL)
    reader = csv.DictReader(csv_text.splitlines())
    player_stats = {}
    for row in reader:
        player_name = normalize_player_name(row['player_name'])
        assert player_name not in player_stats
        stats = RaptorStats(row)
        player_stats[player_name] = stats

    return player_stats


if __name__ == '__main__':
    get_raptor_stats()
