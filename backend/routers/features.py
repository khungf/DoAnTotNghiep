from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .. import models, database, auth

router = APIRouter(prefix="/api", tags=["features"])

def get_sos_or_404(db: Session, sos_id: int):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn SOS này!")
    return sos

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

class ReportCreate(BaseModel):
    reported_id: int = None
    reason: str

# Tính năng 4: Báo cáo an toàn người dùng
@router.post("/sos/{sos_id}/report")
def report_incident(sos_id: int, body: ReportCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    
    report = models.UserReport(
        reporter_id=current.id,
        reported_id=body.reported_id,
        sos_id=sos_id,
        reason=body.reason.strip()
    )
    db.add(report)
    db.commit()
    return {"message": "Đã ghi nhận báo cáo an toàn. Đội ngũ hỗ trợ sẽ kiểm tra ngay lập tức."}