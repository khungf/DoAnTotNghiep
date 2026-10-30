from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import ChatMessage
from pydantic import BaseModel

router = APIRouter(prefix="/api/chat", tags=["Chat & Negotiate"])

class MessageCreate(BaseModel):
    sos_id: int
    sender_id: int
    content: str

@router.post("/send")
def send_message(data: MessageCreate, db: Session = Depends(get_db)):
    msg = ChatMessage(sos_id=data.sos_id, sender_id=data.sender_id, content=data.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"status": "sent", "data": msg}

@router.get("/history/{sos_id}")
def get_history(sos_id: int, db: Session = Depends(get_db)):
    return db.query(ChatMessage).filter(ChatMessage.sos_id == sos_id).all()