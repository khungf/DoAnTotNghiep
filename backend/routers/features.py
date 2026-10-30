from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .. import models, database, auth

router = APIRouter(prefix="/api", tags=["features"])

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float

class ReportCreate(BaseModel):
    reported_id: int = None
    reason: str

class VerificationSubmit(BaseModel):
    vehicle_info: str
    vehicle_photo: str = ""
    cert_photo: str = ""

@router.put("/helper/location")
def update_helper_location(body: LocationUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.current_lat = body.latitude
    current.current_lon = body.longitude
    db.commit()
    return {"message": "Đã cập nhật vị trí thợ."}

@router.get("/sos/{sos_id}/helper-location")
def get_helper_location(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos or not sos.helper_id:
        raise HTTPException(status_code=404, detail="Đơn chưa có thợ nhận.")
    helper = db.query(models.User).filter(models.User.id == sos.helper_id).first()
    return {"latitude": helper.current_lat, "longitude": helper.current_lon}

@router.get("/nearby-services")
def get_nearby_services(lat: float, lon: float):
    return [
        {"name": "Cây xăng Petrolimex", "type": "Trạm xăng", "phone": "19001234", "address": "Cách bạn ~500m", "lat": lat + 0.003, "lon": lon + 0.002},
        {"name": "Tiệm Sửa Xe Cứu Hộ", "type": "Sửa xe", "phone": "0908123456", "address": "Cách bạn ~1.2km", "lat": lat - 0.004, "lon": lon + 0.005}
    ]

@router.post("/sos/{sos_id}/report")
def report_incident(sos_id: int, body: ReportCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    report = models.UserReport(reporter_id=current.id, reported_id=body.reported_id, sos_id=sos_id, reason=body.reason.strip())
    db.add(report)
    db.commit()
    return {"message": "Đã ghi nhận báo cáo an toàn."}

@router.post("/helper/verify-submit")
def submit_verification(body: VerificationSubmit, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.vehicle_info = body.vehicle_info.strip()
    current.vehicle_photo = body.vehicle_photo.strip()
    current.cert_photo = body.cert_photo.strip()
    current.verification_status = "PENDING"
    db.commit()
    return {"message": "Đã gửi hồ sơ xác minh.", "status": current.verification_status}