from fastapi import HTTPException, Request
from datetime import datetime
from database import get_master_conn


async def verify_token(request: Request) -> dict:
    """Dependency to verify authentication token."""
    # Get token from Authorization header
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization token")
    
    token = auth_header.replace('Bearer ', '')
    
    conn = get_master_conn()
    cursor = conn.cursor()
    
    try:
        # Check if token exists and is not expired
        cursor.execute("""SELECT tournament_id, table_id, expires_at FROM session_tokens 
                          WHERE token = ?""", (token,))
        result = cursor.fetchone()
    finally:
        conn.close()
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    
    tournament_id, table_id, expires_at = result
    
    # Check if token is expired
    if datetime.fromisoformat(expires_at) < datetime.now():
        raise HTTPException(status_code=401, detail="Authentication token expired")
    
    return {"tournament_id": tournament_id, "table_id": table_id, "token": token}
