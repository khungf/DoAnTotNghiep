from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import SOSRequest
from pydantic import BaseModel

router = APIRouter(prefix="/api/sos", tags=["SOS"])

class SOSCreate(BaseModel):
    user_id: int
    lat: float
    lng: float
    description: str
    level: str = "Trung bình"

@router.post("/create")
def create_sos(data: SOSCreate, db: Session = Depends(get_db)):
    new_sos = SOSRequest(
        user_id=data.user_id,
        lat=data.lat,
        lng=data.lng,
        description=data.description,
        level=data.level,
        status="Pending"
    )
    db.add(new_sos)
    db.commit()
    db.refresh(new_sos)
    return {"status": "success", "data": new_sos}

@router.get("/list")
def list_sos(db: Session = Depends(get_db)):
    return db.query(SOSRequest).all()

@router.post("/{sos_id}/complete")
def complete_sos(sos_id: int, db: Session = Depends(get_db)):
    sos = db.query(SOSRequest).filter(SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")
    sos.status = "Completed"
    db.commit()
    return {"status": "success", "message": f"Đã hoàn thành SOS {sos_id}"}