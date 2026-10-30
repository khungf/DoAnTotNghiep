import os
import re
import json
import hmac
import hashlib
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .mailer import send_email, MailError

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

if not DEV_MODE and (SECRET_KEY == "dev-secret-change-me" or len(SECRET_KEY) < 32):
    raise RuntimeError(
        "Chưa đặt SECRET_KEY an toàn. Hãy đặt biến môi trường SECRET_KEY dài tối thiểu 32 ký tự "
        "(tạo bằng: python -c \"import secrets; print(secrets.token_hex(32))\"), "
        "hoặc bật DEV_MODE=1 khi chạy thử trên máy."
    )

TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
OTP_LIMIT_TARGET_HOUR = int(os.getenv("OTP_LIMIT_TARGET_HOUR", "5"))
OTP_LIMIT_TARGET_DAY = int(os.getenv("OTP_LIMIT_TARGET_DAY", "10"))
OTP_LIMIT_IP_HOUR = int(os.getenv("OTP_LIMIT_IP_HOUR", "20"))
OTP_DAILY_CAP = int(os.getenv("OTP_DAILY_CAP", "500"))

SPEEDSMS_TOKEN = os.getenv("SPEEDSMS_TOKEN", "")
SPEEDSMS_TYPE = os.getenv("SPEEDSMS_TYPE", "4")
SPEEDSMS_SENDER = os.getenv("SPEEDSMS_SENDER", "Verify")

OTP_TTL_MINUTES = 5
RESEND_COOLDOWN_SECONDS = 60
MAX_ATTEMPTS = 5
TOKEN_DAYS = 7

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\d{9,11}$")

class PhoneRequest(BaseModel):
    phone: str

class PhoneVerify(BaseModel):
    phone: str
    code: str
    name: str = ""

class EmailRequest(BaseModel):
    email: str

class EmailVerify(BaseModel):
    email: str
    code: str

def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s.\-]", "", value)
    if not PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="Số điện thoại không hợp lệ. Hãy nhập 9 đến 11 chữ số.")
    return phone

def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Email không hợp lệ!")
    return email

def hash_code(target: str, code: str) -> str:
    return hmac.new(SECRET_KEY.encode(), f"{target}:{code}".encode(), hashlib.sha256).hexdigest()

def make_token(user_id: int) -> str:
    expires = int((datetime.utcnow() + timedelta(days=TOKEN_DAYS)).timestamp())
    payload = f"{user_id}.{expires}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"

def read_token(token: str):
    try:
        user_id, expires, signature = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}.{expires}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires) < int(datetime.utcnow().timestamp()):
            return None
        return int(user_id)
    except ValueError:
        return None

def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    scheme, _, token = authorization.partition(" ")
    user_id = read_token(token) if scheme.lower() == "bearer" else None
    user = db.get(models.User, user_id) if user_id else None
    if not user:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ, hãy đăng nhập lại!")
    return user

def to_intl_phone(phone: str) -> str:
    if phone.startswith("0"):
        return "84" + phone[1:]
    return phone

def send_sms(phone: str, code: str):
    if not SPEEDSMS_TOKEN:
        if DEV_MODE:
            print(f"[DEV] OTP cho {phone}: {code}")
            return
        raise HTTPException(status_code=503, detail="Chưa cấu hình dịch vụ gửi SMS!")

    params = {
        "access-token": SPEEDSMS_TOKEN,
        "to": to_intl_phone(phone),
        "content": f"Ma xac nhan P2P SOS cua ban la {code}. Co hieu luc {OTP_TTL_MINUTES} phut. Khong chia se ma nay cho ai.",
        "type": SPEEDSMS_TYPE,
        "sender": SPEEDSMS_SENDER,
    }
    url = "https://api.speedsms.vn/index.php/sms/send?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as res:
            data = json.loads(res.read().decode())
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Không gửi được SMS, vui lòng thử lại sau!")

    if data.get("status") != "success":
        print(f"[SMS] SpeedSMS báo lỗi: {data.get('code')} {data.get('message')}")
        raise HTTPException(status_code=503, detail="Không gửi được SMS, vui lòng thử lại sau!")

def email_sender(email: str):
    def send(code: str):
        html = (
            "<p>Mã xác nhận liên kết email của bạn là:</p>"
            f"<h2 style='letter-spacing:4px'>{code}</h2>"
            f"<p>Mã có hiệu lực trong {OTP_TTL_MINUTES} phút. Không chia sẻ mã này cho bất kỳ ai.</p>"
        )
        try:
            send_email(email, f"Mã xác nhận P2P SOS: {code}", html)
        except MailError as e:
            raise HTTPException(status_code=503, detail=str(e))
    return send

def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Proxy tin cậy thêm IP thật của client vào CUỐI danh sách; các giá trị phía trước có thể bị giả mạo.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"

def enforce_rate_limit(db: Session, target: str, ip: str):
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    log = models.OtpRequestLog

    db.query(log).filter(log.created_at < now - timedelta(days=2)).delete(synchronize_session=False)

    def count(*conditions):
        return db.query(func.count(log.id)).filter(*conditions).scalar() or 0

    if count(log.target == target, log.created_at > hour_ago) >= OTP_LIMIT_TARGET_HOUR:
        raise HTTPException(status_code=429, detail="Bạn đã yêu cầu mã quá nhiều lần, hãy thử lại sau 1 giờ!")
    if count(log.target == target, log.created_at > day_ago) >= OTP_LIMIT_TARGET_DAY:
        raise HTTPException(status_code=429, detail="Hôm nay bạn đã yêu cầu mã quá nhiều lần, hãy thử lại vào ngày mai!")
    if count(log.ip == ip, log.created_at > hour_ago) >= OTP_LIMIT_IP_HOUR:
        raise HTTPException(status_code=429, detail="Có quá nhiều yêu cầu từ mạng của bạn, hãy thử lại sau!")
    if count(log.created_at > day_ago) >= OTP_DAILY_CAP:
        raise HTTPException(status_code=503, detail="Hệ thống tạm thời không gửi được mã, hãy thử lại sau!")

    db.add(log(target=target, ip=ip))
    db.commit()

def issue_otp(db: Session, target: str, sender, ip: str = "unknown"):
    now = datetime.utcnow()
    last = db.query(models.OtpCode).filter(models.OtpCode.target == target).order_by(models.OtpCode.id.desc()).first()
    if last:
        elapsed = (now - last.created_at).total_seconds()
        if elapsed < RESEND_COOLDOWN_SECONDS:
            wait = int(RESEND_COOLDOWN_SECONDS - elapsed) + 1
            raise HTTPException(status_code=429, detail=f"Vui lòng đợi {wait} giây rồi gửi lại mã!")

    enforce_rate_limit(db, target, ip)

    code = f"{secrets.randbelow(1000000):06d}"
    sender(code)

    db.query(models.OtpCode).filter(models.OtpCode.target == target).delete()
    db.add(models.OtpCode(
        target=target,
        code_hash=hash_code(target, code),
        expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
    ))
    db.commit()

    result = {
        "message": "Đã gửi mã xác nhận!",
        "cooldown": RESEND_COOLDOWN_SECONDS,
        "expires_in": OTP_TTL_MINUTES * 60,
    }
    if DEV_MODE:
        result["dev_code"] = code
    return result

def check_otp(db: Session, target: str, code: str):
    record = db.query(models.OtpCode).filter(
        models.OtpCode.target == target,
        models.OtpCode.used == False
    ).order_by(models.OtpCode.id.desc()).first()

    if not record:
        raise HTTPException(status_code=400, detail="Bạn chưa yêu cầu mã, hãy bấm gửi mã trước!")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Mã đã hết hạn, hãy gửi lại mã mới!")
    if record.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Nhập sai quá nhiều lần, hãy gửi lại mã mới!")

    record.attempts += 1
    if not hmac.compare_digest(record.code_hash, hash_code(target, code.strip())):
        db.commit()
        left = MAX_ATTEMPTS - record.attempts
        raise HTTPException(status_code=400, detail=f"Mã không đúng! Bạn còn {left} lần thử.")

    record.used = True

@router.post("/request-otp")
def request_login_otp(body: PhoneRequest, request: Request, db: Session = Depends(get_db)):
    phone = normalize_phone(body.phone)
    return issue_otp(db, phone, lambda code: send_sms(phone, code), client_ip(request))

@router.post("/verify-otp")
def verify_login_otp(body: PhoneVerify, db: Session = Depends(get_db)):
    phone = normalize_phone(body.phone)
    check_otp(db, phone, body.code)

    user = db.query(models.User).filter(models.User.phone == phone).first()
    if not user:
        user = models.User(phone=phone, name=body.name.strip() or "ThanhVien", role="unified", is_verified=True)
        db.add(user)
    else:
        user.is_verified = True

    db.commit()
    db.refresh(user)

    return {
        "user_id": user.id,
        "phone": user.phone,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "token": make_token(user.id),
    }

@router.get("/me")
def get_me(user: models.User = Depends(get_current_user)):
    return {"user_id": user.id, "phone": user.phone, "email": user.email, "name": user.name}

@router.post("/email/request")
def request_email_otp(body: EmailRequest, request: Request, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    owner = db.query(models.User).filter(models.User.email == email).first()
    if owner and owner.id != user.id:
        raise HTTPException(status_code=409, detail="Email này đã được liên kết với tài khoản khác!")
    return issue_otp(db, email, email_sender(email), client_ip(request))

@router.post("/email/verify")
def verify_email_otp(body: EmailVerify, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    owner = db.query(models.User).filter(models.User.email == email).first()
    if owner and owner.id != user.id:
        raise HTTPException(status_code=409, detail="Email này đã được liên kết với tài khoản khác!")

    check_otp(db, email, body.code)
    user.email = email
    db.commit()
    return {"message": "Đã liên kết email nhận thông báo!", "email": email}

@router.delete("/email")
def unlink_email(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.email = None
    db.commit()
    return {"message": "Đã gỡ email!"}