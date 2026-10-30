import os
import json
import urllib.request
import urllib.error
from sqlalchemy.orm import Session

from . import models

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