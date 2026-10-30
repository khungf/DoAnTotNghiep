from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional

from .. import models, database, auth
from ..mailer import send_email

router = APIRouter(prefix="/api", tags=["features"])

# --- DTO SCHEMAS ---
class LocationUpdate(BaseModel):
    latitude: float
    longitude: float

class EmergencyContactsUpdate(BaseModel):
    contacts: str  # Ví dụ: "0901234567, 0909876543"

class EKYCSubmit(BaseModel):
    id_card_number: str
    id_card_photo: str
    vehicle_info: str
    vehicle_photo: str = ""
    cert_photo: str = ""

class FcmTokenUpdate(BaseModel):
    fcm_token: str

# 1. LIVE TRACKING: Thợ cập nhật vị trí thời gian thực
@router.put("/helper/location")
def update_helper_location(body: LocationUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.current_lat = body.latitude
    current.current_lon = body.longitude
    current.last_active = datetime.utcnow()
    db.commit()
    return {"message": "Đã cập nhật vị trí thợ."}

# 1. LIVE TRACKING: Khách lấy vị trí di chuyển thời gian thực của thợ
@router.get("/sos/{sos_id}/helper-location")
def get_helper_location(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos or not sos.helper_id:
        raise HTTPException(status_code=404, detail="Đơn hàng chưa có thợ nhận.")
    
    helper = db.query(models.User).filter(models.User.id == sos.helper_id).first()
    return {
        "helper_id": helper.id,
        "latitude": helper.current_lat,
        "longitude": helper.current_lon,
        "last_active": helper.last_active
    }

# 1. GỢI Ý TRẠM XĂNG / SỬA XE GẦN NHẤT (Dữ liệu cố định / Cứu hộ liên kết)
@router.get("/nearby-services")
def get_nearby_services(lat: float, lon: float):
    # Trả về danh sách trạm xăng & tiệm cứu hộ mặc định trong bán kính
    return [
        {"name": "Cây xăng Petrolimex Số 1", "type": "gas_station", "phone": "19001234", "address": "Cách bạn ~500m", "lat": lat + 0.003, "lon": lon + 0.002},
        {"name": "Tiệm Sửa Xe Cứu Hộ 24/7 Sài Gòn", "type": "repair_shop", "phone": "0908123456", "address": "Cách bạn ~1.2km", "lat": lat - 0.004, "lon": lon + 0.005},
        {"name": "Trung Tâm Cứu Hộ Giao Thông Khẩn Cấp", "type": "rescue_center", "phone": "115", "address": "Toàn khu vực", "lat": lat + 0.01, "lon": lon - 0.01}
    ]

# 3. eKYC: Xác minh CCCD & Giấy tờ
@router.post("/helper/ekyc-submit")
def submit_ekyc(body: EKYCSubmit, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.id_card_number = body.id_card_number.strip()
    current.id_card_photo = body.id_card_photo.strip()
    current.vehicle_info = body.vehicle_info.strip()
    current.vehicle_photo = body.vehicle_photo.strip()
    current.cert_photo = body.cert_photo.strip()
    current.verification_status = "PENDING"
    db.commit()
    return {"message": "Đã gửi hồ sơ eKYC. Quản trị viên sẽ phê duyệt trong 24h.", "status": current.verification_status}

# 3. THÂN NHÂN: Cập nhật danh sách số điện thoại khẩn cấp
@router.post("/user/emergency-contacts")
def set_emergency_contacts(body: EmergencyContactsUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.emergency_contacts = body.contacts.strip()
    db.commit()
    return {"message": "Đã lưu số điện thoại thân nhân thành công."}

# 3. THÂN NHÂN: Gửi tín hiệu báo nguy tới thân nhân
@router.post("/sos/{sos_id}/notify-relatives")
def notify_relatives(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not current.emergency_contacts:
        raise HTTPException(status_code=400, detail="Bạn chưa cấu hình số điện thoại thân nhân!")
    
    location_link = f"https://www.google.com/maps?q={sos.latitude},{sos.longitude}" if sos.latitude else "Chưa xác định"
    msg = f"[CẢNH BÁO SOS] Người thân của bạn ({current.name} - {current.phone}) đang gặp sự cố '{sos.issue_type}'. Vị trí: {location_link}"
    
    # Mô phỏng gửi SMS/Email tới thân nhân
    print(f"[EMERGENCY SMS SENT TO {current.emergency_contacts}]: {msg}")
    return {"message": f"Đã phát tin nhắn SOS kèm vị trí GPS tới thân nhân ({current.emergency_contacts})!"}

# 4. DASHBOARD THỢ: Thống kê thu nhập & Đánh giá
@router.get("/helper/dashboard")
def get_helper_dashboard(current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    completed_orders = db.query(models.SOSRequest).filter(
        models.SOSRequest.helper_id == current.id,
        models.SOSRequest.status == "COMPLETED"
    ).all()
    
    total_earnings = sum(s.agreed_price or s.proposed_price for s in completed_orders)
    
    reviews = db.query(models.Review).filter(models.Review.target_id == current.id).all()
    avg_rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 5.0
    
    return {
        "total_completed": len(completed_orders),
        "total_earnings": total_earnings,
        "average_rating": avg_rating,
        "total_reviews": len(reviews),
        "verification_status": current.verification_status
    }

# 4. ADMIN: Màn hình quản trị hệ thống
@router.get("/admin/pending-verifications")
def get_pending_verifications(current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ Admin mới có quyền truy cập!")
    return db.query(models.User).filter(models.User.verification_status == "PENDING").all()

@router.put("/admin/verify-user/{user_id}")
def approve_user_verification(user_id: int, approve: bool, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ Admin mới có quyền truy cập!")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    
    user.verification_status = "APPROVED" if approve else "REJECTED"
    user.is_verified = approve
    db.commit()
    return {"message": f"Đã {'duyệt' if approve else 'từ chối'} hồ sơ của {user.name}."}

# 5. FCM PUSH NOTIFICATION: Đăng ký Token
@router.post("/user/fcm-token")
def save_fcm_token(body: FcmTokenUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.fcm_token = body.fcm_token
    db.commit()
    return {"message": "Đã lưu FCM Token cho thông báo đẩy."}