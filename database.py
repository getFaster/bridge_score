import sqlite3
import os

MASTER_DB_NAME = 'tournaments.db'

def get_master_conn():
    conn = sqlite3.connect(MASTER_DB_NAME, check_same_thread=False)
    return conn

def get_tournament_conn(tournament_id):
    db_name = f'tournament_{tournament_id}.db'
    conn = sqlite3.connect(db_name, check_same_thread=False)
    return conn

def init_master_db():
    conn = get_master_conn()
    cursor = conn.cursor()
    
    # Create tournaments table
    cursor.execute('''CREATE TABLE IF NOT EXISTS tournaments
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_name TEXT NOT NULL,
                        tournament_form TEXT NOT NULL,
                        num_entries INTEGER NOT NULL,
                        boards_per_round INTEGER NOT NULL,
                        scoring_method TEXT NOT NULL,
                        movement_type TEXT NOT NULL,
                        director_password TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                        
    # Create session tokens table (centralized auth)
    cursor.execute('''CREATE TABLE IF NOT EXISTS session_tokens
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token TEXT UNIQUE NOT NULL,
                        tournament_id INTEGER NOT NULL,
                        table_id INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NOT NULL)''')
    
    conn.commit()
    conn.close()

def init_tournament_db(tournament_id):
    conn = get_tournament_conn(tournament_id)
    cursor = conn.cursor()
    
    # Create basic scores table
    cursor.execute('''CREATE TABLE IF NOT EXISTS scores
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create rounds table
    cursor.execute('''CREATE TABLE IF NOT EXISTS rounds
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        round_number INTEGER NOT NULL,
                        table_id INTEGER NOT NULL,
                        entry1_id INTEGER NOT NULL,
                        entry2_id INTEGER NOT NULL,
                        boards TEXT NOT NULL,
                        status TEXT DEFAULT 'pending')''')
    
    # Create board results table
    cursor.execute('''CREATE TABLE IF NOT EXISTS board_results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        board_number INTEGER NOT NULL,
                        contract TEXT NOT NULL,
                        declarer TEXT NOT NULL,
                        vulnerable INTEGER NOT NULL,
                        result INTEGER NOT NULL,
                        score INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create match results table
    cursor.execute('''CREATE TABLE IF NOT EXISTS match_results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_id INTEGER,
                        round_number INTEGER,
                        total_score INTEGER,
                        opponent_score INTEGER,
                        imps INTEGER,
                        vp REAL,
                        UNIQUE(table_id, round_number))''')
    
    # Create tournament settings table
    cursor.execute('''CREATE TABLE IF NOT EXISTS tournament_settings
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        current_round INTEGER DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create table passwords table
    cursor.execute('''CREATE TABLE IF NOT EXISTS table_passwords
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        table_id INTEGER,
                        password TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(table_id))''')
    
    conn.commit()
    conn.close()

def calculate_match_result(cursor, conn, tournament_id, table1, table2, round_number, boards_per_round):
    """Calculate IMPs and VPs for a completed match."""
    from scoring import calculate_imp, calculate_vp
    
    # Get boards for this match
    cursor.execute("SELECT boards FROM rounds WHERE table_id = ? AND round_number = ?",
                   (table1, round_number))
    boards_data = cursor.fetchone()
    if not boards_data:
        return
    
    boards_str = boards_data[0]
    if '-' in boards_str:
        start, end = map(int, boards_str.split('-'))
        board_numbers = list(range(start, end + 1))
    else:
        board_numbers = [int(boards_str)]
    
    # Get results from both tables
    table1_scores = {}
    table2_scores = {}
    
    for board in board_numbers:
        cursor.execute("SELECT score FROM board_results WHERE table_id = ? AND round_number = ? AND board_number = ?",
                       (table1, round_number, board))
        result1 = cursor.fetchone()
        if result1:
            table1_scores[board] = result1[0]
        
        cursor.execute("SELECT score FROM board_results WHERE table_id = ? AND round_number = ? AND board_number = ?",
                       (table2, round_number, board))
        result2 = cursor.fetchone()
        if result2:
            table2_scores[board] = result2[0]
    
    # Calculate total IMPs
    total_imps = 0
    for board in board_numbers:
        if board in table1_scores and board in table2_scores:
            imp = calculate_imp(table1_scores[board], table2_scores[board])
            total_imps += imp
    
    # Calculate VPs
    vp1, vp2 = calculate_vp(total_imps, 0, boards_per_round)
    
    # Store match results in rounds table
    cursor.execute("""UPDATE rounds 
                      SET status = 'complete_with_result'
                      WHERE table_id = ? AND round_number = ?""",
                   (table1, round_number))
    cursor.execute("""UPDATE rounds 
                      SET status = 'complete_with_result'
                      WHERE table_id = ? AND round_number = ?""",
                   (table2, round_number))
    
    # Calculate total scores
    table1_total = sum(table1_scores.values())
    table2_total = sum(table2_scores.values())
    
    # Store results for both tables
    cursor.execute("""INSERT OR REPLACE INTO match_results 
                      (table_id, round_number, total_score, opponent_score, imps, vp)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (table1, round_number, table1_total, table2_total, total_imps, vp1))
    cursor.execute("""INSERT OR REPLACE INTO match_results 
                      (table_id, round_number, total_score, opponent_score, imps, vp)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (table2, round_number, table2_total, table1_total, -total_imps, vp2))
    
    conn.commit()
    print(f"Match result calculated: Table {table1} vs {table2}, IMPs: {total_imps}, VPs: {vp1:.2f} - {vp2:.2f}")
