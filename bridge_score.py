from fastapi import FastAPI
from fastapi.responses import FileResponse
import sqlite3
from contextlib import asynccontextmanager
import uvicorn
from database import init_master_db
from api_routes import register_api_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize master database
    init_master_db()
    yield
    # Shutdown: Nothing to close globally as we use per-request connections
    pass


app = FastAPI(lifespan=lifespan)

# Register all API routes
register_api_routes(app)

# HTML page routes
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


if __name__ == '__main__':
    uvicorn.run('bridge_score:app', host='127.0.0.1', port=8000, reload=True)

