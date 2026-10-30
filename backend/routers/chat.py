from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .. import models, database, auth

router = APIRouter(prefix="/api", tags=["chat"])

CHAT_STATUSES = ("WAITING_APPROVAL", "CHATTING", "NEGOTIATING")

def get_sos_or_404(db: Session, sos_id: int):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn SOS này!")
    return sos

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

class MessageCreate(BaseModel):
    content: str

@router.post("/sos/{sos_id}/messages")
def send_message(sos_id: int, msg: MessageCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Đơn đã hoàn thành, khung chat đã đóng!")
    if sos.status not in CHAT_STATUSES:
        raise HTTPException(status_code=400, detail="Khung chat chỉ mở sau khi thợ đề nghị giá!")
    content = msg.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Tin nhắn trống!")

    new_msg = models.Message(sos_id=sos_id, sender_id=current.id, content=content)
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return {
        "message": "Gửi tin nhắn thành công",
        "msg_id": new_msg.id,
        "content": new_msg.content,
        "timestamp": new_msg.timestamp
    }

@router.get("/sos/{sos_id}/messages")
def get_messages(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    viewer_id = current.id
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, viewer_id)
    return db.query(models.Message).filter(models.Message.sos_id == sos_id).order_by(models.Message.timestamp.asc(), models.Message.id.asc()).all()