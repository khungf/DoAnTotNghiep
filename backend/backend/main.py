import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from . import database, auth, realtime
from .routers import sos, chat, features, payment

database.init_db()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    realtime.manager.loop = asyncio.get_running_loop()
    yield

app = FastAPI(title="P2P Emergency Rescue Platform", version="3.0", lifespan=lifespan)

# Giao diện được phục vụ cùng domain với API nên mặc định KHÔNG cần CORS.
# Chỉ khi cần web khác gọi API, đặt ALLOWED_ORIGINS="https://a.com,https://b.com".
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
    )

app.include_router(auth.router)
app.include_router(sos.router)
app.include_router(chat.router)
app.include_router(features.router)
app.include_router(payment.router)
app.include_router(realtime.router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/login.html")

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "P2P Rescue Backend is running smoothly!"}