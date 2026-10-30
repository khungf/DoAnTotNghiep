import os
import json
import hmac
import time
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .. import models, database, auth
from ..mailer import notify_in_background
from .sos import calculate_distance, get_rating, other_party

router = APIRouter(prefix="/api", tags=["features"])

ADMIN_KEY = os.getenv("ADMIN_KEY", "")
OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
NEARBY_TTL_SECONDS = 300
NEARBY_CACHE = {}
MAX_PHOTO_CHARS = 1_500_000

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
ROUTE_TTL_SECONDS = 10
ROUTE_CACHE = {}
AVG_SPEED_KMH = 30
CLOSED_STATUSES = ("COMPLETED", "EXPIRED", "CANCELLED")
TURN_VI = {
    "left": "trái",
    "right": "phải",
    "slight left": "chếch trái",
    "slight right": "chếch phải",
    "sharp left": "gắt sang trái",
    "sharp right": "gắt sang phải",
}

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float

class ReportCreate(BaseModel):
    reported_id: Optional[int] = None
    reason: str

class VerificationSubmit(BaseModel):
    vehicle_info: str
    vehicle_photo: str = ""
    cert_photo: str = ""

class VerificationDecision(BaseModel):
    approve: bool
    note: str = ""

class ReviewCreate(BaseModel):
    rating: int
    comment: str = ""

def get_sos_or_404(db: Session, sos_id: int):
    sos = db.query(models.SOSRequest).filter(models.SOSRequest.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn SOS này!")
    return sos

def require_participant(sos, user_id: int):
    if user_id != sos.user_id and user_id != sos.helper_id:
        raise HTTPException(status_code=403, detail="Bạn không thuộc đơn cứu hộ này!")

def require_admin(x_admin_key: str = Header(default="")):
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Server chưa cấu hình ADMIN_KEY!")
    if not hmac.compare_digest(x_admin_key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(status_code=403, detail="Sai mã quản trị!")

def check_photo(value: str, label: str, required: bool):
    value = value.strip()
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"Hãy tải lên {label}!")
        return ""
    if not value.startswith("data:image/"):
        raise HTTPException(status_code=400, detail=f"{label} không hợp lệ!")
    if len(value) > MAX_PHOTO_CHARS:
        raise HTTPException(status_code=400, detail=f"{label} quá lớn, hãy chọn ảnh nhỏ hơn!")
    return value

def fetch_nearby(lat: float, lon: float, radius: int):
    around = f"(around:{radius},{lat},{lon})"
    query = (
        "[out:json][timeout:20];("
        f'node{around}["amenity"="fuel"];way{around}["amenity"="fuel"];'
        f'node{around}["shop"="car_repair"];way{around}["shop"="car_repair"];'
        f'node{around}["shop"="motorcycle_repair"];way{around}["shop"="motorcycle_repair"];'
        ");out center 120;"
    )
    data = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": "P2P-SOS/2.3"}, method="POST")
    with urllib.request.urlopen(request, timeout=25) as res:
        return json.loads(res.read().decode()).get("elements", [])

def describe_place(tags: dict):
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    parts = [x for x in (street, tags.get("addr:suburb") or tags.get("addr:district"), tags.get("addr:city")) if x]
    return ", ".join(parts)

@router.put("/helper/location")
def update_helper_location(body: LocationUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    current.current_lat = body.latitude
    current.current_lon = body.longitude
    db.commit()
    return {"message": "Đã cập nhật vị trí thợ."}

@router.get("/sos/{sos_id}/helper-location")
def get_helper_location(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if not sos.helper_id:
        raise HTTPException(status_code=404, detail="Đơn chưa có thợ nhận.")
    helper = db.query(models.User).filter(models.User.id == sos.helper_id).first()
    if not helper:
        raise HTTPException(status_code=404, detail="Không tìm thấy thợ.")
    return {"latitude": helper.current_lat, "longitude": helper.current_lon}

def describe_step(step: dict):
    maneuver = step.get("maneuver", {})
    kind = maneuver.get("type", "")
    modifier = maneuver.get("modifier", "")
    name = step.get("name") or ""
    onto = f" vào {name}" if name else ""
    if kind == "depart":
        return "Xuất phát" + (f" trên {name}" if name else "")
    if kind == "arrive":
        return "Bạn đã tới điểm của khách"
    if kind in ("roundabout", "rotary", "roundabout turn"):
        exit_no = maneuver.get("exit")
        return f"Vào vòng xuyến, ra lối thứ {exit_no}{onto}" if exit_no else f"Đi qua vòng xuyến{onto}"
    if modifier == "uturn":
        return "Quay đầu xe"
    if modifier in TURN_VI:
        return f"Rẽ {TURN_VI[modifier]}{onto}"
    return "Đi thẳng" + (f" trên {name}" if name else "")

def fetch_route(from_lat: float, from_lon: float, to_lat: float, to_lon: float):
    url = (
        f"{OSRM_URL}/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}"
        "?overview=full&geometries=geojson&steps=true"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "P2P-SOS/2.3"})
    with urllib.request.urlopen(request, timeout=15) as res:
        data = json.loads(res.read().decode())
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("OSRM không tìm được đường đi")
    route = data["routes"][0]

    steps = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            lon, lat = step["maneuver"]["location"]
            steps.append({
                "instruction": describe_step(step),
                "distance_m": round(step.get("distance", 0)),
                "lat": lat,
                "lon": lon,
            })
    return {
        "distance_km": round(route["distance"] / 1000, 2),
        "duration_min": max(1, round(route["duration"] / 60)),
        "coordinates": [[c[1], c[0]] for c in route["geometry"]["coordinates"]],
        "steps": steps,
        "approximate": False,
    }

def straight_line_route(from_lat: float, from_lon: float, to_lat: float, to_lon: float):
    km = calculate_distance(from_lat, from_lon, to_lat, to_lon)
    return {
        "distance_km": round(km, 2),
        "duration_min": max(1, round(km / AVG_SPEED_KMH * 60)),
        "coordinates": [[from_lat, from_lon], [to_lat, to_lon]],
        "steps": [],
        "approximate": True,
    }

@router.get("/sos/{sos_id}/route")
def get_route_to_victim(sos_id: int, lat: Optional[float] = None, lon: Optional[float] = None, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    if sos.helper_id != current.id:
        raise HTTPException(status_code=403, detail="Chỉ thợ đã nhận đơn mới xem được chỉ đường!")
    if sos.status in CLOSED_STATUSES:
        raise HTTPException(status_code=400, detail="Đơn đã kết thúc, không còn chỉ đường!")
    if sos.latitude is None or sos.longitude is None:
        raise HTTPException(status_code=400, detail="Khách không chia sẻ vị trí nên chưa thể chỉ đường!")

    if lat is None or lon is None:
        lat, lon = current.current_lat, current.current_lon
    if lat is None or lon is None:
        raise HTTPException(status_code=400, detail="Chưa có vị trí của bạn, hãy bật GPS!")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Tọa độ không hợp lệ!")

    key = (sos_id, round(lat, 4), round(lon, 4))
    cached = ROUTE_CACHE.get(key)
    if cached and time.time() - cached[0] < ROUTE_TTL_SECONDS:
        return cached[1]

    try:
        result = fetch_route(lat, lon, sos.latitude, sos.longitude)
        ROUTE_CACHE[key] = (time.time(), result)
        if len(ROUTE_CACHE) > 500:
            ROUTE_CACHE.clear()
    except (OSError, ValueError, KeyError, IndexError):
        result = straight_line_route(lat, lon, sos.latitude, sos.longitude)

    return {**result, "destination": {"lat": sos.latitude, "lon": sos.longitude}}

@router.get("/nearby-services")
def get_nearby_services(lat: float, lon: float, radius: int = 3000, current: models.User = Depends(auth.get_current_user)):
    radius = max(500, min(radius, 10000))
    key = (round(lat, 3), round(lon, 3), radius)
    cached = NEARBY_CACHE.get(key)
    if cached and time.time() - cached[0] < NEARBY_TTL_SECONDS:
        return cached[1]

    try:
        elements = fetch_nearby(lat, lon, radius)
    except (OSError, ValueError):
        if cached:
            return cached[1]
        raise HTTPException(status_code=503, detail="Không tải được dữ liệu địa điểm, vui lòng thử lại sau!")

    places = []
    for el in elements:
        tags = el.get("tags", {})
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        is_fuel = tags.get("amenity") == "fuel"
        place_type = "Trạm xăng" if is_fuel else "Sửa xe"
        name = tags.get("name") or tags.get("brand") or tags.get("operator") or ("Cây xăng" if is_fuel else "Tiệm sửa xe")
        phone = (tags.get("phone") or tags.get("contact:phone") or "").split(";")[0].strip()
        places.append({
            "name": name,
            "type": place_type,
            "phone": phone,
            "address": describe_place(tags),
            "distance_km": round(calculate_distance(lat, lon, plat, plon), 2),
            "lat": plat,
            "lon": plon,
        })

    places.sort(key=lambda p: p["distance_km"])
    places = places[:20]
    NEARBY_CACHE[key] = (time.time(), places)
    if len(NEARBY_CACHE) > 200:
        NEARBY_CACHE.clear()
    return places

@router.post("/sos/{sos_id}/report")
def report_incident(sos_id: int, body: ReportCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Nội dung báo cáo trống!")
    reported_id = body.reported_id
    if reported_id is None:
        reported_id = other_party(sos, current.id)
    report = models.UserReport(reporter_id=current.id, reported_id=reported_id, sos_id=sos_id, reason=reason)
    db.add(report)
    db.commit()
    return {"message": "Đã ghi nhận báo cáo an toàn."}

@router.get("/helper/verification")
def get_verification(current: models.User = Depends(auth.get_current_user)):
    return {
        "status": current.verification_status or "NONE",
        "vehicle_info": current.vehicle_info,
        "note": current.verification_note,
    }

@router.post("/helper/verify-submit")
def submit_verification(body: VerificationSubmit, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    if current.verification_status == "PENDING":
        raise HTTPException(status_code=400, detail="Hồ sơ của bạn đang chờ duyệt!")
    if current.verification_status == "APPROVED":
        raise HTTPException(status_code=400, detail="Hồ sơ của bạn đã được duyệt!")
    vehicle_info = body.vehicle_info.strip()
    if not vehicle_info:
        raise HTTPException(status_code=400, detail="Hãy nhập thông tin xe!")
    current.vehicle_info = vehicle_info
    current.vehicle_photo = check_photo(body.vehicle_photo, "ảnh xe", True)
    current.cert_photo = check_photo(body.cert_photo, "ảnh giấy tờ", False)
    current.verification_status = "PENDING"
    current.verification_note = None
    db.commit()
    return {"message": "Đã gửi hồ sơ xác minh.", "status": current.verification_status}

@router.get("/admin/verifications")
def admin_list_verifications(status: str = "PENDING", _: None = Depends(require_admin), db: Session = Depends(database.get_db)):
    rows = db.query(models.User).filter(models.User.verification_status == status).order_by(models.User.id.asc()).limit(50).all()
    return [
        {
            "user_id": u.id,
            "name": u.name,
            "phone": u.phone,
            "vehicle_info": u.vehicle_info,
            "vehicle_photo": u.vehicle_photo,
            "cert_photo": u.cert_photo,
            "status": u.verification_status,
        }
        for u in rows
    ]

@router.post("/admin/verifications/{user_id}")
def admin_decide_verification(user_id: int, body: VerificationDecision, background: BackgroundTasks, _: None = Depends(require_admin), db: Session = Depends(database.get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng!")
    if user.verification_status != "PENDING":
        raise HTTPException(status_code=400, detail="Hồ sơ này không ở trạng thái chờ duyệt!")
    note = body.note.strip()
    user.verification_status = "APPROVED" if body.approve else "REJECTED"
    user.verification_note = note or None
    db.commit()
    if body.approve:
        message = "Hồ sơ thợ cứu hộ của bạn đã được duyệt."
    else:
        message = "Hồ sơ thợ cứu hộ của bạn chưa được duyệt." + (f" Lý do: {note}" if note else "")
    background.add_task(notify_in_background, user.id, "Kết quả xác minh thợ cứu hộ", message)
    return {"message": "Đã cập nhật hồ sơ.", "status": user.verification_status}

@router.get("/sos/{sos_id}/review")
def get_my_review(sos_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    review = db.query(models.Review).filter(models.Review.sos_id == sos_id, models.Review.reviewer_id == current.id).first()
    if not review:
        return {"reviewed": False}
    return {"reviewed": True, "rating": review.rating, "comment": review.comment}

@router.post("/sos/{sos_id}/review")
def create_review(sos_id: int, body: ReviewCreate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    require_participant(sos, current.id)
    if sos.status != "COMPLETED":
        raise HTTPException(status_code=400, detail="Chỉ đánh giá được đơn đã hoàn thành!")
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(status_code=400, detail="Điểm đánh giá phải từ 1 đến 5!")
    existing = db.query(models.Review).filter(models.Review.sos_id == sos_id, models.Review.reviewer_id == current.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bạn đã đánh giá đơn này rồi!")
    target_id = other_party(sos, current.id)
    if target_id is None:
        raise HTTPException(status_code=400, detail="Đơn chưa có đối phương để đánh giá!")
    db.add(models.Review(sos_id=sos_id, reviewer_id=current.id, target_id=target_id, rating=body.rating, comment=body.comment.strip()[:500] or None))
    db.commit()
    return {"message": "Cảm ơn bạn đã đánh giá!"}

@router.get("/users/{user_id}/rating")
def get_user_rating(user_id: int, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    average, count = get_rating(db, user_id)
    return {"average": average, "count": count}