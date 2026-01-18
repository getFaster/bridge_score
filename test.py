import pytest
from scoring import calculate_bridge_score


# ==============================================================================
# TESTS FOR calculate_bridge_score
# ==============================================================================

def test_basic_partscores():
    """Test basic partscore contracts without overtricks"""
    # 2C making exactly (level 2) - non-vulnerable
    assert calculate_bridge_score("2C n 2") == 90  # 40 + 50
    # 2D making exactly (level 2) - vulnerable
    assert calculate_bridge_score("2D v 2") == 90  # 40 + 50
    # 2H making exactly (level 2) - non-vulnerable
    assert calculate_bridge_score("2H n 2") == 110  # 60 + 50
    # 2S making exactly (level 2) - vulnerable
    assert calculate_bridge_score("2S v 2") == 110  # 60 + 50
    # 1NT making exactly (level 1) - non-vulnerable
    assert calculate_bridge_score("1NT n 1") == 90  # 40 + 50

def test_game_contracts():
    """Test game contracts making exactly"""
    # 3NT making exactly (level 3) - non-vulnerable
    assert calculate_bridge_score("3NT n 3") == 400  # 100 + 300
    # 3NT making exactly (level 3) - vulnerable
    assert calculate_bridge_score("3NT v 3") == 600  # 100 + 500
    # 4H making exactly (level 4) - non-vulnerable
    assert calculate_bridge_score("4H n 4") == 420  # 120 + 300
    # 4S making exactly (level 4) - vulnerable
    assert calculate_bridge_score("4S v 4") == 620  # 120 + 500
    # 5C making exactly (level 5) - non-vulnerable
    assert calculate_bridge_score("5C n 5") == 400  # 100 + 300
    # 5D making exactly (level 5) - vulnerable
    assert calculate_bridge_score("5D v 5") == 600  # 100 + 500

def test_contracts_with_overtricks():
    """Test contracts with overtricks"""
    # 3NT making 1 overtrick (level 4 reached) - non-vulnerable
    assert calculate_bridge_score("3NT n 4") == 430  # 100 + 300 + 30
    # 4H making 2 overtricks (level 6 reached) - vulnerable
    assert calculate_bridge_score("4H v 6") == 680  # 120 + 500 + 60
    # 1NT making 3 overtricks (level 4 reached) - non-vulnerable
    assert calculate_bridge_score("1NT n 4") == 180  # 40 + 50 + 90
    # 2C making 5 overtricks (level 7 reached) - vulnerable
    assert calculate_bridge_score("2C v 7") == 190  # 40 + 50 + 100

def test_small_slams():
    """Test small slam contracts (6-level)"""
    # 6NT making exactly (level 6) - non-vulnerable
    assert calculate_bridge_score("6NT n 6") == 990  # 190 + 300 + 500
    # 6NT making exactly (level 6) - vulnerable
    assert calculate_bridge_score("6NT v 6") == 1440  # 190 + 500 + 750
    # 6H making 1 overtrick (level 7) - non-vulnerable
    assert calculate_bridge_score("6H n 7") == 1010  # 180 + 300 + 500 + 30
    # 6D making 1 overtrick (level 7) - vulnerable
    assert calculate_bridge_score("6D v 7") == 1390  # 120 + 500 + 750 + 20

def test_grand_slams():
    """Test grand slam contracts (7-level)"""
    # 7NT making exactly (level 7) - non-vulnerable
    assert calculate_bridge_score("7NT n 7") == 1520  # 220 + 300 + 1000
    # 7NT making exactly (level 7) - vulnerable
    assert calculate_bridge_score("7NT v 7") == 2220  # 220 + 500 + 1500
    # 7S making exactly (level 7) - non-vulnerable
    assert calculate_bridge_score("7S n 7") == 1510  # 210 + 300 + 1000
    # 7C making exactly (level 7) - vulnerable
    assert calculate_bridge_score("7C v 7") == 2140  # 140 + 500 + 1500

def test_contracts_down():
    """Test contracts that fail (undertricks)"""
    # 3NT down 1 - non-vulnerable
    assert calculate_bridge_score("3NT n -1") == -50
    # 4H down 1 - vulnerable
    assert calculate_bridge_score("4H v -1") == -100
    # 6NT down 2 - non-vulnerable
    assert calculate_bridge_score("6NT n -2") == -100
    # 7S down 3 - vulnerable
    assert calculate_bridge_score("7S v -3") == -300
    # 5D down 5 - vulnerable
    assert calculate_bridge_score("5D v -5") == -500

def test_doubled_contracts_made():
    """Test doubled contracts that make"""
    # 3NTX making exactly (level 3) - non-vulnerable
    assert calculate_bridge_score("3NTX n 3") == 550  # 200 + 300 + 50
    # 4HX making exactly (level 4) - vulnerable
    assert calculate_bridge_score("4HX v 4") == 790  # 240 + 500 + 50
    # 2CX making 1 overtrick (level 3) - non-vulnerable
    assert calculate_bridge_score("2CX n 3") == 280  # 80 + 50 + 50 + 100 (1 overtrick)
    # 3NTX making 2 overtricks (level 5) - vulnerable
    assert calculate_bridge_score("3NTX v 5") == 1150  # 200 + 300 + 50 + 400 (2 overtricks)

def test_redoubled_contracts_made():
    """Test redoubled contracts that make"""
    # 3NTXX making exactly (level 3) - non-vulnerable
    assert calculate_bridge_score("3NTXX n 3") == 800  # 400 + 300 + 100
    # 4HXX making exactly (level 4) - vulnerable
    assert calculate_bridge_score("4HXX v 4") == 1080  # 480 + 500 + 100
    # 2CXX making 1 overtrick (level 3) - non-vulnerable
    assert calculate_bridge_score("2CXX n 3") == 760  # 160 + 300 + 100 + 200 (1 overtrick)
    # 3NTXX making 2 overtricks (level 5) - vulnerable
    assert calculate_bridge_score("3NTXX v 5") == 1800

def test_doubled_contracts_down():
    """Test doubled contracts that fail"""
    # 3NTX down 1 - non-vulnerable
    assert calculate_bridge_score("3NTX n -1") == -100
    # 4HX down 1 - vulnerable
    assert calculate_bridge_score("4HX v -1") == -200
    # 6NTX down 2 - non-vulnerable
    assert calculate_bridge_score("6NTX n -2") == -300
    # 7SX down 2 - vulnerable
    assert calculate_bridge_score("7SX v -2") == -500
    # 5DX down 3 - non-vulnerable
    assert calculate_bridge_score("5DX n -3") == -500
    # 6CX down 3 - vulnerable
    assert calculate_bridge_score("6CX v -3") == -800
    # 7NTX down 4 - non-vulnerable
    assert calculate_bridge_score("7NTX n -4") == -800  # 500 + 300
    # 7NTX down 4 - vulnerable
    assert calculate_bridge_score("7NTX v -4") == -1100  # 800 + 300

def test_redoubled_contracts_down():
    """Test redoubled contracts that fail"""
    # 3NTXX down 1 - non-vulnerable
    assert calculate_bridge_score("3NTXX n -1") == -200
    # 4HXX down 1 - vulnerable
    assert calculate_bridge_score("4HXX v -1") == -400
    # 6NTXX down 2 - non-vulnerable
    assert calculate_bridge_score("6NTXX n -2") == -600
    # 7SXX down 2 - vulnerable
    assert calculate_bridge_score("7SXX v -2") == -1000
    # 5DXX down 3 - non-vulnerable
    assert calculate_bridge_score("5DXX n -3") == -1000
    # 6CXX down 3 - vulnerable
    assert calculate_bridge_score("6CXX v -3") == -1600

def test_doubled_slams():
    """Test doubled and redoubled slams"""
    # 6NTX making exactly (level 6) - non-vulnerable
    assert calculate_bridge_score("6NTX n 6") == 1230
    # 6HX making exactly (level 6) - vulnerable
    assert calculate_bridge_score("6HX v 6") == 1660
    # 7NTXX making exactly (level 7) - vulnerable
    assert calculate_bridge_score("7NTXX v 7") == 2980  # 880 + 500 + 1500 + 100

def test_invalid_inputs():
    """Test that invalid inputs raise assertions"""
    # Invalid number of parts
    with pytest.raises(AssertionError):
        calculate_bridge_score("4H n")
    
    with pytest.raises(AssertionError):
        calculate_bridge_score("4H n 0 extra")
    
    # Invalid contract format
    with pytest.raises(AssertionError):
        calculate_bridge_score("8H n 0")  # Level 8 doesn't exist but will parse
    
    with pytest.raises(AssertionError):
        calculate_bridge_score("H4 n 0")  # Wrong order
    
    with pytest.raises(AssertionError):
        calculate_bridge_score("4Z n 0")  # Invalid suit
    
    # Note: We don't validate trick counts in the new version
    # since we calculate overtricks from total tricks

def test_edge_cases():
    """Test edge cases and boundary conditions"""
    # Maximum overtricks - 1C making level 7 (6 overtricks)
    assert calculate_bridge_score("1C n 7") > 0
    
    # Maximum undertricks
    assert calculate_bridge_score("7NT v -13") < 0  # Down 13 tricks
    
    # All suits work
    for suit in ['C', 'D', 'H', 'S']:
        assert calculate_bridge_score(f"3{suit} n 3") > 0
    
    # NT works
    assert calculate_bridge_score("3NT n 3") == 400
    
    # Lowercase suit should work (gets converted to uppercase)
    assert calculate_bridge_score("3nt n 3") == 400
    assert calculate_bridge_score("4h n 4") == 420


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
