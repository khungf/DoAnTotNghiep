from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String)
    role = Column(String, default="unified")
    is_verified = Column(Boolean, default=False)

    vehicle_info = Column(String, nullable=True)
    vehicle_photo = Column(String, nullable=True)
    cert_photo = Column(String, nullable=True)
    verification_status = Column(String, default="NONE")
    verification_note = Column(String, nullable=True)

    current_lat = Column(Float, nullable=True)
    current_lon = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)

    is_available = Column(Boolean, default=False)
    max_distance = Column(Float, default=10.0)

    bank_code = Column(String, nullable=True)
    bank_account = Column(String, nullable=True)
    bank_holder = Column(String, nullable=True)

class OtpCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True, index=True)
    target = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class SOSRequest(Base):
    __tablename__ = "sos_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    issue_type = Column(String, nullable=False)
    proposed_price = Column(Float, nullable=False)
    status = Column(String, default="PENDING")
    helper_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agreed_price = Column(Float, nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    cancel_reason = Column(String, nullable=True)
    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    payment_method = Column(String, nullable=True)
    payment_status = Column(String, default="UNPAID")
    paid_at = Column(DateTime, nullable=True)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sos_id = Column(Integer, ForeignKey("sos_requests.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    sos_id = Column(Integer, ForeignKey("sos_requests.id"))
    reviewer_id = Column(Integer, ForeignKey("users.id"))
    target_id = Column(Integer, ForeignKey("users.id"))
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserReport(Base):
    __tablename__ = "user_reports"
    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"))
    reported_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sos_id = Column(Integer, ForeignKey("sos_requests.id"), nullable=True)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class IgnoredOrder(Base):
    __tablename__ = "ignored_orders"
    id = Column(Integer, primary_key=True, index=True)
    sos_id = Column(Integer, ForeignKey("sos_requests.id"), index=True, nullable=False)
    helper_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OtpRequestLog(Base):
    __tablename__ = "otp_request_logs"
    id = Column(Integer, primary_key=True, index=True)
    target = Column(String, index=True, nullable=False)
    ip = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    endpoint = Column(String, unique=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
