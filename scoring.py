import numpy as np
import math
from enum import Enum

class Vul(Enum):
    NONE = 0
    NS = 1
    EW = 2
    ALL = 3

def calculate_bridge_score(result):
    """
    Calculate the score for a bridge contract result.
    
    Args:
        result: A string in format "level+suit declarer vulnerability tricks_made"
                e.g., "3S S m 3" means 3 Spades by South, non-vulnerable, making 3 overtricks
    
    Returns:
        int: The score for the contract
    """
    parts = result.strip().split()
    if len(parts) != 4:
        return 0
    
    contract_str, declarer, vulnerability, tricks_str = parts
    
    # Parse contract
    level = int(contract_str[0])
    suit = contract_str[1:].upper()
    
    # Parse tricks made (overtricks or undertricks)
    tricks_made = int(tricks_str)
    
    # Determine if vulnerable
    vulnerable = vulnerability.lower() in ['v', 'vul']
    
    # Contract made
    if tricks_made >= 0:
        # Base score
        if suit in ['C', 'D']:  # Minor suits
            base_score = level * 20
        elif suit in ['H', 'S']:  # Major suits
            base_score = level * 30
        elif suit == 'NT':  # No Trump
            base_score = level * 30 + 10
        else:
            return 0
        
        # Game bonus
        if base_score >= 100:
            game_bonus = 500 if vulnerable else 300
        else:
            game_bonus = 50
        
        # Slam bonus
        slam_bonus = 0
        if level == 6:  # Small slam
            slam_bonus = 750 if vulnerable else 500
        elif level == 7:  # Grand slam
            slam_bonus = 1500 if vulnerable else 1000
        
        # Overtrick score
        if suit in ['C', 'D']:
            overtrick_value = 20
        elif suit in ['H', 'S', 'NT']:
            overtrick_value = 30
        
        overtrick_score = tricks_made * overtrick_value
        
        total_score = base_score + game_bonus + slam_bonus + overtrick_score
        return total_score
    
    # Contract failed (undertricks)
    else:
        undertricks = abs(tricks_made)
        if not vulnerable:
            penalty = undertricks * 50
        else:
            penalty = undertricks * 100
        return -penalty
    
def calculate_imp(a: int, b: int) -> int:
    """
    Calculate the IMPs (International Match Points) between two scores.
    
    Args:
        a (int): Score of team A
        b (int): Score of team B
    
    Returns:
        int: The IMPs difference
    """
    diff = abs(a - b)
    imp = 0
    
    if diff < 20:
        imp = 0
    elif 20 <= diff <= 40:
        imp = 1
    elif 50 <= diff <= 80:
        imp = 2
    elif 90 <= diff <= 120:
        imp = 3
    elif 130 <= diff <= 160:
        imp = 4
    elif 170 <= diff <= 210:
        imp = 5
    elif 220 <= diff <= 260:
        imp = 6
    elif 270 <= diff <= 310:
        imp = 7
    elif 320 <= diff <= 360:
        imp = 8
    elif 370 <= diff <= 420:
        imp = 9
    elif 430 <= diff <= 490:
        imp = 10
    elif 500 <= diff <= 590:
        imp = 11
    elif 600 <= diff <= 740:
        imp = 12
    elif 750 <= diff <= 890:
        imp = 13
    elif 900 <= diff <= 1090:
        imp = 14
    elif 1100 <= diff <= 1290:
        imp = 15
    elif 1300 <= diff <= 1490:
        imp = 16
    elif 1500 <= diff <= 1740:
        imp = 17
    elif 1750 <= diff <= 1990:
        imp = 18
    elif 2000 <= diff <= 2240:
        imp = 19
    elif 2250 <= diff <= 2490:
        imp = 20
    elif 2500 <= diff <= 2990:
        imp = 21
    elif 3000 <= diff <= 3490:
        imp = 22
    elif 3500 <= diff <= 3990:
        imp = 23
    else:  # 4000+
        imp = 24
    
    return int(imp * np.sign(a - b))

def calculate_vp(a: int, b: int, num_boards: int) -> tuple[float, float]:
    trophy = abs(a - b)
    tau = (1 + math.sqrt(5)) / 2 - 1 # Golden ratio minus 1
    trophy = 3 * trophy / (15 * math.sqrt(num_boards))
    trophy = min(10, 10 * ( tau ** trophy / tau ** 3))
    if a > b:
        return 10 + trophy, 10 - trophy
    else:
        return 10 - trophy, 10 + trophy
    
def calculate_vulnerability(board_number: int) -> Vul:
    board = ((board_number - 1) % 16) + 1
    
    vulnerability_map = {
        1: Vul.NONE,
        2: Vul.NS,
        3: Vul.EW,
        4: Vul.ALL,
        5: Vul.NS,
        6: Vul.EW,
        7: Vul.ALL,
        8: Vul.NONE,
        9: Vul.EW,
        10: Vul.ALL,
        11: Vul.NONE,
        12: Vul.NS,
        13: Vul.ALL,
        14: Vul.NONE,
        15: Vul.NS,
        16: Vul.EW
    }
    
    
    return vulnerability_map[board]