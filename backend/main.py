from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_
from sqlalchemy.orm import Session
from math import radians, sin, cos, sqrt, atan2
from pydantic import BaseModel

from backend import models
from backend import database

database.init_db()

app = FastAPI(title="P2P Emergency Rescue Platform", version="1.6")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

CHAT_STATUSES = ("WAITING_APPROVAL", "CHATTING", "NEGOTIATING")
IGNORED_ORDERS = {}

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/login.html")

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def calculate_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 999.0
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

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

class MessageCreate(BaseModel):
    sender_id: int
    content: str

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "P2P Rescue Backend is running smoothly!"}

@app.post("/api/users")
def register_or_login(phone: str, name: str = "Thành Viên", role: str = "unified", db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == phone).first()
    if not user:
        user = models.User(phone=phone, name=name, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {
        "user_id": user.id,
        "phone": user.phone,
        "name": user.name,
        "role": user.role
    }

@app.get("/api/users/{user_id}/sos")
def get_user_sos(user_id: int, db: Session = Depends(get_db)):
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

@app.post("/api/sos")
def create_sos(user_id: int, issue_type: str, proposed_price: float, latitude: float = None, longitude: float = None, db: Session = Depends(get_db)):
    sos_request = models.SOSRequest(
        user_id=user_id,
        issue_type=issue_type,
        proposed_price=proposed_price,
        latitude=latitude,
        longitude=longitude,
        status="PENDING"
    )
    db.add(sos_request)
    db.commit()
    db.refresh(sos_request)
    return {
        "message": "Phát tín hiệu SOS thành công!",
        "sos_id": sos_request.id,
        "status": sos_request.status
    }

@app.put("/api/sos/{sos_id}/ignore")
def ignore_sos(sos_id: int, helper_id: int):
    if sos_id not in IGNORED_ORDERS:
        IGNORED_ORDERS[sos_id] = set()
    IGNORED_ORDERS[sos_id].add(helper_id)
    return {"message": "Đã ghi nhận bỏ qua đơn."}

@app.get("/api/helper/incoming-order")
def get_incoming_order(helper_id: int, lat: float = None, lon: float = None, max_distance: float = 10.0, db: Session = Depends(get_db)):
    pending_sos = db.query(models.SOSRequest).filter(models.SOSRequest.status == "PENDING").all()
    if not pending_sos:
        return {"has_order": False}

    valid_sos = []
    for s in pending_sos:
        if s.user_id == helper_id:
            continue
        if s.id in IGNORED_ORDERS and helper_id in IGNORED_ORDERS[s.id]:
            continue
        valid_sos.append(s)

    if not valid_sos:
        return {"has_order": False}

    closest_sos = None
    min_dist = 9999.0
    for sos in valid_sos:
        dist = calculate_distance(lat, lon, sos.latitude, sos.longitude)
        if dist < min_dist:
            min_dist = dist
            closest_sos = sos

    if not closest_sos or min_dist > max_distance:
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

@app.get("/api/sos/{sos_id}")
def get_sos(sos_id: int, viewer_id: int = None, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    is_participant = viewer_id is not None and (viewer_id == sos.user_id or viewer_id == sos.helper_id)
    share_info = is_participant and sos.helper_id is not None

    user_name, user_phone = get_user_info(db, sos.user_id)
    helper_name, helper_phone = get_user_info(db, sos.helper_id)

    return {
        "id": sos.id,
        "user_id": sos.user_id,
        "helper_id": sos.helper_id,
        "issue_type": sos.issue_type,
        "proposed_price": sos.proposed_price,
        "agreed_price": sos.agreed_price,
        "status": sos.status,
        "latitude": sos.latitude,
        "longitude": sos.longitude,
        "user_name": user_name,
        "user_phone": user_phone if share_info else None,
        "helper_name": helper_name if share_info else None,
        "helper_phone": helper_phone if share_info else None
    }

@app.put("/api/sos/{sos_id}/negotiate")
def negotiate_sos(sos_id: int, helper_id: int, final_price: float, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    if final_price <= 0:
        raise HTTPException(status_code=400, detail="Giá đề nghị phải lớn hơn 0!")
    if sos.user_id == helper_id:
        raise HTTPException(status_code=400, detail="Bạn không thể nhận đơn SOS của chính mình!")

    if sos.status in ("PENDING", "DISPATCHED"):
        content = f"💰 Thợ đề nghị mức giá {final_price:,.0f} VNĐ. Đang chờ khách xác nhận."
    elif sos.status in ("WAITING_APPROVAL", "CHATTING") and sos.helper_id == helper_id:
        content = f"💰 Thợ đề nghị lại mức giá {final_price:,.0f} VNĐ. Đang chờ khách xác nhận."
    else:
        raise HTTPException(status_code=400, detail="Đơn này đã có thợ khác nhận hoặc không thể đổi giá nữa!")

    sos.helper_id = helper_id
    sos.agreed_price = final_price
    sos.status = "WAITING_APPROVAL"

    db.add(models.Message(sos_id=sos_id, sender_id=helper_id, content=content))
    db.commit()
    db.refresh(sos)
    return {
        "message": "Đã gửi đề nghị giá tới người cần cứu. Đang chờ khách xác nhận!",
        "sos_id": sos.id,
        "agreed_price": sos.agreed_price,
        "status": sos.status
    }

@app.put("/api/sos/{sos_id}/respond")
def respond_sos(sos_id: int, action: str, user_id: int, expected_price: float = None, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    if sos.user_id != user_id:
        raise HTTPException(status_code=403, detail="Chỉ người cần cứu mới được đồng ý hoặc từ chối giá!")
    if sos.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail="Đơn này hiện không có đề nghị giá nào chờ duyệt!")

    if action == "ACCEPT":
        if expected_price is not None and abs(expected_price - sos.agreed_price) > 0.5:
            raise HTTPException(status_code=409, detail="Thợ vừa đổi mức giá, hãy xem lại đề nghị mới!")
        sos.status = "NEGOTIATING"
        msg_content = f"✅ Khách hàng đã ĐỒNG Ý mức giá {sos.agreed_price:,.0f} VNĐ. Tiến hành cứu hộ!"
    elif action == "REJECT":
        rejected_price = sos.agreed_price
        sos.status = "CHATTING"
        sos.agreed_price = None
        msg_content = f"❌ Khách hàng chưa đồng ý mức giá {rejected_price:,.0f} VNĐ. Hai bên có thể nhắn tin hoặc gọi điện để thỏa thuận lại."
    else:
        raise HTTPException(status_code=400, detail="Hành động không hợp lệ!")

    db.add(models.Message(sos_id=sos_id, sender_id=sos.user_id, content=msg_content))
    db.commit()
    db.refresh(sos)

    return {
        "message": "Đã cập nhật phản hồi của khách hàng!",
        "status": sos.status
    }

@app.put("/api/sos/{sos_id}/release")
def release_sos(sos_id: int, user_id: int, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, user_id)
    if sos.status not in ("WAITING_APPROVAL", "CHATTING"):
        raise HTTPException(status_code=400, detail="Chỉ có thể kết thúc thương lượng khi chưa chốt giá!")

    db.query(models.Message).filter(models.Message.sos_id == sos_id).delete()
    sos.helper_id = None
    sos.agreed_price = None
    sos.status = "PENDING"
    db.commit()
    db.refresh(sos)
    return {
        "message": "Đã kết thúc thương lượng, đơn quay lại danh sách chờ thợ.",
        "status": sos.status
    }

@app.post("/api/sos/{sos_id}/messages")
def send_message(sos_id: int, msg: MessageCreate, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, msg.sender_id)
    if sos.status == "COMPLETED":
        raise HTTPException(status_code=400, detail="Đơn đã hoàn thành, khung chat đã đóng!")
    if sos.status not in CHAT_STATUSES:
        raise HTTPException(status_code=400, detail="Khung chat chỉ mở sau khi thợ đề nghị giá!")
    content = msg.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Tin nhắn trống!")

    new_msg = models.Message(sos_id=sos_id, sender_id=msg.sender_id, content=content)
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return {
        "message": "Gửi tin nhắn thành công",
        "msg_id": new_msg.id,
        "content": new_msg.content,
        "timestamp": new_msg.timestamp
    }

@app.get("/api/sos/{sos_id}/messages")
def get_messages(sos_id: int, viewer_id: int, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, viewer_id)
    return db.query(models.Message).filter(models.Message.sos_id == sos_id).order_by(models.Message.timestamp.asc(), models.Message.id.asc()).all()

@app.put("/api/sos/{sos_id}/complete")
def complete_sos(sos_id: int, user_id: int, db: Session = Depends(get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, user_id)
    if sos.status != "NEGOTIATING":
        raise HTTPException(status_code=400, detail="Đơn chưa chốt giá hoặc đã hoàn thành!")

    sos.status = "COMPLETED"
    db.add(models.Message(sos_id=sos_id, sender_id=user_id, content="🏁 Đơn cứu hộ đã được xác nhận hoàn thành."))
    db.commit()
    db.refresh(sos)
    return {
        "message": "Đơn cứu hộ đã được hoàn thành!",
        "sos_id": sos.id,
        "status": sos.status
    }