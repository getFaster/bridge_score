import numpy as np
import math
from enum import Enum
import re

class Vul(Enum):
    NONE = 0
    NS = 1
    EW = 2
    ALL = 3

def calculate_bridge_score(result: str) -> int:
    """
    Calculate the score for a bridge contract result.
    
    Args:
        score_input = f"{contract} {vulnerability_str} {result}"
        contract (str): Contract in the format "<level><suit><doubles>"
                        e.g., "4H", "3NTX", "5DX"
        vulnerability_str (str): 'v' for vulnerable, 'n' for not vulnerable
        result >= <level>: level made
        result <= 1: undertricks (negative)    
    
    Returns:
        int: The score for the contract
    """
    parts = result.strip().split()
    if len(parts) != 3:
        assert False, "Invalid input format. Expected format: '<contract> <vulnerability> <tricks made/undertricks>'"
    
    contract_str, vulnerability, tricks_str = parts
    
    # Parse contract
    # Support for doubled (X) and redoubled (XX) contracts
    m = re.match(r"(\d+)(NT|[CDHS])(X{0,2})", contract_str.upper())
    if not m:
        assert False, "Invalid contract format: {}".format(contract_str)
    level = int(m.group(1))
    suit = m.group(2)
    dbl = m.group(3)
    
    # Determine multiplier
    if dbl == 'X':
        multiplier = 2
    elif dbl == 'XX':
        multiplier = 4
    else:
        multiplier = 1
    
    # Parse tricks made (overtricks or undertricks)
    tricks = int(tricks_str)
    assert tricks >= level or tricks <= -1, \
            "Invalid tricks for contract {}: {}".format(contract_str, tricks)

    
    # Determine if vulnerable
    vulnerable = vulnerability.lower() in ['v', 'vul']
        
    # Contract made (tricks_taken is total tricks)
    if tricks >= level:
        # Base score
        base_score = 0
        if suit in ['C', 'D']:  # Minor suits
            base_score = level * 20
        elif suit in ['H', 'S']:  # Major suits
            base_score = level * 30
        elif suit == 'NT':  # No Trump
            base_score = level * 30 + 10
        
        base_score *= multiplier
        # Game bonus
        if base_score >= 100:
            game_bonus = 500 if vulnerable else 300
        else:
            game_bonus = 50

        # Doubled/redoubled insult bonus
        insult_bonus = 0
        if multiplier == 2:
            insult_bonus = 50
        elif multiplier == 4:
            insult_bonus = 100
                
        # Slam bonus
        slam_bonus = 0
        if level == 6:  # Small slam
            slam_bonus = 750 if vulnerable else 500
        elif level == 7:  # Grand slam
            slam_bonus = 1500 if vulnerable else 1000
        
        # Overtrick score
        overtrick_value = 0
        if multiplier == 2:
            overtrick_value = 200 if vulnerable else 100
        elif multiplier == 4:
            overtrick_value = 400 if vulnerable else 200
        elif suit in ['C', 'D']:
            overtrick_value = 20
        elif suit in ['H', 'S', 'NT']:
            overtrick_value = 30
        
        # Calculate overtricks
        overtricks = tricks - level
        assert overtricks >= 0, "Logic error: overtricks should be >= 0 for made contracts"
                
        total_score = base_score + game_bonus + slam_bonus + overtrick_value * overtricks + insult_bonus
        return total_score
    
    # Contract failed (negative means undertricks)
    else:
        undertricks = abs(tricks)
        penalty = 0
        if multiplier == 1:
            # Not doubled
            penalty = undertricks * (100 if vulnerable else 50)
        else:
            # Doubled
            if not vulnerable:
                if undertricks == 1:
                    penalty = 100
                elif undertricks == 2:
                    penalty = 300
                else:  # 3 or more
                    penalty = 500 + (undertricks - 3) * 300
            else:
                if undertricks == 1:
                    penalty = 200
                elif undertricks == 2:
                    penalty = 500
                else:  # 3 or more
                    penalty = 800 + (undertricks - 3) * 300

            if multiplier == 4:
                penalty *= 2

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