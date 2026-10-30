import os
import json
import html as html_lib
import urllib.request
import urllib.error
from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
MAIL_SENDER = os.getenv("MAIL_SENDER", "")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"

class MailError(Exception):
    pass

def send_email(to: str, subject: str, html: str):
    if not BREVO_API_KEY or not MAIL_SENDER:
        if DEV_MODE:
            print(f"[DEV] Email tới {to}: {subject}")
            return
        raise MailError("Server chưa cấu hình dịch vụ gửi email!")

    body = {
        "sender": {"name": "P2P SOS", "email": MAIL_SENDER},
        "to": [{"email": to}],
        "subject": subject,
        "htmlContent": html,
    }
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(body).encode(),
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "accept": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=15)
    except OSError:
        raise MailError("Không gửi được email, vui lòng thử lại sau!")

def notify_user(db: Session, user_id: int, subject: str, html: str) -> bool:
    user = db.get(models.User, user_id)
    if not user or not user.email:
        return False
    try:
        send_email(user.email, subject, html)
        return True
    except MailError:
        return False

def notify_in_background(user_id, subject: str, message: str):
    if not user_id:
        return
    db = SessionLocal()
    try:
        body = f"<p>{html_lib.escape(message)}</p><p>Mở ứng dụng P2P SOS để xem chi tiết.</p>"
        notify_user(db, user_id, subject, body)
    except Exception as e:
        print(f"[MAIL] Lỗi gửi thông báo: {e}")
    finally:
        db.close()