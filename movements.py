"""
Tournament movements and pairing logic for bridge competitions.
Handles round robin, Swiss system, and table assignments.
"""

from typing import List, Tuple, Dict
import random
from scipy.optimize import milp, Bounds, LinearConstraint


def assign_table_pairs(team_ids: List[int], round_number: int = 1, bye_team: int = None) -> List[Tuple[int, str, int, int]]:
    """
    Assign match pairs for duplicate bridge (open and closed rooms).
    Each match requires two tables with teams swapping NS/EW positions.
    
    Args:
        team_ids: List of team IDs to be paired (should be even number)
        round_number: Current round number (for tracking)
        bye_team: Optional team ID that represents a bye (no tables assigned for bye matches)
    
    Returns:
        List of tuples: (table_number, room, team_ns, team_ew)
        Excludes matches involving the bye team.
        
    Example:
        >>> assign_table_pairs([1, 2, 3, 4])
        [(1, 'open', 1, 2), (1, 'closed', 2, 1), (2, 'open', 3, 4), (2, 'closed', 4, 3)]
        >>> assign_table_pairs([1, 2, 3, 0], bye_team=0)
        [(1, 'open', 1, 2), (1, 'closed', 2, 1)]
    """
    if len(team_ids) < 2:
        raise ValueError("Need at least 2 teams to create pairings")
    
    if len(team_ids) % 2 != 0:
        raise ValueError("Number of teams must be even. Use bye_team parameter for odd team counts.")
    
    teams = team_ids.copy()
    
    # Create pairings with open and closed rooms
    pairings = []
    table_number = 1
    
    for i in range(0, len(teams), 2):
        team1 = teams[i]
        team2 = teams[i + 1]
        
        # Skip if either team is the bye team
        if (bye_team is not None and (team1 == bye_team or team2 == bye_team)):
            continue
        
        # Open room: Team1 (NS) vs Team2 (EW)
        pairings.append((table_number, 'open', team1, team2))
        # Closed room: Team2 (NS) vs Team1 (EW)
        pairings.append((table_number, 'closed', team2, team1))
        table_number += 1
    
    return pairings


def round_robin(num_teams: int, bye_team: int = None) -> List[List[Tuple[int, int]]]:
    """
    Generate a complete round robin schedule where each team plays every other team exactly once.
    Uses the circle method (rotating algorithm).
    Returns only the match pairings without room/table assignments.
    
    Args:
        num_teams: Number of teams in the tournament (if odd, bye_team will be added)
        bye_team: Optional bye team ID (default: num_teams + 1 for odd num_teams).
    
    Returns:
        List of rounds, where each round is a list of (team1, team2) tuples representing matches.
        Teams are numbered 1 to num_teams.
        Matches with bye_team are included in the schedule but will be filtered out when assigning tables.
        
    Example:
        >>> round_robin(4)
        [
            [(1, 2), (3, 4)],      # Round 1: 2 matches
            [(1, 3), (2, 4)],      # Round 2: 2 matches
            [(1, 4), (2, 3)]       # Round 3: 2 matches
        ]
        >>> round_robin(3)
        [
            [(1, 2), (3, 4)],      # Round 1: Team 3 has bye (4 is bye team)
            [(1, 3), (2, 4)],      # Round 2: Team 2 has bye
            [(1, 4), (2, 3)]       # Round 3: Team 1 has bye
        ]
    """
    if num_teams < 2:
        raise ValueError("Need at least 2 teams for round robin")
    
    teams = list(range(1, num_teams + 1))
    
    # If odd number of teams, add bye team
    if num_teams % 2 == 1:
        if bye_team is None:
            bye_team = num_teams + 1
        teams.append(bye_team)
    
    num_rounds = len(teams) - 1
    half = len(teams) // 2
    
    schedule = []
    
    for round_num in range(num_rounds):
        round_pairings = []
        
        for i in range(half):
            team1 = teams[i]
            team2 = teams[len(teams) - 1 - i]
            round_pairings.append((team1, team2))
        
        schedule.append(round_pairings)
        
        # Rotate teams (keep first team fixed, rotate others)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    
    return schedule


def round_robin_with_tables(num_teams: int, bye_team: int = None) -> List[List[Tuple[int, str, int, int]]]:
    """
    Generate a complete round robin schedule with duplicate bridge table assignments.
    Each match creates two tables (open and closed rooms) with teams swapping positions.
    Matches involving the bye team do not get table assignments.
    
    Args:
        num_teams: Number of teams in the tournament
        bye_team: Optional bye team ID (default: num_teams + 1 for odd num_teams).
    
    Returns:
        List of rounds, where each round is a list of (table_number, room, team_ns, team_ew) tuples.
        Bye matches are excluded from table assignments.
        
    Example:
        >>> round_robin_with_tables(4)
        [
            # Round 1: 2 matches = 4 tables
            [(1, 'open', 1, 2), (1, 'closed', 2, 1), (2, 'open', 3, 4), (2, 'closed', 4, 3)],
            # Round 2: 2 matches = 4 tables
            [(1, 'open', 1, 3), (1, 'closed', 3, 1), (2, 'open', 2, 4), (2, 'closed', 4, 2)],
            # Round 3: 2 matches = 4 tables
            [(1, 'open', 1, 4), (1, 'closed', 4, 1), (2, 'open', 2, 3), (2, 'closed', 3, 2)]
        ]
        >>> round_robin_with_tables(3)
        [
            # Round 1: 1 match = 2 tables (Team 3 has bye, 4 is bye team)
            [(1, 'open', 1, 2), (1, 'closed', 2, 1)],
            # Round 2: 1 match = 2 tables (Team 2 has bye)
            [(1, 'open', 1, 3), (1, 'closed', 3, 1)],
            # Round 3: 1 match = 2 tables (Team 1 has bye)
            [(1, 'open', 2, 3), (1, 'closed', 3, 2)]
        ]
    """
    schedule = round_robin(num_teams, bye_team)
    
    # Determine bye_team value if not specified
    if num_teams % 2 == 1 and bye_team is None:
        bye_team = num_teams + 1
    
    # Add table numbers and create open/closed rooms, excluding bye matches
    schedule_with_tables = []
    for round_pairings in schedule:
        round_with_tables = []
        table_num = 1
        for (team1, team2) in round_pairings:
            # Skip if either team is the bye team
            if bye_team is not None and (team1 == bye_team or team2 == bye_team):
                continue
            
            # Open room: Team1 (NS) vs Team2 (EW)
            round_with_tables.append((table_num, 'open', team1, team2))
            # Closed room: Team2 (NS) vs Team1 (EW)
            round_with_tables.append((table_num, 'closed', team2, team1))
            table_num += 1
        schedule_with_tables.append(round_with_tables)
    
    return schedule_with_tables


def swiss_pairing(
    team_ids: List[int],
    standings: Dict[int, float],
    previous_opponents: Dict[int, List[int]],
    round_number: int,
    bye_team: int = None
) -> List[Tuple[int, str, int, int]]:
    """
    Generate Swiss system pairings based on current standings using MILP optimization.
    Teams with similar scores are paired together, avoiding rematches.
    Creates duplicate bridge tables (open and closed rooms).
    
    The bye will also have its own VP score, so it can be included in standings.
    
    Args:
        team_ids: List of all team IDs in the tournament (should be even, or include bye_team)
        standings: Dictionary mapping team_id to current VP (Victory Points)
        previous_opponents: Dictionary mapping team_id to list of team_ids they've already played
        round_number: Current round number
        bye_team: Optional bye team ID. Matches with bye team won't get table assignments.
    
    Returns:
        List of tuples: (table_number, room, team_ns, team_ew)
        Excludes matches involving bye_team.
    """
    if len(team_ids) < 2:
        raise ValueError("Need at least 2 teams for Swiss pairing")
    
    if len(team_ids) % 2 != 0:
        raise ValueError("Number of teams must be even. Use bye_team parameter for odd team counts.")
    
    import numpy as np
    
    n = len(team_ids)
    num_pairs = n * (n - 1) // 2
    
    # Create VP array sorted by team_ids
    vps = [standings.get(team_id, 0) for team_id in team_ids]
    
    # Build history set of (i, j) where i and j are indices in team_ids
    team_to_idx = {team_id: idx for idx, team_id in enumerate(team_ids)}
    history = set()
    for team_id, opponents in previous_opponents.items():
        if team_id in team_to_idx:
            i = team_to_idx[team_id]
            for opp_id in opponents:
                if opp_id in team_to_idx:
                    j = team_to_idx[opp_id]
                    if i < j:
                        history.add((i, j))
                    else:
                        history.add((j, i))
    
    # Map (i, j) pairs to indices in the x vector
    pair_to_idx = {}
    idx_to_pair = []
    curr = 0
    for i in range(n):
        for j in range(i + 1, n):
            pair_to_idx[(i, j)] = curr
            idx_to_pair.append((i, j))
            curr += 1

    # 1. Objective Function (Costs)
    # Minimize the square of VP differences
    costs = np.zeros(num_pairs)
    huge_penalty = 1e6 
    
    for idx, (i, j) in enumerate(idx_to_pair):
        diff = (vps[i] - vps[j])**2
        # If they've played before, add the penalty
        if (i, j) in history or (j, i) in history:
            costs[idx] = huge_penalty
        else:
            costs[idx] = diff

    # 2. Constraints: Each team appears exactly once
    # A * x = 1
    A = np.zeros((n, num_pairs))
    for idx, (i, j) in enumerate(idx_to_pair):
        A[i, idx] = 1
        A[j, idx] = 1
    
    constraints = LinearConstraint(A, lb=1, ub=1)
    
    # 3. Integrality (x must be 0 or 1)
    integrality = np.ones(num_pairs) # 1 means integer constraint
    bounds = Bounds(0, 1)

    res = milp(c=costs, constraints=constraints, integrality=integrality, bounds=bounds)

    if not res.success:
        # Fallback to greedy approach
        return _greedy_swiss_pairing(team_ids, standings, previous_opponents, bye_team)
    
    # Extract matches from result
    matches = [idx_to_pair[i] for i, val in enumerate(res.x) if val > 0.5]
    
    # Sort matches by VP sum (descending) for table assignment
    # Higher VP sum gets lower table number
    matches_with_vp = []
    for (i, j) in matches:
        team1 = team_ids[i]
        team2 = team_ids[j]
        
        # Skip if either team is the bye team
        if bye_team is not None and (team1 == bye_team or team2 == bye_team):
            continue
        
        vp_sum = standings.get(team1, 0) + standings.get(team2, 0)
        matches_with_vp.append((vp_sum, i, j))
    
    # Sort by VP sum descending
    matches_with_vp.sort(reverse=True)
    
    # Convert index pairs back to team IDs and create table pairings
    pairings = []
    table_number = 1
    
    for (vp_sum, i, j) in matches_with_vp:
        team1 = team_ids[i]
        team2 = team_ids[j]
        
        # Open room: Team1 (NS) vs Team2 (EW)
        pairings.append((table_number, 'open', team1, team2))
        # Closed room: Team2 (NS) vs Team1 (EW)
        pairings.append((table_number, 'closed', team2, team1))
        table_number += 1
    
    return pairings


def _greedy_swiss_pairing(
    team_ids: List[int],
    standings: Dict[int, float],
    previous_opponents: Dict[int, List[int]],
    bye_team: int = None
) -> List[Tuple[int, str, int, int]]:
    """
    Greedy fallback for Swiss pairing when MILP fails.
    """
    # Sort teams by standings (highest first)
    sorted_teams = sorted(team_ids, key=lambda x: standings.get(x, 0), reverse=True)
    
    pairings = []
    table_number = 1
    paired = set()
    
    for team1 in sorted_teams:
        if team1 in paired:
            continue
        
        # Find best opponent for team1
        team1_opponents = previous_opponents.get(team1, [])
        
        # Try to pair with closest-ranked team that hasn't been played
        for team2 in sorted_teams:
            if team2 == team1 or team2 in paired:
                continue
            
            # Check if they haven't played before
            if team2 not in team1_opponents:
                # Skip if either team is the bye team
                if bye_team is not None and (team1 == bye_team or team2 == bye_team):
                    paired.add(team1)
                    paired.add(team2)
                    break
                
                # Open room: Team1 (NS) vs Team2 (EW)
                pairings.append((table_number, 'open', team1, team2))
                # Closed room: Team2 (NS) vs Team1 (EW)
                pairings.append((table_number, 'closed', team2, team1))
                paired.add(team1)
                paired.add(team2)
                table_number += 1
                break
        else:
            # No valid opponent found (all have been played), pair with closest anyway
            for team2 in sorted_teams:
                if team2 == team1 or team2 in paired:
                    continue
                
                # Skip if either team is the bye team
                if bye_team is not None and (team1 == bye_team or team2 == bye_team):
                    paired.add(team1)
                    paired.add(team2)
                    break
                
                # Open room: Team1 (NS) vs Team2 (EW)
                pairings.append((table_number, 'open', team1, team2))
                # Closed room: Team2 (NS) vs Team1 (EW)
                pairings.append((table_number, 'closed', team2, team1))
                paired.add(team1)
                paired.add(team2)
                table_number += 1
                break
    
    return pairings




def knockout_bracket(team_ids: List[int], seeded: bool = False) -> List[List[Tuple[int, int, int]]]:
    """
    Generate a single-elimination knockout bracket.
    
    Args:
        team_ids: List of team IDs (should be power of 2 for perfect bracket)
        seeded: If True, pair 1 vs N, 2 vs N-1, etc. Otherwise random.
    
    Returns:
        List of rounds, where each round contains table pairings.
        
    Example:
        >>> knockout_bracket([1, 2, 3, 4], seeded=True)
        [
            [(1, 1, 4), (2, 2, 3)],      # Semi-finals
            [(1, 1, 2)]                   # Final (winners of semi-finals)
        ]
    """
    if len(team_ids) < 2:
        raise ValueError("Need at least 2 teams for knockout")
    
    import math
    num_teams = len(team_ids)
    
    # Check if power of 2
    if num_teams & (num_teams - 1) != 0:
        # Not a power of 2, pad with byes
        next_power = 2 ** math.ceil(math.log2(num_teams))
        # For simplicity, just raise error
        raise ValueError(f"Knockout requires power of 2 teams. Got {num_teams}, need {next_power}")
    
    teams = team_ids.copy()
    
    if seeded:
        # Seed pairing: 1 vs N, 2 vs N-1, etc.
        pass
    else:
        # Random bracket
        random.shuffle(teams)
    
    rounds = []
    current_round = teams
    
    while len(current_round) > 1:
        round_pairings = []
        next_round = []
        table_num = 1
        
        for i in range(0, len(current_round), 2):
            team1 = current_round[i]
            team2 = current_round[i + 1]
            round_pairings.append((table_num, team1, team2))
            # For now, just use team1 as placeholder winner
            next_round.append(team1)
            table_num += 1
        
        rounds.append(round_pairings)
        current_round = next_round
    
    return rounds


def mitchell_movement(num_pairs: int, num_rounds: int = None) -> Dict:
    """
    Generate a Mitchell movement for pairs.
    In Mitchell movement, pairs are divided into North-South and East-West.
    NS pairs stay at tables, EW pairs move.
    
    Args:
        num_pairs: Total number of pairs (must be even)
        num_rounds: Number of rounds (default: num_pairs // 2)
    
    Returns:
        Dictionary with movement information
    """
    if num_pairs % 2 != 0:
        raise ValueError("Mitchell movement requires even number of pairs")
    
    if num_rounds is None:
        num_rounds = num_pairs // 2
    
    num_tables = num_pairs // 2
    
    # NS pairs: 1 to num_tables (stay at their table)
    # EW pairs: num_tables+1 to num_pairs (move each round)
    
    movement = {
        'type': 'mitchell',
        'num_tables': num_tables,
        'num_rounds': num_rounds,
        'rounds': []
    }
    
    for round_num in range(1, num_rounds + 1):
        round_data = []
        for table in range(1, num_tables + 1):
            ns_pair = table
            # EW pairs rotate
            ew_pair = num_tables + ((table - 1 + round_num - 1) % num_tables) + 1
            round_data.append({
                'table': table,
                'ns_pair': ns_pair,
                'ew_pair': ew_pair
            })
        movement['rounds'].append(round_data)
    
    return movement


def howell_movement(num_pairs: int) -> Dict:
    """
    Generate a Howell movement for pairs.
    In Howell movement, all pairs play against all other pairs (round robin).
    This is more complex and typically uses pre-computed schedules.
    
    Args:
        num_pairs: Number of pairs
    
    Returns:
        Dictionary with movement information
    """
    # For simplicity, implement as round robin with table assignments
    num_rounds = num_pairs - 1 if num_pairs % 2 == 0 else num_pairs
    
    schedule = round_robin(num_pairs)
    
    movement = {
        'type': 'howell',
        'num_pairs': num_pairs,
        'num_rounds': len(schedule),
        'rounds': []
    }
    
    for round_num, round_pairings in enumerate(schedule, 1):
        round_data = []
        for table_num, (pair1, pair2) in enumerate(round_pairings, 1):
            round_data.append({
                'table': table_num,
                'ns_pair': pair1,
                'ew_pair': pair2
            })
        movement['rounds'].append(round_data)
    
    return movement


if __name__ == '__main__':
    # Test the functions
    print("=== Round Robin Test (4 teams) ===")
    schedule = round_robin_with_tables(4)
    for round_num, round_pairings in enumerate(schedule, 1):
        print(f"\nRound {round_num}:")
        for table, room, team_ns, team_ew in round_pairings:
            print(f"  Table {table} ({room:6s}): Team {team_ns} (NS) vs Team {team_ew} (EW)")
    
    print("\n\n=== Round Robin Test (5 teams with bye) ===")
    schedule = round_robin_with_tables(5)
    for round_num, round_pairings in enumerate(schedule, 1):
        print(f"\nRound {round_num}:")
        if not round_pairings:
            print("  (All teams have bye)")
        for table, room, team_ns, team_ew in round_pairings:
            print(f"  Table {table} ({room:6s}): Team {team_ns} (NS) vs Team {team_ew} (EW)")
        # Show which team has bye
        all_teams = {1, 2, 3, 4, 5, 6}
        playing_teams = {team_ns for _, _, team_ns, _ in round_pairings} | {team_ew for _, _, _, team_ew in round_pairings}
        bye_teams = all_teams - playing_teams - {6}  # 6 is the bye team ID
        if bye_teams:
            print(f"  Team {list(bye_teams)[0]} has bye this round")
    
    print("\n=== Mitchell Movement Test (8 pairs) ===")
    movement = mitchell_movement(8, num_rounds=4)
    for round_num, round_data in enumerate(movement['rounds'], 1):
        print(f"Round {round_num}:")
        for table_data in round_data:
            print(f"  Table {table_data['table']}: NS Pair {table_data['ns_pair']} vs EW Pair {table_data['ew_pair']}")
