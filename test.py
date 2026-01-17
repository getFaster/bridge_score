import pytest
from scoring import calculate_bridge_score

def test_calculate_bridge_score_part_score_non_vulnerable():
    """Test a part score contract non-vulnerable."""
    assert calculate_bridge_score("2C S m 0") == 90  # 2*20 + 50


def test_calculate_bridge_score_game_major_non_vulnerable():
    """Test game in major suit non-vulnerable."""
    assert calculate_bridge_score("4H N m 0") == 420  # 4*30 + 300


def test_calculate_bridge_score_game_major_vulnerable():
    """Test game in major suit vulnerable."""
    assert calculate_bridge_score("4S E v 0") == 620  # 4*30 + 500


def test_calculate_bridge_score_game_notrump_non_vulnerable():
    """Test game in no trump non-vulnerable."""
    assert calculate_bridge_score("3NT W m 0") == 400  # 3*30+10 + 300


def test_calculate_bridge_score_game_notrump_vulnerable():
    """Test game in no trump vulnerable."""
    assert calculate_bridge_score("3NT S vul 0") == 600  # 3*30+10 + 500


def test_calculate_bridge_score_small_slam_non_vulnerable():
    """Test small slam non-vulnerable."""
    assert calculate_bridge_score("6C N m 0") == 920  # 6*20 + 300 + 500


def test_calculate_bridge_score_small_slam_vulnerable():
    """Test small slam vulnerable."""
    assert calculate_bridge_score("6D S v 0") == 1370  # 6*20 + 500 + 750


def test_calculate_bridge_score_grand_slam_non_vulnerable():
    """Test grand slam non-vulnerable."""
    assert calculate_bridge_score("7H E m 0") == 1510  # 7*30 + 300 + 1000


def test_calculate_bridge_score_grand_slam_vulnerable():
    """Test grand slam vulnerable."""
    assert calculate_bridge_score("7NT W v 0") == 2220  # 7*30+10 + 500 + 1500


def test_calculate_bridge_score_with_overtricks_minor():
    """Test contract with overtricks in minor suit."""
    assert calculate_bridge_score("2D S m 2") == 130  # 2*20 + 50 + 2*20


def test_calculate_bridge_score_with_overtricks_major():
    """Test contract with overtricks in major suit."""
    assert calculate_bridge_score("4H N v 1") == 650  # 4*30 + 500 + 1*30


def test_calculate_bridge_score_with_overtricks_notrump():
    """Test contract with overtricks in no trump."""
    assert calculate_bridge_score("3NT S m 2") == 460  # 3*30+10 + 300 + 2*30


def test_calculate_bridge_score_undertricks_non_vulnerable():
    """Test failed contract non-vulnerable."""
    assert calculate_bridge_score("4S N m -2") == -100  # 2*50


def test_calculate_bridge_score_undertricks_vulnerable():
    """Test failed contract vulnerable."""
    assert calculate_bridge_score("5C S v -3") == -300  # 3*100


def test_calculate_bridge_score_invalid_format():
    """Test invalid input format."""
    assert calculate_bridge_score("invalid") == 0
    assert calculate_bridge_score("3S N") == 0
    assert calculate_bridge_score("") == 0


def test_calculate_bridge_score_minor_suit_game():
    """Test game in minor suit (5C/5D)."""
    assert calculate_bridge_score("5D W m 0") == 400  # 5*20 + 300


def test_calculate_bridge_score_vulnerability_variations():
    """Test different vulnerability notations."""
    assert calculate_bridge_score("3NT S v 0") == 600
    assert calculate_bridge_score("3NT S vul 0") == 600
    assert calculate_bridge_score("3NT S V 0") == 600


def test_swiss_pairing_17_teams_8_rounds():
    """
    Test Swiss pairing system with 17 teams over 8 rounds.
    Simulates a complete tournament with random VP results.
    Uses a 20 VP system (total VPs in a match sum to 20).
    """
    from movements import swiss_pairing
    import random
    
    random.seed(42)  # For reproducibility
    
    # 17 teams means we need an 18th team as bye
    num_teams = 17
    num_rounds = 8
    bye_team = num_teams + 1  # Team 18 is the bye
    
    # All teams including bye
    all_teams = list(range(1, num_teams + 1)) + [bye_team]
    
    # Initialize standings (all teams start with 0 VP)
    standings = {team: 0.0 for team in all_teams}
    
    # Initialize previous opponents
    previous_opponents = {team: [] for team in all_teams}
    
    print("\n" + "="*80)
    print(f"SWISS SYSTEM TOURNAMENT - {num_teams} TEAMS - {num_rounds} ROUNDS")
    print("="*80)
    
    for round_num in range(1, num_rounds + 1):
        print(f"\n{'='*80}")
        print(f"ROUND {round_num}")
        print(f"{'='*80}")
        
        # Generate pairings for this round
        pairings = swiss_pairing(all_teams, standings, previous_opponents, round_num, bye_team)
        
        # Extract unique matches (skip duplicate open/closed entries)
        matches = []
        seen_matches = set()
        for table, room, team_ns, team_ew in pairings:
            match_key = tuple(sorted([team_ns, team_ew]))
            if room == 'open' and match_key not in seen_matches:
                matches.append((table, team_ns, team_ew))
                seen_matches.add(match_key)
        
        print(f"\nPairings (showing {len(matches)} matches):")
        for table, team1, team2 in matches:
            print(f"  Table {table}: Team {team1:2d} ({standings[team1]:5.1f} VP) vs Team {team2:2d} ({standings[team2]:5.1f} VP)")
        
        # Simulate results - generate random VPs that sum to 20
        print(f"\nResults:")
        for table, team1, team2 in matches:
            # Generate random VP between 0 and 20 for team1
            # Common distribution: more likely around 10, rare extremes
            vp1 = random.triangular(0, 20, 10)  # Triangular distribution centered at 10
            vp1 = round(vp1 * 2) / 2  # Round to nearest 0.5
            vp2 = 20 - vp1
            
            standings[team1] += vp1
            standings[team2] += vp2
            
            # Update opponent history
            previous_opponents[team1].append(team2)
            previous_opponents[team2].append(team1)
            
            winner = team1 if vp1 > vp2 else (team2 if vp2 > vp1 else "Tie")
            print(f"  Table {table}: Team {team1:2d} gets {vp1:4.1f} VP, Team {team2:2d} gets {vp2:4.1f} VP {f'(Team {winner} wins)' if winner != 'Tie' else '(Tie)'}")
        
        # Handle bye - team with bye gets 10 VP
        playing_teams = set()
        for table, team1, team2 in matches:
            playing_teams.add(team1)
            playing_teams.add(team2)
        
        bye_teams = set(range(1, num_teams + 1)) - playing_teams
        if bye_teams:
            for bye_team_id in bye_teams:
                standings[bye_team_id] += 10.0
                previous_opponents[bye_team_id].append(bye_team)
                previous_opponents[bye_team].append(bye_team_id)
                print(f"\n  Team {bye_team_id} has BYE - receives 10.0 VP")
        
        # Print standings after this round
        print(f"\nStandings after Round {round_num}:")
        sorted_standings = sorted(standings.items(), key=lambda x: x[1], reverse=True)
        for rank, (team, vp) in enumerate(sorted_standings, 1):
            if team == bye_team:
                continue
            matches_played = len(previous_opponents[team])
            print(f"  {rank:2d}. Team {team:2d}: {vp:6.1f} VP ({matches_played} matches)")
    
    # Final tournament summary
    print(f"\n{'='*80}")
    print("FINAL STANDINGS")
    print(f"{'='*80}")
    sorted_standings = sorted(
        [(t, v) for t, v in standings.items() if t != bye_team], 
        key=lambda x: x[1], 
        reverse=True
    )
    for rank, (team, vp) in enumerate(sorted_standings, 1):
        matches_played = len(previous_opponents[team])
        opponents = ", ".join(str(o) for o in previous_opponents[team] if o != bye_team)
        print(f"  {rank:2d}. Team {team:2d}: {vp:6.1f} VP ({matches_played} matches)")
        print(f"      Played against: {opponents}")
    
    # Verify all teams played correct number of rounds
    for team in range(1, num_teams + 1):
        assert len(previous_opponents[team]) == num_rounds, \
            f"Team {team} played {len(previous_opponents[team])} matches, expected {num_rounds}"
    
    # Verify no team played the same opponent twice (except bye)
    for team in range(1, num_teams + 1):
        opponents = [o for o in previous_opponents[team] if o != bye_team]
        assert len(opponents) == len(set(opponents)), \
            f"Team {team} played against the same opponent twice!"
    
    print(f"\n{'='*80}")
    print("✓ Tournament completed successfully!")
    print(f"✓ All {num_teams} teams played {num_rounds} rounds")
    print("✓ No rematches occurred")
    print(f"{'='*80}\n")
