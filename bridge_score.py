from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi import Request
import json
import sqlite3
from contextlib import asynccontextmanager
import uvicorn
from scoring import calculate_bridge_score, calculate_vulnerability, Vul, calculate_imp, calculate_vp
from movements import round_robin, assign_table_pairs, swiss_pairing
import secrets
from datetime import datetime, timedelta

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    app.state.conn = sqlite3.connect('bridge_scores.db', check_same_thread=False)
    app.state.cursor = app.state.conn.cursor()
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS scores
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create session tokens table
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS session_tokens
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token TEXT UNIQUE NOT NULL,
                        tournament_id INTEGER NOT NULL,
                        table_id INTEGER NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at DATETIME NOT NULL)''')
    
    # Check if tournaments table exists and migrate if needed
    app.state.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tournaments'")
    table_exists = app.state.cursor.fetchone()
    
    if table_exists:
        # Check if old schema exists
        app.state.cursor.execute("PRAGMA table_info(tournaments)")
        columns = [col[1] for col in app.state.cursor.fetchall()]
        
        if 'tournament_form' not in columns:
            # Migrate old schema to new schema
            print("Migrating tournaments table to new schema...")
            app.state.cursor.execute("ALTER TABLE tournaments RENAME TO tournaments_old")
            app.state.cursor.execute('''CREATE TABLE tournaments
                                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                tournament_name TEXT NOT NULL,
                                tournament_form TEXT NOT NULL,
                                num_entries INTEGER NOT NULL,
                                boards_per_round INTEGER NOT NULL,
                                scoring_method TEXT NOT NULL,
                                movement_type TEXT NOT NULL,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            # Copy old data if any exists (default to 'pairs' for old tournaments)
            app.state.cursor.execute("""INSERT INTO tournaments 
                                (id, tournament_name, tournament_form, num_entries, 
                                boards_per_round, scoring_method, movement_type, created_at)
                                SELECT id, tournament_name, 'pairs', 
                                COALESCE(num_pairs, num_entries, 8),
                                boards_per_round, scoring_method, movement_type, created_at
                                FROM tournaments_old""")
            app.state.cursor.execute("DROP TABLE tournaments_old")
            print("Migration complete!")
    else:
        # Create new table
        app.state.cursor.execute('''CREATE TABLE tournaments
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            tournament_name TEXT NOT NULL,
                            tournament_form TEXT NOT NULL,
                            num_entries INTEGER NOT NULL,
                            boards_per_round INTEGER NOT NULL,
                            scoring_method TEXT NOT NULL,
                            movement_type TEXT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS rounds
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL,
                        table_number INTEGER NOT NULL,
                        entry1_id INTEGER NOT NULL,
                        entry2_id INTEGER NOT NULL,
                        boards TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS board_results
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
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS match_results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER,
                        table_id INTEGER,
                        round_number INTEGER,
                        total_score INTEGER,
                        opponent_score INTEGER,
                        imps INTEGER,
                        vp REAL,
                        UNIQUE(tournament_id, table_id, round_number))''')
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS tournament_settings
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER UNIQUE,
                        current_round INTEGER DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    app.state.cursor.execute('''CREATE TABLE IF NOT EXISTS table_passwords
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tournament_id INTEGER,
                        table_id INTEGER,
                        password TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(tournament_id, table_id),
                        FOREIGN KEY (tournament_id) REFERENCES tournaments(id))''')
    app.state.conn.commit()
    yield
    # Shutdown: Close database
    app.state.conn.close()

app = FastAPI(lifespan=lifespan)

# Authentication verification function
async def verify_token(request: Request) -> dict:
    """Dependency to verify authentication token."""
    # Get token from Authorization header
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization token")
    
    token = auth_header.replace('Bearer ', '')
    
    cursor = request.app.state.cursor
    
    # Check if token exists and is not expired
    cursor.execute("""SELECT tournament_id, table_id, expires_at FROM session_tokens 
                      WHERE token = ?""", (token,))
    result = cursor.fetchone()
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    
    tournament_id, table_id, expires_at = result
    
    # Check if token is expired
    if datetime.fromisoformat(expires_at) < datetime.now():
        raise HTTPException(status_code=401, detail="Authentication token expired")
    
    return {"tournament_id": tournament_id, "table_id": table_id, "token": token}

@app.get("/")
async def read_index():
    return FileResponse('html/index.html')

@app.get("/setup")
async def read_setup():
    return FileResponse('html/setup.html')

@app.get("/table_select")
async def read_table_select():
    return FileResponse('html/table_select.html')

@app.get("/management")
async def read_management():
    return FileResponse('html/management.html')

@app.get("/score_entry")
async def read_score_entry():
    return FileResponse('html/score_entry.html')

@app.post("/api/scores")
async def get_scores(request: Request, auth: dict = Depends(verify_token)):
    """Submit board scores - requires authentication."""
    data = await request.json()
    name = data.get('name')
    score = data.get('score')

    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    cursor.execute("INSERT INTO scores (name, score) VALUES (?, ?)", (name, score))
    conn.commit()

    print(f"Name: {name}, Score: {score} (Table {auth['table_id']})")
    return {"status": "success", "name": name, "score": score}

@app.post("/api/tournament/setup")
async def setup_tournament(request: Request):
    data = await request.json()
    
    tournament_name = data.get('tournamentName')
    tournament_form = data.get('tournamentForm', 'pairs')  # Default to pairs if not provided
    num_entries = data.get('numEntries')
    boards_per_round = data.get('boardsPerRound')
    scoring_method = data.get('scoringMethod')
    movement_type = data.get('movementType')
    user_num_rounds = data.get('numRounds')  # For swiss only
    
    # Validation
    if not tournament_name or not tournament_form or not num_entries:
        return {"status": "error", "message": "Missing required fields"}

    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Insert tournament
    cursor.execute("""INSERT INTO tournaments 
                      (tournament_name, tournament_form, num_entries, 
                       boards_per_round, scoring_method, movement_type) 
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (tournament_name, tournament_form, num_entries, 
                    boards_per_round, scoring_method, movement_type))
    tournament_id = cursor.lastrowid
    
    # Calculate number of tables based on entries
    if tournament_form == 'pairs':
        num_tables = (num_entries + 1) // 2  # Round up division
    else:  # teams
        num_tables = (num_entries + 1) // 2  # Each match needs one table
    
    # Calculate number of rounds based on movement type
    if tournament_form == 'pairs':
        if movement_type == 'mitchell':
            num_rounds = num_entries // 2  # Each pair plays against half the field
        elif movement_type == 'howell':
            num_rounds = num_entries - 1  # Round robin for pairs
        else:
            num_rounds = 1
    else:  # teams
        if movement_type == 'round-robin':
            num_rounds = num_entries - 1  # Each team plays all others
        elif movement_type == 'swiss':
            # Use user-specified rounds or default
            num_rounds = user_num_rounds if user_num_rounds else min(7, num_entries - 1)
        elif movement_type == 'knockout':
            import math
            num_rounds = math.ceil(math.log2(num_entries))  # Knockout stages
        else:
            num_rounds = 1
    
    # Create rounds table entries
    for round_num in range(1, num_rounds + 1):
        # Simple pairing: alternate entries at each table
        for table in range(1, num_tables + 1):
            if table * 2 <= num_entries:
                entry1 = table * 2 - 1
                entry2 = table * 2
                # Board numbers for this round
                start_board = (round_num - 1) * boards_per_round + 1
                end_board = round_num * boards_per_round
                boards = f"{start_board}-{end_board}"
                
                cursor.execute("""INSERT INTO rounds 
                              (tournament_id, round_number, table_number, entry1_id, entry2_id, boards) 
                              VALUES (?, ?, ?, ?, ?, ?)""",
                           (tournament_id, round_num, table, entry1, entry2, boards))
    
    conn.commit()

    print(f"Tournament setup: {tournament_name} - {num_tables} tables, {num_rounds} rounds created")
    return {
        "status": "success", 
        "message": "Tournament configuration saved and rounds created", 
        "tournament_id": tournament_id,
        "rounds_created": num_rounds
    }

@app.get("/api/tournament/current")
async def get_current_tournament(request: Request):
    cursor = request.app.state.cursor
    cursor.execute("SELECT * FROM tournaments ORDER BY created_at DESC LIMIT 1")
    result = cursor.fetchone()
    
    if result:
        tournament_id = result[0]
        # Get number of rounds for this tournament
        cursor.execute("SELECT COUNT(DISTINCT round_number) FROM rounds WHERE tournament_id = ?", (tournament_id,))
        num_rounds = cursor.fetchone()[0]
        
        return {
            "id": tournament_id,
            "tournamentName": result[1],
            "tournamentForm": result[2],
            "numEntries": result[3],
            "boardsPerRound": result[4],
            "scoringMethod": result[5],
            "movementType": result[6],
            "numRounds": num_rounds,
            "createdAt": result[7]
        }
    return {"status": "none", "message": "No tournament configured"}

@app.get("/api/tournament/{tournament_id}/rounds")
async def get_tournament_rounds(tournament_id: int, request: Request):
    cursor = request.app.state.cursor
    cursor.execute("SELECT * FROM rounds WHERE tournament_id = ? ORDER BY round_number, table_number", (tournament_id,))
    results = cursor.fetchall()
    
    rounds = []
    for row in results:
        rounds.append({
            "id": row[0],
            "tournamentId": row[1],
            "roundNumber": row[2],
            "tableNumber": row[3],
            "entry1Id": row[4],
            "entry2Id": row[5],
            "boards": row[6],
            "status": row[7]
        })
    
    return {"rounds": rounds}

@app.get("/api/board/{board_number}/vulnerability")
async def get_board_vulnerability(board_number: int):
    """Get vulnerability for a specific board number."""
    vul_enum = calculate_vulnerability(board_number)
    
    # Map enum to readable text and string value
    vul_map = {
        Vul.NONE: ("None Vulnerable", "None"),
        Vul.NS: ("NS Vulnerable", "NS"),
        Vul.EW: ("EW Vulnerable", "EW"),
        Vul.ALL: ("Both Vulnerable", "Both")
    }
    
    vul_text, vul_value = vul_map[vul_enum]
    
    return {
        "vulnerability": vul_value,
        "vulnerabilityText": vul_text,
        "boardNumber": board_number
    }

@app.get("/api/table/{table_id}/round/{round_number}/boards")
async def get_table_boards(table_id: int, round_number: int, request: Request):
    cursor = request.app.state.cursor
    
    # Get current tournament
    cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    if not tournament:
        return {"boards": []}
    
    tournament_id = tournament[0]
    
    # Get boards for this table/round from rounds table
    cursor.execute("SELECT boards FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                   (tournament_id, table_id, round_number))
    round_data = cursor.fetchone()
    
    if not round_data:
        return {"boards": []}
    
    # Parse board range (e.g., "1-3" or "4-6")
    boards_str = round_data[0]
    if '-' in boards_str:
        start, end = map(int, boards_str.split('-'))
        board_numbers = list(range(start, end + 1))
    else:
        board_numbers = [int(boards_str)]
    
    # Check which boards have been completed
    boards = []
    for board_num in board_numbers:
        cursor.execute("SELECT id FROM board_results WHERE tournament_id = ? AND table_id = ? AND round_number = ? AND board_number = ?",
                       (tournament_id, table_id, round_number, board_num))
        completed = cursor.fetchone() is not None
        
        boards.append({
            "boardNumber": board_num,
            "completed": completed
        })
    
    return {"boards": boards}

@app.post("/api/score/submit")
async def submit_score(request: Request, auth: dict = Depends(verify_token)):
    """Submit board scores - requires authentication."""
    data = await request.json()
    
    table_id = data.get('tableId')
    round_number = data.get('round')
    board_number = data.get('boardNumber')
    contract = data.get('contract')
    declarer = data.get('declarer')
    result = data.get('result')
    
    # Verify the table_id matches the authenticated token
    if table_id != auth['table_id']:
        raise HTTPException(status_code=403, detail="Not authorized to submit scores for this table")
    
    if not all([table_id, round_number, board_number, contract, declarer, result is not None]):
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Get current tournament
    cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    if not tournament:
        return {"status": "error", "message": "No active tournament"}
    
    tournament_id = tournament[0]
    
    # Get vulnerability from board number
    vul_enum = calculate_vulnerability(board_number)
    
    # Map enum to vulnerability string
    vul_map = {
        Vul.NONE: "None",
        Vul.NS: "NS",
        Vul.EW: "EW",
        Vul.ALL: "Both"
    }
    vulnerability = vul_map[vul_enum]
    
    # Determine if declarer's side is vulnerable
    vulnerable = False
    if vulnerability == 'Both':
        vulnerable = True
    elif vulnerability == 'NS' and (declarer == 'N' or declarer == 'S'):
        vulnerable = True
    elif vulnerability == 'EW' and (declarer == 'E' or declarer == 'W'):
        vulnerable = True
    
    # Calculate score using scoring module
    # Format for calculate_bridge_score: "level+suit declarer vulnerability tricks_made"
    vulnerability_str = 'v' if vulnerable else 'm'
    score_input = f"{contract} {declarer} {vulnerability_str} {result}"
    
    try:
        score = calculate_bridge_score(score_input)
    except Exception as e:
        return {"status": "error", "message": f"Error calculating score: {str(e)}"}
    
    # Check if score already exists for this board
    cursor.execute("SELECT id FROM board_results WHERE tournament_id = ? AND table_id = ? AND round_number = ? AND board_number = ?",
                   (tournament_id, table_id, round_number, board_number))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing score
        cursor.execute("""UPDATE board_results 
                         SET contract = ?, declarer = ?, vulnerable = ?, result = ?, score = ?
                         WHERE id = ?""",
                      (contract, declarer, vulnerable, result, score, existing[0]))
    else:
        # Insert new score
        cursor.execute("""INSERT INTO board_results 
                         (tournament_id, table_id, round_number, board_number, contract, declarer, vulnerable, result, score)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (tournament_id, table_id, round_number, board_number, contract, declarer, vulnerable, result, score))
    
    conn.commit()
    
    print(f"Score submitted: Table {table_id}, Board {board_number}, Contract {contract}, Score {score}")
    return {"status": "success", "score": score, "message": "Score saved successfully"}

@app.get("/api/table/{table_id}/round/{round_number}/results")
async def get_table_results(table_id: int, round_number: int, request: Request):
    """Get all results entered for a table/round."""
    cursor = request.app.state.cursor
    
    # Get current tournament
    cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    if not tournament:
        return {"results": [], "allComplete": False}
    
    tournament_id = tournament[0]
    
    # Get all results for this table/round
    cursor.execute("""SELECT board_number, contract, declarer, result, score 
                      FROM board_results 
                      WHERE tournament_id = ? AND table_id = ? AND round_number = ?
                      ORDER BY board_number""",
                   (tournament_id, table_id, round_number))
    results_data = cursor.fetchall()
    
    # Get expected boards for this table/round
    cursor.execute("SELECT boards FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                   (tournament_id, table_id, round_number))
    round_data = cursor.fetchone()
    
    all_complete = False
    if round_data:
        boards_str = round_data[0]
        if '-' in boards_str:
            start, end = map(int, boards_str.split('-'))
            expected_count = end - start + 1
        else:
            expected_count = 1
        all_complete = len(results_data) >= expected_count
    
    results = []
    for row in results_data:
        results.append({
            "boardNumber": row[0],
            "contract": row[1],
            "declarer": row[2],
            "result": row[3],
            "score": row[4]
        })
    
    return {"results": results, "allComplete": all_complete}

@app.post("/api/table/submit_round")
async def submit_round(request: Request):
    """Mark a table's round as complete and calculate IMPs if opponent table also complete."""
    data = await request.json()
    table_id = data.get('tableId')
    round_number = data.get('round')
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Get current tournament
    cursor.execute("SELECT id, boards_per_round FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    if not tournament:
        return {"status": "error", "message": "No active tournament"}
    
    tournament_id, boards_per_round = tournament[0], tournament[1]
    
    # Mark this round as complete
    cursor.execute("UPDATE rounds SET status = 'complete' WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                   (tournament_id, table_id, round_number))
    conn.commit()
    
    # Find opponent table (for now, simple pairing: 1&2, 3&4, etc.)
    if table_id % 2 == 1:
        opponent_table = table_id + 1
    else:
        opponent_table = table_id - 1
    
    # Check if opponent table has also completed
    cursor.execute("SELECT status FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                   (tournament_id, opponent_table, round_number))
    opponent_status = cursor.fetchone()
    
    match_complete = False
    if opponent_status and opponent_status[0] == 'complete':
        # Both tables complete, calculate IMPs and VPs
        match_complete = True
        calculate_match_result(cursor, conn, tournament_id, table_id, opponent_table, round_number, boards_per_round)
    
    return {
        "status": "success", 
        "matchComplete": match_complete,
        "message": "Round submitted" + (" and match results calculated" if match_complete else "")
    }

def calculate_match_result(cursor, conn, tournament_id, table1, table2, round_number, boards_per_round):
    """Calculate IMPs and VPs for a completed match."""
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

@app.get("/api/table/{table_id}/round/{round_number}/match_status")
async def get_match_status(table_id: int, round_number: int, request: Request):
    """Get match status and results if complete."""
    cursor = request.app.state.cursor
    
    # Get current tournament
    cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    if not tournament:
        return {"matchComplete": False}
    
    tournament_id = tournament[0]
    
    # Check if match results exist for this table/round
    cursor.execute("""SELECT total_score, opponent_score, imps, vp 
                      FROM match_results 
                      WHERE tournament_id = ? AND table_id = ? AND round_number = ?""",
                   (tournament_id, table_id, round_number))
    result = cursor.fetchone()
    
    if result:
        # Calculate opponent VP (20 - our VP)
        our_vp = result[3]
        opp_vp = 20 - our_vp
        
        return {
            "matchComplete": True,
            "ourScore": result[0],
            "oppScore": result[1],
            "imps": result[2],
            "vp": our_vp,
            "oppVp": opp_vp
        }
    
    return {"matchComplete": False}

@app.get("/api/tournament/{tournament_id}/current_round")
async def get_current_round(tournament_id: int, request: Request):
    """Get the current round number for the tournament."""
    cursor = request.app.state.cursor
    
    # Get current round from tournament_settings
    cursor.execute("SELECT current_round FROM tournament_settings WHERE tournament_id = ?", (tournament_id,))
    settings = cursor.fetchone()
    
    if settings:
        return {"currentRound": settings[0]}
    
    # Fallback to max round if no settings exist
    cursor.execute("SELECT MAX(round_number) FROM rounds WHERE tournament_id = ?", (tournament_id,))
    max_round = cursor.fetchone()[0]
    
    return {"currentRound": max_round if max_round else 1}

@app.get("/api/tournament/{tournament_id}/available_rounds")
async def get_available_rounds(tournament_id: int, request: Request):
    """Get all available rounds for the tournament."""
    cursor = request.app.state.cursor
    
    cursor.execute("SELECT DISTINCT round_number FROM rounds WHERE tournament_id = ? ORDER BY round_number", 
                   (tournament_id,))
    results = cursor.fetchall()
    
    rounds = [row[0] for row in results]
    
    # If no rounds exist yet, return round 1 as default
    if not rounds:
        rounds = [1]
    
    return {"rounds": rounds}

@app.get("/api/tournament/{tournament_id}/round/{round_number}/matchups")
async def get_round_matchups(tournament_id: int, round_number: int, request: Request):
    """Get all matchups for a specific round."""
    cursor = request.app.state.cursor
    
    cursor.execute("""SELECT id, table_number, entry1_id, entry2_id, boards, status 
                      FROM rounds 
                      WHERE tournament_id = ? AND round_number = ?
                      ORDER BY table_number""",
                   (tournament_id, round_number))
    results = cursor.fetchall()
    
    matchups = []
    for row in results:
        matchups.append({
            "id": row[0],
            "tableNumber": row[1],
            "entry1Id": row[2],
            "entry2Id": row[3],
            "boards": row[4],
            "status": row[5]
        })
    
    return {"matchups": matchups}

@app.get("/api/tournament/{tournament_id}/round/{round_number}/all_scores")
async def get_round_all_scores(tournament_id: int, round_number: int, request: Request):
    """Get all scores for a specific round."""
    cursor = request.app.state.cursor
    
    cursor.execute("""SELECT id, table_id, board_number, contract, declarer, result, score
                      FROM board_results
                      WHERE tournament_id = ? AND round_number = ?
                      ORDER BY table_id, board_number""",
                   (tournament_id, round_number))
    results = cursor.fetchall()
    
    scores = []
    for row in results:
        scores.append({
            "id": row[0],
            "tableId": row[1],
            "boardNumber": row[2],
            "contract": row[3],
            "declarer": row[4],
            "result": row[5],
            "score": row[6]
        })
    
    return {"scores": scores}

@app.post("/api/score/update")
async def update_score(request: Request, auth: dict = Depends(verify_token)):
    """Update an existing score entry - requires authentication."""
    data = await request.json()
    
    score_id = data.get('scoreId')
    contract = data.get('contract')
    declarer = data.get('declarer')
    result = data.get('result')
    score = data.get('score')
    
    if not all([score_id, contract, declarer, result is not None, score is not None]):
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    cursor.execute("""UPDATE board_results 
                      SET contract = ?, declarer = ?, result = ?, score = ?
                      WHERE id = ?""",
                   (contract, declarer, result, score, score_id))
    conn.commit()
    
    return {"status": "success", "message": "Score updated successfully"}

@app.post("/api/matchup/update")
async def update_matchup(request: Request):
    """Update a matchup (change teams/pairs)."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    round_number = data.get('round')
    table_number = data.get('tableNumber')
    entry1_id = data.get('entry1Id')
    entry2_id = data.get('entry2Id')
    
    if not all([tournament_id, round_number, table_number, entry1_id, entry2_id]):
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    cursor.execute("""UPDATE rounds 
                      SET entry1_id = ?, entry2_id = ?
                      WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                   (entry1_id, entry2_id, tournament_id, round_number, table_number))
    conn.commit()
    
    return {"status": "success", "message": "Matchup updated successfully"}

@app.post("/api/matchup/swap_tables")
async def swap_tables(request: Request):
    """Swap the table numbers of two matchups."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    round_number = data.get('round')
    table1 = data.get('table1')
    table2 = data.get('table2')
    
    if not all([tournament_id, round_number, table1, table2]):
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Get matchup data for both tables
    cursor.execute("""SELECT entry1_id, entry2_id, boards 
                      FROM rounds 
                      WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                   (tournament_id, round_number, table1))
    matchup1 = cursor.fetchone()
    
    cursor.execute("""SELECT entry1_id, entry2_id, boards 
                      FROM rounds 
                      WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                   (tournament_id, round_number, table2))
    matchup2 = cursor.fetchone()
    
    if not matchup1 or not matchup2:
        return {"status": "error", "message": "One or both tables not found"}
    
    # Swap the matchups
    cursor.execute("""UPDATE rounds 
                      SET entry1_id = ?, entry2_id = ?, boards = ?
                      WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                   (matchup2[0], matchup2[1], matchup2[2], tournament_id, round_number, table1))
    
    cursor.execute("""UPDATE rounds 
                      SET entry1_id = ?, entry2_id = ?, boards = ?
                      WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                   (matchup1[0], matchup1[1], matchup1[2], tournament_id, round_number, table2))
    
    # Also swap board results table_ids
    cursor.execute("""UPDATE board_results SET table_id = -1
                      WHERE tournament_id = ? AND round_number = ? AND table_id = ?""",
                   (tournament_id, round_number, table1))
    cursor.execute("""UPDATE board_results SET table_id = ?
                      WHERE tournament_id = ? AND round_number = ? AND table_id = ?""",
                   (table1, tournament_id, round_number, table2))
    cursor.execute("""UPDATE board_results SET table_id = ?
                      WHERE tournament_id = ? AND round_number = ? AND table_id = -1""",
                   (table2, tournament_id, round_number))
    
    conn.commit()
    
    return {"status": "success", "message": "Tables swapped successfully"}

@app.post("/api/tournament/set_current_round")
async def set_current_round(request: Request):
    """Set a specific round as the current tournament round."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    round_number = data.get('roundNumber')
    
    if not tournament_id or round_number is None:
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Verify the round exists
    cursor.execute("""SELECT COUNT(*) FROM rounds 
                      WHERE tournament_id = ? AND round_number = ?""",
                   (tournament_id, round_number))
    
    if cursor.fetchone()[0] == 0:
        return {"status": "error", "message": f"Round {round_number} does not exist"}
    
    # Store current round in tournament_settings
    cursor.execute("""INSERT OR REPLACE INTO tournament_settings 
                      (tournament_id, current_round) 
                      VALUES (?, ?)""",
                   (tournament_id, round_number))
    conn.commit()
    
    return {"status": "success", "currentRound": round_number}

@app.post("/api/table/set_password")
async def set_table_password(request: Request):
    """Set or update password for a table."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    table_id = data.get('tableId')
    password = data.get('password')
    
    if not tournament_id or not table_id or not password:
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    cursor.execute("""INSERT OR REPLACE INTO table_passwords 
                      (tournament_id, table_id, password) 
                      VALUES (?, ?, ?)""",
                   (tournament_id, table_id, password))
    conn.commit()
    
    return {"status": "success", "message": "Password set successfully"}

@app.post("/api/table/verify_password")
async def verify_table_password(request: Request):
    """Verify password for a table and return authentication token."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    table_id = data.get('tableId')
    password = data.get('password')
    
    if not tournament_id or not table_id or not password:
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    cursor.execute("""SELECT password FROM table_passwords 
                      WHERE tournament_id = ? AND table_id = ?""",
                   (tournament_id, table_id))
    result = cursor.fetchone()
    
    password_correct = False
    if not result:
        # No password set for this table - allow access
        password_correct = True
    elif result[0] == password:
        password_correct = True
    
    if password_correct:
        # Generate session token
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=8)  # Token valid for 8 hours
        
        # Store token in database
        cursor.execute("""INSERT INTO session_tokens (token, tournament_id, table_id, expires_at)
                          VALUES (?, ?, ?, ?)""",
                       (token, tournament_id, table_id, expires_at.isoformat()))
        conn.commit()
        
        return {"status": "success", "authenticated": True, "token": token}
    else:
        return {"status": "error", "authenticated": False, "message": "Incorrect password"}

@app.get("/api/table/{table_id}/has_password")
async def check_table_has_password(table_id: int, request: Request):
    """Check if a table requires a password."""
    cursor = request.app.state.cursor
    
    # Get current tournament
    cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
    tournament = cursor.fetchone()
    
    if not tournament:
        return {"hasPassword": False}
    
    tournament_id = tournament[0]
    
    cursor.execute("""SELECT id FROM table_passwords 
                      WHERE tournament_id = ? AND table_id = ?""",
                   (tournament_id, table_id))
    result = cursor.fetchone()
    
    return {"hasPassword": result is not None}

@app.post("/api/tournament/advance_round")
async def advance_round(request: Request):
    """Advance to the next round and generate new matchups using movement logic."""
    data = await request.json()
    
    tournament_id = data.get('tournamentId')
    current_round = data.get('currentRound')
    
    if not tournament_id or current_round is None:
        return {"status": "error", "message": "Missing required fields"}
    
    cursor = request.app.state.cursor
    conn = request.app.state.conn
    
    # Get tournament details
    cursor.execute("""SELECT tournament_form, movement_type, num_entries, boards_per_round 
                      FROM tournaments WHERE id = ?""", (tournament_id,))
    tournament = cursor.fetchone()
    
    if not tournament:
        return {"status": "error", "message": "Tournament not found"}
    
    tournament_form, movement_type, num_entries, boards_per_round = tournament
    
    # Check if all scores for current round are complete
    cursor.execute("""SELECT COUNT(*) FROM rounds WHERE tournament_id = ? AND round_number = ?""",
                   (tournament_id, current_round))
    total_matches = cursor.fetchone()[0]
    
    # Calculate expected number of board results
    expected_results = total_matches * boards_per_round
    
    cursor.execute("""SELECT COUNT(*) FROM board_results 
                      WHERE tournament_id = ? AND round_number = ?""",
                   (tournament_id, current_round))
    actual_results = cursor.fetchone()[0]
    
    if actual_results < expected_results:
        return {
            "status": "error", 
            "message": f"Cannot advance: {actual_results} of {expected_results} board results entered. All scores must be collected first."
        }
    
    new_round = current_round + 1
    
    # Generate matchups based on movement type
    try:
        if movement_type == 'round-robin':
            # Get all rounds for round robin
            all_rounds = round_robin(num_entries)
            if new_round - 1 < len(all_rounds):
                round_matchups = all_rounds[new_round - 1]
            else:
                return {"status": "error", "message": "No more rounds in round robin"}
        elif movement_type == 'swiss':
            # Get current standings and use swiss pairing
            cursor.execute("""SELECT table_id, SUM(vp) as total_vp
                              FROM match_results
                              WHERE tournament_id = ?
                              GROUP BY table_id
                              ORDER BY total_vp DESC""", (tournament_id,))
            standings_results = cursor.fetchall()
            
            team_ids = list(range(1, num_entries + 1))
            
            # Build standings dictionary
            standings = {row[0]: float(row[1]) for row in standings_results} if standings_results else {tid: 0.0 for tid in team_ids}
            
            # Build previous opponents dictionary
            cursor.execute("""SELECT entry1_id, entry2_id 
                              FROM rounds 
                              WHERE tournament_id = ? AND round_number < ?""",
                           (tournament_id, new_round))
            previous_matches = cursor.fetchall()
            
            previous_opponents = {tid: [] for tid in team_ids}
            for entry1, entry2 in previous_matches:
                if entry1 in previous_opponents:
                    previous_opponents[entry1].append(entry2)
                if entry2 in previous_opponents:
                    previous_opponents[entry2].append(entry1)
            
            # Call swiss_pairing with all required parameters
            pairings = swiss_pairing(team_ids, standings, previous_opponents, new_round)
            
            # Convert from swiss_pairing format to simple matchup format
            # swiss_pairing returns: List[Tuple[int, str, int, int]] = (table_number, room, team_ns, team_ew)
            # We need: List[Tuple[int, int]] = (team1, team2)
            # Group by table number and take one room per table
            round_matchups = []
            seen_tables = set()
            for table_num, room, team_ns, team_ew in pairings:
                if table_num not in seen_tables:
                    round_matchups.append((team_ns, team_ew))
                    seen_tables.add(table_num)
        else:
            # For mitchell/howell or other movements, use simple rotation
            team_ids = list(range(1, num_entries + 1))
            # Simple rotation: each round shifts by 1
            offset = (new_round - 1) % (len(team_ids) - 1)
            round_matchups = [(team_ids[i], team_ids[(i + offset) % len(team_ids)]) 
                             for i in range(0, len(team_ids), 2) if i + offset < len(team_ids)]
        
        # Insert new round matchups into database
        for table_num, (entry1, entry2) in enumerate(round_matchups, start=1):
            start_board = (new_round - 1) * boards_per_round + 1
            end_board = new_round * boards_per_round
            boards = f"{start_board}-{end_board}"
            
            cursor.execute("""INSERT INTO rounds 
                             (tournament_id, round_number, table_number, entry1_id, entry2_id, boards, status)
                             VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                          (tournament_id, new_round, table_num, entry1, entry2, boards))
        
        conn.commit()
        
        return {
            "status": "success",
            "newRound": new_round,
            "message": f"Advanced to round {new_round}"
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Error generating matchups: {str(e)}"}

if __name__ == '__main__':
    uvicorn.run('bridge_score:app', host='127.0.0.1', port=8000, reload=True)

