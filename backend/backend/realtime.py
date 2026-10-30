import asyncio
import json
from typing import Dict, Iterable, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from . import auth, models
from .database import SessionLocal

router = APIRouter(tags=["realtime"])

class ConnectionManager:
    """Quản lý kết nối WebSocket trong RAM của một tiến trình.
    Nếu chạy nhiều worker/instance, sự kiện chỉ tới được client cùng tiến trình;
    client vẫn có polling dự phòng nên dữ liệu không bị mất."""

    def __init__(self):
        self.connections: Dict[int, Set[WebSocket]] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def is_online(self, user_id) -> bool:
        return bool(self.connections.get(user_id))

    def _add(self, user_id: int, ws: WebSocket):
        self.connections.setdefault(user_id, set()).add(ws)

    def _remove(self, user_id: int, ws: WebSocket):
        sockets = self.connections.get(user_id)
        if sockets:
            sockets.discard(ws)
            if not sockets:
                self.connections.pop(user_id, None)

    async def _deliver(self, user_ids: Iterable[int], text: str):
        for user_id in list(user_ids):
            for ws in list(self.connections.get(user_id, ())):
                try:
                    await ws.send_text(text)
                except Exception:
                    self._remove(user_id, ws)

    def publish(self, user_ids: Iterable, payload: dict):
        """Gọi được từ hàm đồng bộ (endpoint sync / background task chạy trong threadpool)."""
        if self.loop is None:
            return
        ids = {u for u in user_ids if u}
        if ids:
            asyncio.run_coroutine_threadsafe(self._deliver(ids, json.dumps(payload)), self.loop)

    def broadcast(self, payload: dict, exclude: Iterable = ()):
        if self.loop is None:
            return
        skip = set(exclude)
        ids = [u for u in list(self.connections) if u not in skip]
        if ids:
            asyncio.run_coroutine_threadsafe(self._deliver(ids, json.dumps(payload)), self.loop)

manager = ConnectionManager()

def sos_changed(sos):
    manager.publish([sos.user_id, sos.helper_id], {"type": "sos_update", "sos_id": sos.id})

def _user_exists(user_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.get(models.User, user_id) is not None
    finally:
        db.close()

@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Xác thực bằng tin nhắn đầu tiên để token không nằm trên URL (tránh lộ trong log).
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        token = str(json.loads(raw).get("token", ""))
        user_id = auth.read_token(token)
        if user_id is None or not await run_in_threadpool(_user_exists, user_id):
            raise ValueError("token không hợp lệ")
    except Exception:
        await ws.close(code=4401)
        return

    manager._add(user_id, ws)
    try:
        await ws.send_text(json.dumps({"type": "ready"}))
        while True:
            message = await ws.receive_text()
            if message == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager._remove(user_id, ws)
