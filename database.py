import sqlite3
from datetime import datetime


def initialize_database(conn):
    """Initialize database schema and perform migrations if needed."""
    cursor = conn.cursor()
    
    # Create basic scores table
    cursor.execute('''CREATE TABLE IF NOT EXISTS scores
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create session tokens table
    cursor.execute('''CREATE TABLE IF NOT EXISTS session_tokens
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token TEXT UNIQUE NOT NULL,
                        tournament_id INTEGER NOT NULL,
                        table_id INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NOT NULL)''')
    
    # Check if tournaments table exists and migrate if needed
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tournaments'")
    table_exists = cursor.fetchone()
    
    if table_exists:
        # Check if old schema exists
        cursor.execute("PRAGMA table_info(tournaments)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'tournament_form' not in columns:
            # Migrate old schema to new schema
            print("Migrating tournaments table to new schema...")
            cursor.execute("ALTER TABLE tournaments RENAME TO tournaments_old")
            cursor.execute('''CREATE TABLE tournaments
                                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                tournament_name TEXT NOT NULL,
                                tournament_form TEXT NOT NULL,
                                num_entries INTEGER NOT NULL,
                                boards_per_round INTEGER NOT NULL,
                                scoring_method TEXT NOT NULL,
                                movement_type TEXT NOT NULL,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            # Copy old data if any exists (default to 'pairs' for old tournaments)
            cursor.execute("""INSERT INTO tournaments 
                                (id, tournament_name, tournament_form, num_entries, 
                                boards_per_round, scoring_method, movement_type, created_at)
                                SELECT id, tournament_name, 'pairs', 
                                COALESCE(num_pairs, num_entries, 8),
                                boards_per_round, scoring_method, movement_type, created_at
                                FROM tournaments_old""")
            cursor.execute("DROP TABLE tournaments_old")
            print("Migration complete!")
    else:
        # Create new table
        cursor.execute('''CREATE TABLE tournaments
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            tournament_name TEXT NOT NULL,
                            tournament_form TEXT NOT NULL,
                            num_entries INTEGER NOT NULL,
                            boards_per_round INTEGER NOT NULL,
                            scoring_method TEXT NOT NULL,
                            movement_type TEXT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create rounds table
    cursor.execute('''CREATE TABLE IF NOT EXISTS rounds
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        table_number INTEGER NOT NULL,
                        entry1_id INTEGER NOT NULL,
                        entry2_id INTEGER NOT NULL,
                        boards TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    
    # Create board results table
    cursor.execute('''CREATE TABLE IF NOT EXISTS board_results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER,
                        table_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        board_number INTEGER NOT NULL,
                        contract TEXT NOT NULL,
                        declarer TEXT NOT NULL,
                        vulnerable INTEGER NOT NULL,
                        result INTEGER NOT NULL,
                        score INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    
    # Create match results table
    cursor.execute('''CREATE TABLE IF NOT EXISTS match_results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER,
                        table_id INTEGER,
                        round_number INTEGER,
                        total_score INTEGER,
                        opponent_score INTEGER,
                        imps INTEGER,
                        vp REAL,
                        UNIQUE(tournament_id, table_id, round_number))''')
    
    # Create tournament settings table
    cursor.execute('''CREATE TABLE IF NOT EXISTS tournament_settings
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER UNIQUE,
                        current_round INTEGER DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    
    # Create table passwords table
    cursor.execute('''CREATE TABLE IF NOT EXISTS table_passwords
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER,
                        table_id INTEGER,
                        password TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(tournament_id, table_id),
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    
    conn.commit()


def calculate_match_result(cursor, conn, tournament_id, table1, table2, round_number, boards_per_round):
    """Calculate IMPs and VPs for a completed match."""
    from scoring import calculate_imp, calculate_vp
    
    # Get boards for this match
    cursor.execute("SELECT boards FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                   (tournament_id, table1, round_number))
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
        cursor.execute("SELECT score FROM board_results WHERE tournament_id = ? AND table_id = ? AND round_number = ? AND board_number = ?",
                       (tournament_id, table1, round_number, board))
        result1 = cursor.fetchone()
        if result1:
            table1_scores[board] = result1[0]
        
        cursor.execute("SELECT score FROM board_results WHERE tournament_id = ? AND table_id = ? AND round_number = ? AND board_number = ?",
                       (tournament_id, table2, round_number, board))
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
                      WHERE tournament_id = ? AND table_number = ? AND round_number = ?""",
                   (tournament_id, table1, round_number))
    cursor.execute("""UPDATE rounds 
                      SET status = 'complete_with_result'
                      WHERE tournament_id = ? AND table_number = ? AND round_number = ?""",
                   (tournament_id, table2, round_number))
    
    # Calculate total scores
    table1_total = sum(table1_scores.values())
    table2_total = sum(table2_scores.values())
    
    # Store results for both tables
    cursor.execute("""INSERT OR REPLACE INTO match_results 
                      (tournament_id, table_id, round_number, total_score, opponent_score, imps, vp)
                      VALUES (?, ?, ?, ?, ?, ?, ?)""",
                   (tournament_id, table1, round_number, table1_total, table2_total, total_imps, vp1))
    cursor.execute("""INSERT OR REPLACE INTO match_results 
                      (tournament_id, table_id, round_number, total_score, opponent_score, imps, vp)
                      VALUES (?, ?, ?, ?, ?, ?, ?)""",
                   (tournament_id, table2, round_number, table2_total, table1_total, -total_imps, vp2))
    
    conn.commit()
    print(f"Match result calculated: Table {table1} vs {table2}, IMPs: {total_imps}, VPs: {vp1:.2f} - {vp2:.2f}")
