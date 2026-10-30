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

class ReviewCreate(BaseModel):
    rating: int
    comment: str = ""

class ReportCreate(BaseModel):
    reported_id: int = None
    reason: str

class VerificationSubmit(BaseModel):
    vehicle_info: str
    vehicle_photo: str = ""
    cert_photo: str = ""

@router.post("/sos/{sos_id}/review")
def create_review(sos_id: int, body: ReviewCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    if not (1 <= body.rating <= 5):
        raise HTTPException(status_code=400, detail="Số sao đánh giá phải từ 1 đến 5!")
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Chỉ có thể đánh giá khi đơn đã hoàn thành!")
    
    target_id = sos.helper_id if current.id == sos.user_id else sos.user_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Không tìm thấy đối phương để đánh giá!")

    existing = db.query(models.Review).filter(
        models.Review.sos_id == sos_id,
        models.Review.reviewer_id == current.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bạn đã đánh giá đơn này rồi!")

    review = models.Review(
        sos_id=sos_id,
        reviewer_id=current.id,
        target_id=target_id,
        rating=body.rating,
        comment=body.comment.strip()
    )
    db.add(review)
    db.commit()
    return {"message": "Đã gửi đánh giá thành công! Cảm ơn bạn."}

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

@router.post("/helper/verify-submit")
def submit_verification(body: VerificationSubmit, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.vehicle_info = body.vehicle_info.strip()
    current.vehicle_photo = body.vehicle_photo.strip()
    current.cert_photo = body.cert_photo.strip()
    current.verification_status = "PENDING"
    db.commit()
    return {"message": "Đã gửi hồ sơ xác minh, hệ thống sẽ duyệt trong thời gian sớm nhất.", "status": current.verification_status}