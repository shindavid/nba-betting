from player_events import get_all_player_events


def main():
    for evt in get_all_player_events():
        print(evt)


if __name__ == '__main__':
    main()
