from fastapi import HTTPException, Depends, Request
from auth import verify_token
from scoring import calculate_bridge_score, calculate_vulnerability, Vul, calculate_imp, calculate_vp
from movements import round_robin, swiss_pairing
from database import calculate_match_result, get_master_conn, get_tournament_conn, init_tournament_db
import secrets
import sqlite3
from datetime import datetime, timedelta
import math


# Movement type handlers
def handle_round_robin(num_entries: int, new_round: int) -> list:
    """Generate matchups for round-robin movement."""
    all_rounds = round_robin(num_entries)
    if new_round - 1 >= len(all_rounds):
        raise ValueError("No more rounds in round robin")

    round_pairings = all_rounds[new_round - 1]
    # Filter out bye matches (bye team is num_entries + 1 when num_entries is odd)
    if num_entries % 2 == 1:
        bye_team = num_entries + 1
        round_pairings = [
            (team1, team2)
            for team1, team2 in round_pairings
            if team1 != bye_team and team2 != bye_team
        ]
    return round_pairings


def handle_swiss(cursor, tournament_id: int, num_entries: int, new_round: int) -> list:
    """Generate matchups for Swiss movement."""
    # Get current standings
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
    
    # Get pairings from swiss_pairing algorithm
    pairings = swiss_pairing(team_ids, standings, previous_opponents, new_round)
    
    # Convert from swiss_pairing format to simple matchup format
    # swiss_pairing returns: List[Tuple[int, str, int, int]] = (table_number, room, team_ns, team_ew)
    # We need: List[Tuple[int, int]] = (team1, team2)
    round_matchups = []
    seen_tables = set()
    for table_num, room, team_ns, team_ew in pairings:
        if table_num not in seen_tables:
            round_matchups.append((team_ns, team_ew))
            seen_tables.add(table_num)
    
    return round_matchups


def handle_rotation(num_entries: int, new_round: int) -> list:
    """Generate matchups using simple rotation/fallback movement."""
    team_ids = list(range(1, num_entries + 1))
    offset = (new_round - 1) % (len(team_ids) - 1)
    round_matchups = [(team_ids[i], team_ids[(i + offset) % len(team_ids)]) 
                     for i in range(0, len(team_ids), 2) if i + offset < len(team_ids)]
    return round_matchups


def register_api_routes(app):
    """Register all API routes with the FastAPI app."""
    
    @app.post("/api/scores")
    async def get_scores(request: Request, auth: dict = Depends(verify_token)):
        """Submit board scores - requires authentication."""
        data = await request.json()
        name = data.get('name')
        score = data.get('score')
        
        tournament_id = auth['tournament_id']
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("INSERT INTO scores (name, score) VALUES (?, ?)", (name, score))
            conn.commit()
        finally:
            conn.close()

        print(f"Name: {name}, Score: {score} (Table {auth['table_id']})")
        return {"status": "success", "name": name, "score": score}

    @app.post("/api/tournament/setup")
    async def setup_tournament(request: Request):
        data = await request.json()
        
        tournament_name = data.get('tournamentName')
        tournament_form = data.get('tournamentForm', 'pairs')
        num_entries = data.get('numEntries')
        boards_per_round = data.get('boardsPerRound')
        scoring_method = data.get('scoringMethod')
        movement_type = data.get('movementType')
        user_num_rounds = data.get('numRounds')
        
        if not tournament_name or not tournament_form or not num_entries:
            raise HTTPException(status_code=422, detail="Missing required fields")

        master_conn = get_master_conn()
        master_cursor = master_conn.cursor()
        
        try:
            # Insert tournament
            master_cursor.execute("""INSERT INTO tournaments 
                            (tournament_name, tournament_form, num_entries, 
                            boards_per_round, scoring_method, movement_type) 
                            VALUES (?, ?, ?, ?, ?, ?)""",
                        (tournament_name, tournament_form, num_entries, 
                            boards_per_round, scoring_method, movement_type))
            tournament_id = master_cursor.lastrowid
            master_conn.commit()
        finally:
            master_conn.close()
        
        # Initialize tournament specific database
        init_tournament_db(tournament_id)
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            # Calculate number of tables and rounds
            num_rounds = 0
            num_tables = 0
            
            if tournament_form == 'pairs':
                num_tables = (num_entries + 1) // 2
                
                if movement_type == 'mitchell':
                    num_rounds = num_entries // 2
                elif movement_type == 'howell':
                    num_rounds = num_entries - 1
                else:
                    num_rounds = 1
                    
                # Create rounds table entries for pairs
                for round_num in range(1, num_rounds + 1):
                    for table in range(1, num_tables + 1):
                        if table * 2 <= num_entries:
                            entry1 = table * 2 - 1
                            entry2 = table * 2
                            start_board = (round_num - 1) * boards_per_round + 1
                            end_board = round_num * boards_per_round
                            boards = f"{start_board}-{end_board}"
                            
                            cursor.execute("""INSERT INTO rounds 
                                        (tournament_id, round_number, table_number, entry1_id, entry2_id, boards) 
                                        VALUES (?, ?, ?, ?, ?, ?)""",
                                    (tournament_id, round_num, table, entry1, entry2, boards))
            
            elif tournament_form == 'teams':
                if movement_type == 'round-robin':
                    # For round-robin: each match needs 2 tables (duplicate bridge)
                    all_rounds = round_robin(num_entries)
                    num_rounds = len(all_rounds)
                    num_tables = (num_entries // 2) * 2  # Each match needs 2 tables

                    # Create rounds table entries for teams round-robin (duplicate)
                    for round_num in range(1, num_rounds + 1):
                        round_pairings = all_rounds[round_num - 1]
                        if num_entries % 2 == 1:
                            bye_team = num_entries + 1
                            round_pairings = [
                                (team1, team2)
                                for team1, team2 in round_pairings
                                if team1 != bye_team and team2 != bye_team
                            ]

                        table_id_counter = 1
                        for entry1, entry2 in round_pairings:
                            # Table 1: entry1 NS, entry2 EW
                            start_board = (round_num - 1) * boards_per_round + 1
                            end_board = round_num * boards_per_round
                            boards = f"{start_board}-{end_board}"

                            cursor.execute("""INSERT INTO rounds 
                                        (tournament_id, round_number, table_number, entry1_id, entry2_id, boards) 
                                        VALUES (?, ?, ?, ?, ?, ?)""",
                                    (tournament_id, round_num, table_id_counter, entry1, entry2, boards))

                            # Table 2: entry1 EW, entry2 NS (duplicate)
                            table_id_counter += 1
                            cursor.execute("""INSERT INTO rounds 
                                        (tournament_id, round_number, table_number, entry1_id, entry2_id, boards) 
                                        VALUES (?, ?, ?, ?, ?, ?)""",
                                    (tournament_id, round_num, table_id_counter, entry2, entry1, boards))
                            table_id_counter += 1
                
                elif movement_type == 'swiss':
                    # Swiss: calculate expected rounds but don't pre-populate (dynamic pairings)
                    num_rounds = user_num_rounds if user_num_rounds else min(7, num_entries - 1)
                    num_tables = (num_entries // 2) * 2
                # Don't create rounds - they will be generated by advance_round based on standings
                
            elif movement_type == 'knockout':
                # Knockout: calculate expected rounds but don't pre-populate (dynamic pairings)
                num_rounds = math.ceil(math.log2(num_entries))
                num_tables = (num_entries // 2) * 2
                # Don't create rounds - they will be generated based on match results
                
            else:
                # Unknown movement type for teams
                num_rounds = 1
                num_tables = (num_entries // 2) * 2

            conn.commit()
        finally:
            conn.close()

        print(f"Tournament setup: {tournament_name} - {num_tables} tables, {num_rounds} rounds created")
        return {
            "status": "success", 
            "message": "Tournament configuration saved and rounds created", 
            "tournament_id": tournament_id,
            "rounds_created": num_rounds
        }

    @app.get("/api/tournament/current")
    async def get_current_tournament(request: Request):
        conn = get_master_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM tournaments ORDER BY created_at DESC LIMIT 1")
            result = cursor.fetchone()
        finally:
            conn.close()
        
        if result:
            tournament_id = result[0]
            
            # Get round count from tournament DB
            t_conn = get_tournament_conn(tournament_id)
            t_cursor = t_conn.cursor()
            try:
                t_cursor.execute("SELECT COUNT(DISTINCT round_number) FROM rounds WHERE tournament_id = ?", (tournament_id,))
                num_rounds_result = t_cursor.fetchone()
                num_rounds = num_rounds_result[0] if num_rounds_result else 0
            except sqlite3.OperationalError:
                # Table might not exist if initialization failed
                num_rounds = 0
            finally:
                t_conn.close()
            
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
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM rounds WHERE tournament_id = ? ORDER BY round_number, table_number", (tournament_id,))
            results = cursor.fetchall()
        finally:
            conn.close()
        
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
        # Get current tournament ID from master DB
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        tournament_id = None
        try:
            m_cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
            tournament = m_cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
        finally:
            m_conn.close()
            
        if not tournament_id:
            return {"boards": []}
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT boards FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                        (tournament_id, table_id, round_number))
            round_data = cursor.fetchone()
            
            if not round_data:
                return {"boards": []}
            
            boards_str = round_data[0]
            if '-' in boards_str:
                start, end = map(int, boards_str.split('-'))
                board_numbers = list(range(start, end + 1))
            else:
                board_numbers = [int(boards_str)]
            
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
        finally:
            conn.close()

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
        
        if table_id != auth['table_id']:
            raise HTTPException(status_code=403, detail="Not authorized to submit scores for this table")
        
        if not all([table_id, round_number, board_number, contract, declarer, result is not None]):
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        # Use tournament_id from auth token
        tournament_id = auth['tournament_id']
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            vul_enum = calculate_vulnerability(board_number)
            
            vul_map = {
                Vul.NONE: "None",
                Vul.NS: "NS",
                Vul.EW: "EW",
                Vul.ALL: "Both"
            }
            vulnerability = vul_map[vul_enum]
            
            vulnerable = False
            if vulnerability == 'Both':
                vulnerable = True
            elif vulnerability == 'NS' and (declarer == 'N' or declarer == 'S'):
                vulnerable = True
            elif vulnerability == 'EW' and (declarer == 'E' or declarer == 'W'):
                vulnerable = True
            
            vulnerability_str = 'v' if vulnerable else 'm'
            score_input = f"{contract} {vulnerability_str} {result}"
            
            try:
                score = calculate_bridge_score(score_input)
                if declarer in ['E', 'W']:
                    score = -score
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error calculating score: {str(e)}")
            
            cursor.execute("SELECT id FROM board_results WHERE tournament_id = ? AND table_id = ? AND round_number = ? AND board_number = ?",
                        (tournament_id, table_id, round_number, board_number))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""UPDATE board_results 
                                SET contract = ?, declarer = ?, vulnerable = ?, result = ?, score = ?
                                WHERE id = ?""",
                            (contract, declarer, vulnerable, result, score, existing[0]))
            else:
                cursor.execute("""INSERT INTO board_results 
                                (tournament_id, table_id, round_number, board_number, contract, declarer, vulnerable, result, score)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (tournament_id, table_id, round_number, board_number, contract, declarer, vulnerable, result, score))
            
            conn.commit()
            
            print(f"Score submitted: Table {table_id}, Board {board_number}, Contract {contract}, Score {score}")
            return {"status": "success", "score": score, "message": "Score saved successfully"}
        finally:
            conn.close()

    @app.get("/api/table/{table_id}/round/{round_number}/results")
    async def get_table_results(table_id: int, round_number: int, request: Request):
        """Get all results entered for a table/round."""
        # Get current tournament ID
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        tournament_id = None
        try:
            m_cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
            tournament = m_cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
        finally:
            m_conn.close()
            
        if not tournament_id:
            return {"results": [], "allComplete": False}
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""SELECT board_number, contract, declarer, result, score 
                            FROM board_results 
                            WHERE tournament_id = ? AND table_id = ? AND round_number = ?
                            ORDER BY board_number""",
                        (tournament_id, table_id, round_number))
            results_data = cursor.fetchall()
            
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
        finally:
            conn.close()

    @app.post("/api/table/submit_round")
    async def submit_round(request: Request):
        """Mark a table's round as complete and calculate IMPs if opponent table also complete."""
        data = await request.json()
        table_id = data.get('tableId')
        round_number = data.get('round')
        
        # Get current tournament ID and settings
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        tournament = None
        try:
            m_cursor.execute("SELECT id, boards_per_round FROM tournaments ORDER BY created_at DESC LIMIT 1")
            tournament = m_cursor.fetchone()
        finally:
            m_conn.close()

        if not tournament:
            raise HTTPException(status_code=404, detail="No active tournament")
        
        tournament_id, boards_per_round = tournament[0], tournament[1]
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("UPDATE rounds SET status = 'complete' WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                        (tournament_id, table_id, round_number))
            conn.commit()
            
            if table_id % 2 == 1:
                opponent_table = table_id + 1
            else:
                opponent_table = table_id - 1
            
            cursor.execute("SELECT status FROM rounds WHERE tournament_id = ? AND table_number = ? AND round_number = ?",
                        (tournament_id, opponent_table, round_number))
            opponent_status = cursor.fetchone()
            
            match_complete = False
            if opponent_status and opponent_status[0] == 'complete':
                match_complete = True
                calculate_match_result(cursor, conn, tournament_id, table_id, opponent_table, round_number, boards_per_round)
            
            return {
                "status": "success", 
                "matchComplete": match_complete,
                "message": "Round submitted" + (" and match results calculated" if match_complete else "")
            }
        finally:
            conn.close()

    @app.get("/api/table/{table_id}/round/{round_number}/match_status")
    async def get_match_status(table_id: int, round_number: int, request: Request):
        """Get match status and results if complete."""
        # Get current tournament ID
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        tournament_id = None
        try:
            m_cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
            tournament = m_cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
        finally:
            m_conn.close()
            
        if not tournament_id:
            return {"matchComplete": False}
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""SELECT total_score, opponent_score, imps, vp 
                            FROM match_results 
                            WHERE tournament_id = ? AND table_id = ? AND round_number = ?""",
                        (tournament_id, table_id, round_number))
            result = cursor.fetchone()
            
            if result:
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
        finally:
            conn.close()

    @app.get("/api/tournament/{tournament_id}/current_round")
    async def get_current_round(tournament_id: int, request: Request):
        """Get the current round number for the tournament."""
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT current_round FROM tournament_settings WHERE tournament_id = ?", (tournament_id,))
            settings = cursor.fetchone()
            
            if settings:
                return {"currentRound": settings[0]}
            
            cursor.execute("SELECT MAX(round_number) FROM rounds WHERE tournament_id = ?", (tournament_id,))
            max_round = cursor.fetchone()[0]
            
            return {"currentRound": max_round if max_round else 1}
        finally:
            conn.close()

    @app.get("/api/tournament/{tournament_id}/available_rounds")
    async def get_available_rounds(tournament_id: int, request: Request):
        """Get all available rounds for the tournament."""
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT DISTINCT round_number FROM rounds WHERE tournament_id = ? ORDER BY round_number", 
                        (tournament_id,))
            results = cursor.fetchall()
            
            rounds = [row[0] for row in results]
            
            if not rounds:
                rounds = [1]
            
            return {"rounds": rounds}
        finally:
            conn.close()

    @app.get("/api/tournament/{tournament_id}/round/{round_number}/matchups")
    async def get_round_matchups(tournament_id: int, round_number: int, request: Request):
        """Get all matchups for a specific round."""
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
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
        finally:
            conn.close()

    @app.get("/api/tournament/{tournament_id}/round/{round_number}/all_scores")
    async def get_round_all_scores(tournament_id: int, round_number: int, request: Request):
        """Get all scores for a specific round."""
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
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
        finally:
            conn.close()

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
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        tournament_id = auth['tournament_id']
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""UPDATE board_results 
                            SET contract = ?, declarer = ?, result = ?, score = ?
                            WHERE id = ?""",
                        (contract, declarer, result, score, score_id))
            conn.commit()
            
            return {"status": "success", "message": "Score updated successfully"}
        finally:
            conn.close()

    @app.post("/api/matchup/update")
    async def update_matchup(request: Request):
        """
        Update a matchup (change teams/pairs).
        
        Purpose:
        Allows an admin or the system to change the teams/pairs assigned to a specific table 
        in a specific round (i.e., update the matchup for a table).
        """
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        round_number = data.get('round')
        table_number = data.get('tableNumber')
        entry1_id = data.get('entry1Id')
        entry2_id = data.get('entry2Id')
        
        if not all([tournament_id, round_number, table_number, entry1_id, entry2_id]):
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""UPDATE rounds 
                            SET entry1_id = ?, entry2_id = ?
                            WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                        (entry1_id, entry2_id, tournament_id, round_number, table_number))
            conn.commit()
            
            return {"status": "success", "message": "Matchup updated successfully"}
        finally:
            conn.close()

    @app.post("/api/matchup/swap_tables")
    async def swap_tables(request: Request):
        """Swap the table numbers of two matchups."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        round_number = data.get('round')
        table1 = data.get('table1')
        table2 = data.get('table2')
        
        if not all([tournament_id, round_number, table1, table2]):
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
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
                raise HTTPException(status_code=404, detail="One or both tables not found")
            
            cursor.execute("""UPDATE rounds 
                            SET entry1_id = ?, entry2_id = ?, boards = ?
                            WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                        (matchup2[0], matchup2[1], matchup2[2], tournament_id, round_number, table1))
            
            cursor.execute("""UPDATE rounds 
                            SET entry1_id = ?, entry2_id = ?, boards = ?
                            WHERE tournament_id = ? AND round_number = ? AND table_number = ?""",
                        (matchup1[0], matchup1[1], matchup1[2], tournament_id, round_number, table2))
            
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
        finally:
            conn.close()

    @app.post("/api/tournament/set_current_round")
    async def set_current_round(request: Request):
        """Set a specific round as the current tournament round."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        round_number = data.get('roundNumber')
        
        if not tournament_id or round_number is None:
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""SELECT COUNT(*) FROM rounds 
                            WHERE tournament_id = ? AND round_number = ?""",
                        (tournament_id, round_number))
            
            if cursor.fetchone()[0] == 0:
                raise HTTPException(status_code=404, detail=f"Round {round_number} does not exist")
            
            cursor.execute("""INSERT OR REPLACE INTO tournament_settings 
                            (tournament_id, current_round) 
                            VALUES (?, ?)""",
                        (tournament_id, round_number))
            conn.commit()
            
            return {"status": "success", "currentRound": round_number}
        finally:
            conn.close()

    @app.post("/api/table/set_password")
    async def set_table_password(request: Request):
        """Set or update password for a table."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        table_id = data.get('tableId')
        password = data.get('password')
        
        if not tournament_id or not table_id or not password:
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""INSERT OR REPLACE INTO table_passwords 
                            (tournament_id, table_id, password) 
                            VALUES (?, ?, ?)""",
                        (tournament_id, table_id, password))
            conn.commit()
            
            return {"status": "success", "message": "Password set successfully"}
        finally:
            conn.close()

    @app.post("/api/table/verify_password")
    async def verify_table_password(request: Request):
        """Verify password for a table and return authentication token."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        table_id = data.get('tableId')
        password = data.get('password')
        
        if not tournament_id or not table_id or not password:
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        t_conn = get_tournament_conn(tournament_id)
        t_cursor = t_conn.cursor()
        
        try:
            t_cursor.execute("""SELECT password FROM table_passwords 
                            WHERE tournament_id = ? AND table_id = ?""",
                        (tournament_id, table_id))
            result = t_cursor.fetchone()
        finally:
            t_conn.close()
        
        password_correct = False
        if not result:
            password_correct = True
        elif result[0] == password:
            password_correct = True
        
        if password_correct:
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(hours=8)
            
            m_conn = get_master_conn()
            m_cursor = m_conn.cursor()
            try:
                m_cursor.execute("""INSERT INTO session_tokens (token, tournament_id, table_id, expires_at)
                                VALUES (?, ?, ?, ?)""",
                            (token, tournament_id, table_id, expires_at.isoformat()))
                m_conn.commit()
            finally:
                m_conn.close()
            
            return {"status": "success", "authenticated": True, "token": token}
        else:
            raise HTTPException(status_code=401, detail="Incorrect password")

    @app.get("/api/table/{table_id}/has_password")
    async def check_table_has_password(table_id: int, request: Request):
        """Check if a table requires a password."""
        # Get current tournament ID
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        tournament_id = None
        try:
            m_cursor.execute("SELECT id FROM tournaments ORDER BY created_at DESC LIMIT 1")
            tournament = m_cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
        finally:
            m_conn.close()
            
        if not tournament_id:
            return {"hasPassword": False}
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""SELECT id FROM table_passwords 
                            WHERE tournament_id = ? AND table_id = ?""",
                        (tournament_id, table_id))
            result = cursor.fetchone()
            
            return {"hasPassword": result is not None}
        finally:
            conn.close()

    @app.post("/api/table/get_token")
    async def get_table_token(request: Request):
        """Get authentication token for a table without password."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        table_id = data.get('tableId')
        
        if not tournament_id or not table_id:
            raise HTTPException(status_code=422, detail="Missing required fields")
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            # Check if table requires password
            cursor.execute("""SELECT id FROM table_passwords 
                            WHERE tournament_id = ? AND table_id = ?""",
                        (tournament_id, table_id))
            result = cursor.fetchone()
            
            if result:
                raise HTTPException(status_code=403, detail="This table requires a password")
        finally:
            conn.close()
        
        # Generate token for password-free table
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=8)
        
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        try:
            m_cursor.execute("""INSERT INTO session_tokens (token, tournament_id, table_id, expires_at)
                            VALUES (?, ?, ?, ?)""",
                        (token, tournament_id, table_id, expires_at.isoformat()))
            m_conn.commit()
            
            return {"status": "success", "token": token}
        finally:
            m_conn.close()

    @app.post("/api/tournament/advance_round")
    async def advance_round(request: Request):
        """Advance to the next round and generate new matchups using movement logic."""
        data = await request.json()
        
        tournament_id = data.get('tournamentId')
        current_round = data.get('currentRound')
        
        if not tournament_id or current_round is None:
            raise HTTPException(status_code=422, detail="Missing tournamentId or currentRound")
        
        m_conn = get_master_conn()
        m_cursor = m_conn.cursor()
        
        try:
            m_cursor.execute("""SELECT tournament_form, movement_type, num_entries, boards_per_round 
                            FROM tournaments WHERE id = ?""", (tournament_id,))
            tournament = m_cursor.fetchone()
        finally:
            m_conn.close()
        
        if not tournament:
            raise HTTPException(status_code=404, detail="Tournament not found")
        
        tournament_form, movement_type, num_entries, boards_per_round = tournament
        
        conn = get_tournament_conn(tournament_id)
        cursor = conn.cursor()
        
        try:
            # Validate that all scores for current round are entered
            cursor.execute("""SELECT COUNT(*) FROM rounds WHERE tournament_id = ? AND round_number = ?""",
                        (tournament_id, current_round))
            total_matches = cursor.fetchone()[0]
            
            expected_results = total_matches * boards_per_round
            
            cursor.execute("""SELECT COUNT(*) FROM board_results 
                            WHERE tournament_id = ? AND round_number = ?""",
                        (tournament_id, current_round))
            actual_results = cursor.fetchone()[0]
            
            if actual_results < expected_results:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Cannot advance: {actual_results} of {expected_results} board results entered. All scores must be collected first."
                )
            
            new_round = current_round + 1
            
            try:
                # Generate matchups based on movement type
                if movement_type == 'round-robin':
                    round_matchups = handle_round_robin(num_entries, new_round)
                elif movement_type == 'swiss':
                    round_matchups = handle_swiss(cursor, tournament_id, num_entries, new_round)
                else:
                    # Fallback to rotation for mitchell/howell or unknown types
                    round_matchups = handle_rotation(num_entries, new_round)
                
                # Insert new round matchups into database
                if movement_type == 'round-robin' and tournament_form == 'teams':
                    table_num = 1
                    for entry1, entry2 in round_matchups:
                        start_board = (new_round - 1) * boards_per_round + 1
                        end_board = new_round * boards_per_round
                        boards = f"{start_board}-{end_board}"

                        cursor.execute("""INSERT INTO rounds 
                                        (tournament_id, round_number, table_number, entry1_id, entry2_id, boards, status)
                                        VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                                    (tournament_id, new_round, table_num, entry1, entry2, boards))

                        table_num += 1
                        cursor.execute("""INSERT INTO rounds 
                                        (tournament_id, round_number, table_number, entry1_id, entry2_id, boards, status)
                                        VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                                    (tournament_id, new_round, table_num, entry2, entry1, boards))
                        table_num += 1
                else:
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
                raise HTTPException(status_code=500, detail=f"Error generating matchups: {str(e)}")
        finally:
            conn.close()
