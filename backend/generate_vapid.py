"""Tạo cặp khóa VAPID cho thông báo đẩy. Chạy 1 lần: python generate_vapid.py
Sau đó đặt 2 giá trị in ra thành biến môi trường trên server (KHÔNG commit lên git)."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

key = ec.generate_private_key(ec.SECP256R1())
private_raw = key.private_numbers().private_value.to_bytes(32, "big")
public_raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

print("VAPID_PUBLIC_KEY=" + b64(public_raw))
print("VAPID_PRIVATE_KEY=" + b64(private_raw))
print("VAPID_SUBJECT=mailto:email-cua-ban@example.com")
