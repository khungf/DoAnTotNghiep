from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from . import database, auth
from .routers import sos, chat, features

database.init_db()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="P2P Emergency Rescue Platform", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sos.router)
app.include_router(chat.router)
app.include_router(features.router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/login.html")

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "P2P Rescue Backend is running smoothly!"}