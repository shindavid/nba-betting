PlayerName = str

def normalize_player_name(player_name: PlayerName) -> PlayerName:
    """
    Normalizes a player name to a standard format.
    """
    return player_name.replace('.', '')
