from bball_reference import PlayerDirectory


def main():
    directory = PlayerDirectory.instance()
    player = directory.get('Kevin Durant')
    log = directory.get_career_log(player)
    for season in sorted(log.season_game_logs):
        season_log = log.season_game_logs[season]
        for game_log in season_log.games:
            print(f'{season} {game_log.minutes:.3f} {game_log.game}')


if __name__ == '__main__':
    main()
