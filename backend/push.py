import os
import json
from sqlalchemy.orm import Session

from . import models

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")

def push_enabled() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

def send_push_to_user(db: Session, user_id, title: str, body: str, url: str = "/static/index.html", tag: str = None) -> int:
    """Gửi thông báo đẩy tới mọi thiết bị đã đăng ký của user. Trả về số thiết bị gửi thành công."""
    if not user_id or not push_enabled():
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[PUSH] Chưa cài pywebpush, bỏ qua thông báo đẩy.")
        return 0

    subscriptions = db.query(models.PushSubscription).filter(models.PushSubscription.user_id == user_id).all()
    payload = json.dumps({"title": title[:80], "body": body[:200], "url": url, "tag": tag})
    sent = 0
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=600,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                db.delete(sub)  # thiết bị đã hủy đăng ký
            else:
                print(f"[PUSH] Lỗi gửi tới user {user_id}: {e}")
        except Exception as e:
            print(f"[PUSH] Lỗi không xác định: {e}")
    db.commit()
    return sent
