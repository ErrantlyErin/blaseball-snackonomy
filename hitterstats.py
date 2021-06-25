import blaseball_mike.database as mike
import gspread
import json
import logging
import sqlite3
from sseclient import SSEClient


def update(spreadsheet_ids):
    '''
    Updates all hitter stats in the future hitting income tab of this season's snack spreadsheet
    '''

    logging.info("Updating hitter spreadsheet...")

    # Get current season
    sim = mike.get_simulation_data()
    season = sim['season']+1
    spreadsheet_id = spreadsheet_ids[season]

    # Connect to spreadsheet
    credentials = gspread.service_account()
    worksheet = credentials.open_by_key(spreadsheet_id).worksheet('All Hitters')

    # Get current dates
    today = sim['day']+1
    tomorrow = sim['day']+2

    # Initialize database
    sqldb = sqlite3.connect('databases/blaseball_S{}.db'.format(season))
    sqldb.execute('''DROP TABLE IF EXISTS hitters_proj''')
    sqldb.execute('''
        CREATE TABLE IF NOT EXISTS hitters_proj (
            player_id TINYTEXT NOT NULL,
            player_name TINYTEXT,
            team_name TINYTEXT,
            games TINYINT UNSIGNED,
            pas SMALLINT UNSIGNED,
            hits SMALLINT UNSIGNED,
            homeruns SMALLINT UNSIGNED,
            steals SMALLINT UNSIGNED,
            papg FLOAT,
            hppa FLOAT,
            hrppa FLOAT,
            sbppa FLOAT,
            lineup_avg FLOAT,
            lineup_current TINYINT UNSIGNED,
            can_earn TINYINT UNSIGNED,
            multiplier TINYINT UNSIGNED,
            primary key (player_id)
        )
    ''')

    # Prep some fields:
    # Mods that mean a player can't earn money
    inactive_mods = set(['ELSEWHERE','SHELLED','LEGENDARY','REPLICA','NON_IDOLIZED'])
    # Incinerated players
    incinerated = mike.get_tributes()['players']
    incinerated_ids = set([player['playerId'] for player in incinerated])
    # Map of team full name to shorthand
    teams = mike.get_all_teams()
    teams_shorten = {}
    for team_id in teams:
        teams_shorten[team_id] = teams[team_id]['shorthand']
    # List of teams in league (ignore historical/coffee cup teams)
    teams_inleague = [team for team in teams.values() if team['stadium']]
    # Shadows players for players who moved to shadows
    shadows = [ids for team in teams_inleague for ids in team['shadows']]
    # Pitchers for players who reverbed/feedbacked to being a pitcher
    pitchers = [ids for team in teams_inleague for ids in team['rotation']]
    # Teams playing tomorrow to support the postseason
    teams_playing = set()
    # After the brackets have been decided but before the first round begins, it's complicated
    if sim['phase'] in [8]:
        # Get full streamdata
        stream = SSEClient('http://blaseball.com/events/streamData')
        moveon = -10
        for message in stream:
            while moveon < 1:
                # At seemingly fixed intervals, the stream sends an empty message
                if not str(message):
                    moveon += 1
                    continue
                data = json.loads(str(message))
                # Sometimes the stream just sends fights
                if 'games' not in data['value']:
                    moveon += 1
                    continue
                # This should always work, though
                games = json.loads(str(message))['value']['games']
                games_tomorrow = games['tomorrowSchedule']
                # Log this info since I don't actually know what it looks like
                logging.info(games_tomorrow)
                for game_tomorrow in games_tomorrow:
                    teams_playing.add(game_tomorrow['awayTeam'])
                    teams_playing.add(game_tomorrow['homeTeam'])
                moveon = 1
            else:
                break
    #     playoffs = mike.get_playoff_details(season)
    #     round_id = playoffs['rounds'][0] # Just get wildcard round
    #     round = mike.get_playoff_round(round_id)
    #     matchups_wildcard_ids = [round['matchups'][1],round['matchups'][5]]
    #     for matchup_wildcard in mike.get_playoff_matchups(matchups_wildcard_ids).values():
    #         teams_playing.add(matchup_wildcard['homeTeam'])
    #         teams_playing.add(matchup_wildcard['awayTeam'])
    #     # This only has the overbracket teams... Can't find an endpoint for underbracket :/
    # else:
    # During the season and while postseason is in progress, we can just get tomorrow's games
    else:
        tomorrow_games = mike.get_games(season, tomorrow)
        for game in tomorrow_games:
            teams_playing.add(tomorrow_games[game]['awayTeam'])
            teams_playing.add(tomorrow_games[game]['homeTeam'])
    # After the election, get current team lineups to update the recommendations for D0
    if sim['phase'] == 0:
        teams_lineup = {}
        for team in teams_inleague:
            teammate_details = mike.get_player(team['lineup']).values()
            lineup_current = 0
            for teammate_detail in teammate_details:
                teammate_mods = set(teammate_detail['permAttr']+teammate_detail['seasAttr']+teammate_detail['itemAttr'])
                if not any(mod in teammate_mods for mod in ['SHELLED','ELSEWHERE']):
                    lineup_current += 1
            teams_lineup[team['id']] = lineup_current

    # Get players
    player_ids = sqldb.execute('''
        SELECT DISTINCT player_id FROM hitters_statsheets
    ''')

    # Get details for use later (mods, team active, etc.)
    player_ids = [player_id[0] for player_id in player_ids]
    player_details = mike.get_player(player_ids)

    for player_id in player_ids:

        # If this player can't be gotten, like, say a ghost inhabits someone but the ghost doesn't technically EXIST...
        if player_id not in player_details:
            continue

        # Calculate money stats
        player_name = list(sqldb.execute('''
            SELECT player_name FROM hitters_statsheets WHERE player_id = "{}" ORDER by day DESC LIMIT 1
        '''.format(player_id)))[0][0]
        team_name = list(sqldb.execute('''
            SELECT team_name FROM hitters_statsheets WHERE player_id = "{}" ORDER by day DESC LIMIT 1
        '''.format(player_id)))[0][0]
        games = list(sqldb.execute('''
            SELECT Count(*) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        pas = list(sqldb.execute('''
            SELECT SUM(pas) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        hits = list(sqldb.execute('''
            SELECT SUM(hits) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        homeruns = list(sqldb.execute('''
            SELECT SUM(homeruns) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        steals = list(sqldb.execute('''
            SELECT SUM(steals) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        lineup = list(sqldb.execute('''
            SELECT SUM(lineup_size) FROM hitters_statsheets WHERE player_id = "{}"
        '''.format(player_id)))[0][0]
        lineup_current = list(sqldb.execute('''
            SELECT lineup_size FROM hitters_statsheets WHERE player_id = "{}" ORDER by day DESC LIMIT 1
        '''.format(player_id)))[0][0]

        # if player_id == '11de4da3-8208-43ff-a1ff-0b3480a0fbf1':
        #     logging.info(pas/games)
        #     logging.info(lineup/games)
        #     logging.info(hits/pas)
        #     logging.info(homeruns/pas)
        #     logging.info(steals/pas)
        #     quit()
        # logging.info([player_name, atbats, pas, hits-homeruns, homeruns, steals])

        # Get current player mods
        player_mods = player_details[player_id]['permAttr']+player_details[player_id]['seasAttr']+player_details[player_id]['itemAttr']

        # Check if this player can earn any money next game
        # Check if this player has a mod preventing them from making money
        can_earn = int(not any(mod in player_mods for mod in inactive_mods))
        # Check if this player is currently in the shadows, pitching, or incinerated
        if player_id in shadows or player_id in pitchers or player_id in incinerated_ids:
            can_earn = 0
        # Check if this team is playing tomorrow
        # But if we're in the offseason still let them be shown to make D0 predictions for the next season
        if not player_details[player_id]['leagueTeamId'] in teams_playing and sim['phase'] not in [0,12,13]:
            can_earn = 0

        # Determine payout multiplier
        multiplier = 1
        if 'DOUBLE_PAYOUTS' in player_mods:
            multiplier = 2
        if 'CREDIT_TO_THE_TEAM' in player_mods:
            multiplier = 5

        # Get earning stats
        hppa = (hits-homeruns)/pas # Homeruns don't count for seeds
        hrppa = homeruns/pas
        sbppa = steals/pas

        # Calculate some other stats
        papg = pas/games
        lineup_avg = lineup/games

        # Get each player's current team's shortname (abbreviation)
        team_abbr = teams_shorten[player_details[player_id]['leagueTeamId']]

        # Finally, if we're between the election and D0, get updated lineup sizes post-election
        if sim['phase'] == 0:
            team_id = player_details[player_id]['leagueTeamId']
            lineup_current = teams_lineup[team_id]

        # Add player data to database
        entry = [player_id, player_name, team_abbr, games, pas, hits-homeruns, homeruns, steals, papg, hppa, hrppa, sbppa, lineup_avg, lineup_current, can_earn, multiplier]
        sqldb.execute('''INSERT INTO hitters_proj (player_id, player_name, team_name, games, pas, hits, homeruns, steals, papg, hppa, hrppa, sbppa, lineup_avg, lineup_current, can_earn, multiplier)
            VALUES ("{0}", "{1}", "{2}", {3}, {4}, {5}, {6}, {7}, {8}, {9}, {10}, {11}, {12}, {13}, {14}, {15})
            ON CONFLICT (player_id) DO
            UPDATE SET player_name="{1}", team_name="{2}", games={3}, pas={4}, hits={5}, homeruns={6}, steals={7}, papg={8}, hppa={9}, hrppa={10}, sbppa={11}, lineup_avg={12}, lineup_current={13}, can_earn={14}, multiplier={15}'''.format(*entry))

    # Save changes to database
    sqldb.commit()

    # Update spreadsheet
    payload = [list(player) for player in sqldb.execute('''SELECT * FROM hitters_proj ORDER BY team_name''')]
    while len(payload) < 300:
        payload.append(['','','','','','','','','','','','','','','',''])
    worksheet.update('A4:P', payload)

    # Update the day
    worksheet.update('B1', today)

    logging.info("Hitter spreadsheet updated.")

if __name__ == "__main__":
    spreadsheet_ids = {
        19: '1_p6jsPxMvO0nGE-fiqGfilu-dxeUc994k2zwAGNVNr0',
        20: '1EAqMvv2KrC9DjlJdlXrH_JXmHtAStxRJ661lWbuwYQs',
        21: '1DBCpsYlDOft5wve7IKTXAH-3zeoZIUy7A_R4a5uiYz8'
    }
    update(spreadsheet_ids)