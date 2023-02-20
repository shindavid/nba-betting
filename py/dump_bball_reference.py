from bball_reference import PlayerDirectory


def main():
    directory = PlayerDirectory.instance()

    player_list = [
        'Kevin Durant',
        'Chris Andersen',
    ]
    for player_name in player_list:
        player = directory.get(player_name)
        log = directory.get_career_log(player)
        log.summarize()


if __name__ == '__main__':
    main()
