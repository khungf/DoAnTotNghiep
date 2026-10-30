from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .. import models, database, auth, realtime, push
from ..database import SessionLocal

router = APIRouter(prefix="/api", tags=["chat"])
CLOSED_STATUSES = ("COMPLETED", "CANCELLED", "EXPIRED")

def get_sos_or_404(db: Session, sos_id: int):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn SOS này!")
    return sos

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

def push_chat_in_background(receiver_id, sos_id: int, sender_name: str, text: str):
    if not receiver_id or not push.push_enabled():
        return
    db = SessionLocal()
    try:
        push.send_push_to_user(db, receiver_id, f"💬 {sender_name} - đơn #{sos_id}", text, tag=f"chat-{sos_id}")
    except Exception as e:
        print(f"[PUSH] Lỗi báo tin nhắn: {e}")
    finally:
        db.close()

class MessageCreate(BaseModel):
    content: str

@router.post("/sos/{sos_id}/messages")
def send_message(sos_id: int, msg: MessageCreate, background: BackgroundTasks, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status in CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="Đơn đã kết thúc, không thể nhắn thêm!")

    content = msg.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Tin nhắn trống!")
    if len(content) > 1000:
        raise HTTPException(status_code=400, detail="Tin nhắn quá dài!")

    new_msg = models.Message(sos_id=sos_id, sender_id=current.id, content=content)
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    receiver_id = sos.helper_id if current.id == sos.user_id else sos.user_id
    realtime.sos_changed(sos)
    background.add_task(push_chat_in_background, receiver_id, sos_id, current.name or "Đối phương", content)
    return {"message": "Gửi thành công", "msg_id": new_msg.id, "content": new_msg.content, "timestamp": new_msg.timestamp}

@router.get("/sos/{sos_id}/messages")
def get_messages(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    return db.query(models.Message).filter(models.Message.sos_id == sos_id).order_by(models.Message.timestamp.asc(), models.Message.id.asc()).all()
