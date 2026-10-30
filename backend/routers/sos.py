import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timedelta
from pydantic import BaseModel

from .. import models, database, auth
from ..mailer import notify_in_background

router = APIRouter(prefix="/api", tags=["sos"])

CLOSED_STATUSES = ("COMPLETED", "EXPIRED", "CANCELLED")
REQUIRE_VERIFIED_HELPER = os.getenv("REQUIRE_VERIFIED_HELPER", "0") == "1"

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def get_sos_or_404(db: Session, sos_id: int):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn SOS này!")
    return sos

def get_user_info(db: Session, user_id):
    if user_id is None:
        return None, None
    user = db.query(models.User).filter(models.User.id == user_id).first()
    return (user.name, user.phone) if user else (None, None)

def get_rating(db: Session, user_id):
    if user_id is None:
        return None, 0
    avg, count = db.query(func.avg(models.Review.rating), func.count(models.Review.id)).filter(models.Review.target_id == user_id).one()
    return (round(float(avg), 1) if avg is not None else None), int(count or 0)

def other_party(sos, user_id: int):
    return sos.helper_id if user_id == sos.user_id else sos.user_id

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

def check_expired_sos(db: Session):
    expiration_threshold = datetime.utcnow() - timedelta(minutes=15)
    pending_sos = db.query(models.SOSRequest).filter(
        models.SOSRequest.status == "PENDING",
        models.SOSRequest.created_at < expiration_threshold
    ).all()
    for sos in pending_sos:
        sos.status = "EXPIRED"
    if pending_sos:
        db.commit()

class CancelRequest(BaseModel):
    reason: str

@router.get("/users/{user_id}/sos")
def get_user_sos(user_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    if user_id != current.id:
        raise HTTPException(status_code=403, detail="Bạn chỉ được xem đơn của chính mình!")
    check_expired_sos(db)
    rows = db.query(models.SOSRequest).filter(
        or_(models.SOSRequest.user_id == user_id, models.SOSRequest.helper_id == user_id)
    ).order_by(models.SOSRequest.id.desc()).limit(20).all()
    return [
        {
            "id": s.id,
            "role": "Khách" if s.user_id == user_id else "Thợ",
            "issue_type": s.issue_type,
            "proposed_price": s.proposed_price,
            "agreed_price": s.agreed_price,
            "status": s.status
        }
        for s in rows
    ]

@router.post("/sos")
def create_sos(issue_type: str, proposed_price: float, latitude: float = None, longitude: float = None, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    issue_type = issue_type.strip()
    if not issue_type:
        raise HTTPException(status_code=400, detail="Hãy mô tả sự cố!")
    if proposed_price <= 0:
        raise HTTPException(status_code=400, detail="Giá đề xuất phải lớn hơn 0!")
    sos_request = models.SOSRequest(
        user_id=current.id,
        issue_type=issue_type,
        proposed_price=proposed_price,
        latitude=latitude,
        longitude=longitude,
        status="PENDING"
    )
    db.add(sos_request)
    db.commit()
    db.refresh(sos_request)
    return {"message": "Phát tín hiệu SOS thành công!", "sos_id": sos_request.id, "status": sos_request.status}

@router.put("/sos/{sos_id}/ignore")
def ignore_sos(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    get_sos_or_404(db, sos_id)
    exists = db.query(models.IgnoredOrder).filter(
        models.IgnoredOrder.sos_id == sos_id,
        models.IgnoredOrder.helper_id == current.id
    ).first()
    if not exists:
        db.add(models.IgnoredOrder(sos_id=sos_id, helper_id=current.id))
        db.commit()
    return {"message": "Đã ghi nhận bỏ qua đơn."}

@router.get("/helper/incoming-order")
def get_incoming_order(lat: float = None, lon: float = None, max_distance: float = 10.0, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    check_expired_sos(db)
    helper_id = current.id
    if REQUIRE_VERIFIED_HELPER and current.verification_status != "APPROVED":
        return {"has_order": False}

    ignored = {row[0] for row in db.query(models.IgnoredOrder.sos_id).filter(models.IgnoredOrder.helper_id == helper_id).all()}
    pending_sos = db.query(models.SOSRequest).filter(models.SOSRequest.status == "PENDING").all()

    closest_sos = None
    min_dist = None
    for sos in pending_sos:
        if sos.user_id == helper_id or sos.id in ignored:
            continue
        if None in (lat, lon, sos.latitude, sos.longitude):
            dist = 0.0
        else:
            dist = calculate_distance(lat, lon, sos.latitude, sos.longitude)
        if dist > max_distance:
            continue
        if min_dist is None or dist < min_dist:
            min_dist = dist
            closest_sos = sos

    if not closest_sos:
        return {"has_order": False}

    user_name, _ = get_user_info(db, closest_sos.user_id)
    return {
        "has_order": True,
        "sos_id": closest_sos.id,
        "user_name": user_name or "Khách hàng",
        "issue_type": closest_sos.issue_type,
        "proposed_price": closest_sos.proposed_price,
        "distance_km": round(min_dist, 2),
        "latitude": closest_sos.latitude,
        "longitude": closest_sos.longitude
    }

@router.get("/sos/{sos_id}")
def get_sos(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    check_expired_sos(db)
    viewer_id = current.id
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, viewer_id)
    share_info = sos.helper_id is not None

    user_name, user_phone = get_user_info(db, sos.user_id)
    helper_name, helper_phone = get_user_info(db, sos.helper_id)
    helper = db.get(models.User, sos.helper_id) if sos.helper_id else None
    helper_rating, helper_review_count = get_rating(db, sos.helper_id)
    user_rating, user_review_count = get_rating(db, sos.user_id)

    return {
        "id": sos.id, "user_id": sos.user_id, "helper_id": sos.helper_id,
        "issue_type": sos.issue_type, "proposed_price": sos.proposed_price, "agreed_price": sos.agreed_price,
        "status": sos.status, "latitude": sos.latitude, "longitude": sos.longitude,
        "user_name": user_name, "user_phone": user_phone if share_info else None,
        "helper_name": helper_name if share_info else None, "helper_phone": helper_phone if share_info else None,
        "helper_verified": bool(helper and helper.verification_status == "APPROVED"),
        "helper_rating": helper_rating, "helper_review_count": helper_review_count,
        "user_rating": user_rating, "user_review_count": user_review_count
    }

@router.put("/sos/{sos_id}/negotiate")
def negotiate_sos(sos_id: int, final_price: float, background: BackgroundTasks, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    helper_id = current.id
    sos = get_sos_or_404(db, sos_id)
    if final_price <= 0:
        raise HTTPException(status_code=400, detail="Giá đề nghị phải lớn hơn 0!")
    if sos.user_id == helper_id:
        raise HTTPException(status_code=400, detail="Bạn không thể nhận đơn SOS của chính mình!")
    if sos.status in CLOSED_STATUSES or sos.status == "NEGOTIATING":
        raise HTTPException(status_code=400, detail="Đơn này không thể nhận nữa!")
    if sos.helper_id is not None and sos.helper_id != helper_id:
        raise HTTPException(status_code=400, detail="Đơn đã có thợ khác nhận!")

    if REQUIRE_VERIFIED_HELPER and current.verification_status != "APPROVED":
        raise HTTPException(status_code=403, detail="Bạn cần được xác minh hồ sơ thợ trước khi nhận đơn!")

    sos.helper_id = helper_id
    sos.agreed_price = final_price
    sos.status = "WAITING_APPROVAL"

    db.add(models.Message(sos_id=sos_id, sender_id=helper_id, content=f"💰 Thợ đề nghị mức giá {final_price:,.0f} VNĐ. Đang chờ khách xác nhận."))
    db.commit()
    background.add_task(notify_in_background, sos.user_id, f"Đơn SOS #{sos.id}: thợ đề nghị giá", f"Thợ cứu hộ đề nghị mức giá {final_price:,.0f} VNĐ cho đơn #{sos.id}.")
    return {"message": "Đã gửi đề nghị giá!", "status": sos.status}

@router.put("/sos/{sos_id}/respond")
def respond_sos(sos_id: int, action: str, background: BackgroundTasks, expected_price: float = None, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    if sos.user_id != current.id:
        raise HTTPException(status_code=403, detail="Chỉ người cần cứu mới được phản hồi giá!")
    if sos.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail="Đơn không ở trạng thái chờ xác nhận giá!")
    if action not in ("ACCEPT", "REJECT"):
        raise HTTPException(status_code=400, detail="Hành động không hợp lệ!")

    if action == "ACCEPT":
        sos.status = "NEGOTIATING"
        msg = f"✅ Khách đã ĐỒNG Ý mức giá {sos.agreed_price:,.0f} VNĐ."
    else:
        sos.status = "CHATTING"
        sos.agreed_price = None
        msg = "❌ Khách chưa đồng ý giá, thương lượng lại."

    db.add(models.Message(sos_id=sos_id, sender_id=sos.user_id, content=msg))
    db.commit()
    background.add_task(notify_in_background, sos.helper_id, f"Đơn SOS #{sos.id}: khách đã phản hồi giá", msg)
    return {"message": "Đã cập nhật!", "status": sos.status}

@router.put("/sos/{sos_id}/complete")
def complete_sos(sos_id: int, background: BackgroundTasks, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status != "NEGOTIATING":
        raise HTTPException(status_code=400, detail="Chỉ hoàn thành được đơn đã thống nhất giá!")
    sos.status = "COMPLETED"
    db.add(models.Message(sos_id=sos_id, sender_id=current.id, content="🏁 Đơn cứu hộ đã được xác nhận hoàn thành."))
    db.commit()
    background.add_task(notify_in_background, other_party(sos, current.id), f"Đơn SOS #{sos.id} đã hoàn thành", f"Đơn cứu hộ #{sos.id} đã được xác nhận hoàn thành. Hãy đánh giá đối phương trong ứng dụng.")
    return {"message": "Hoàn thành đơn!", "status": sos.status}

@router.put("/sos/{sos_id}/cancel")
def cancel_sos(sos_id: int, body: CancelRequest, background: BackgroundTasks, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status in CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="Đơn này không thể hủy nữa!")

    sos.status = "CANCELLED"
    sos.cancel_reason = body.reason.strip()
    sos.cancelled_by = current.id

    role_name = "Khách hàng" if current.id == sos.user_id else "Thợ cứu hộ"
    db.add(models.Message(sos_id=sos_id, sender_id=current.id, content=f"🚫 {role_name} đã hủy đơn. Lý do: {sos.cancel_reason}"))
    db.commit()
    background.add_task(notify_in_background, other_party(sos, current.id), f"Đơn SOS #{sos.id} đã bị hủy", f"{role_name} đã hủy đơn #{sos.id}. Lý do: {sos.cancel_reason}")
    return {"message": "Đã hủy đơn thành công.", "status": sos.status}