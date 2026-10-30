import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, database, auth, realtime
from ..mailer import notify_in_background
from .sos import get_sos_or_404

router = APIRouter(prefix="/api", tags=["payment"])

# Mã ngân hàng theo chuẩn VietQR (img.vietqr.io). Hãy thử quét QR thật với từng ngân hàng trước khi phát hành.
BANKS = {
    "VCB": "Vietcombank", "TCB": "Techcombank", "MB": "MB Bank", "ACB": "ACB", "BIDV": "BIDV",
    "ICB": "VietinBank", "VBA": "Agribank", "VPB": "VPBank", "TPB": "TPBank", "STB": "Sacombank",
    "SHB": "SHB", "HDB": "HDBank", "VIB": "VIB", "OCB": "OCB", "MSB": "MSB", "SEAB": "SeABank",
}
PAYABLE_STATUSES = ("NEGOTIATING", "COMPLETED")
METHOD_LABEL = {"CASH": "tiền mặt", "TRANSFER": "chuyển khoản"}

class BankUpdate(BaseModel):
    bank_code: str = ""
    bank_account: str = ""
    bank_holder: str = ""

class PaymentMethodBody(BaseModel):
    method: str

@router.get("/helper/bank")
def get_bank(current: models.User = Depends(auth.get_current_user)):
    return {"bank_code": current.bank_code or "", "bank_account": current.bank_account or "", "bank_holder": current.bank_holder or "", "banks": BANKS}

@router.put("/helper/bank")
def update_bank(body: BankUpdate, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    code = body.bank_code.strip().upper()
    account = re.sub(r"[\s.\-]", "", body.bank_account)
    holder = " ".join(body.bank_holder.split())[:60]

    if not code and not account and not holder:
        current.bank_code = current.bank_account = current.bank_holder = None
        db.commit()
        return {"message": "Đã xóa tài khoản nhận tiền."}

    if code not in BANKS:
        raise HTTPException(status_code=400, detail="Hãy chọn ngân hàng!")
    if not re.fullmatch(r"\d{6,20}", account):
        raise HTTPException(status_code=400, detail="Số tài khoản phải gồm 6 đến 20 chữ số!")
    if len(holder) < 2:
        raise HTTPException(status_code=400, detail="Hãy nhập tên chủ tài khoản!")

    current.bank_code, current.bank_account, current.bank_holder = code, account, holder
    db.commit()
    return {"message": "Đã lưu tài khoản nhận tiền."}

@router.put("/sos/{sos_id}/payment-method")
def set_payment_method(sos_id: int, body: PaymentMethodBody, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    if sos.user_id != current.id:
        raise HTTPException(status_code=403, detail="Chỉ khách mới chọn được cách thanh toán!")
    if sos.status not in PAYABLE_STATUSES or not sos.agreed_price:
        raise HTTPException(status_code=400, detail="Chỉ chọn được cách thanh toán sau khi đã thống nhất giá!")
    if (sos.payment_status or "UNPAID") == "PAID":
        raise HTTPException(status_code=400, detail="Đơn này đã thanh toán rồi!")
    method = body.method.strip().upper()
    if method not in METHOD_LABEL:
        raise HTTPException(status_code=400, detail="Cách thanh toán không hợp lệ!")

    if method == "TRANSFER":
        helper = db.get(models.User, sos.helper_id) if sos.helper_id else None
        if not (helper and helper.bank_code and helper.bank_account):
            raise HTTPException(status_code=400, detail="Thợ chưa cập nhật tài khoản nhận tiền, hãy chọn tiền mặt hoặc nhờ thợ cập nhật!")

    sos.payment_method = method
    db.add(models.Message(sos_id=sos_id, sender_id=current.id, content=f"💳 Khách chọn thanh toán bằng {METHOD_LABEL[method]}."))
    db.commit()
    realtime.sos_changed(sos)
    return {"message": "Đã chọn cách thanh toán.", "payment_method": method}

@router.put("/sos/{sos_id}/confirm-paid")
def confirm_paid(sos_id: int, background: BackgroundTasks, current: models.User = Depends(auth.get_current_user), db: Session = Depends(database.get_db)):
    sos = get_sos_or_404(db, sos_id)
    if sos.helper_id != current.id:
        raise HTTPException(status_code=403, detail="Chỉ thợ của đơn mới xác nhận đã nhận tiền!")
    if sos.status not in PAYABLE_STATUSES or not sos.agreed_price:
        raise HTTPException(status_code=400, detail="Đơn chưa thống nhất giá nên chưa thể xác nhận thanh toán!")

    method = sos.payment_method or "CASH"
    updated = db.query(models.SOSRequest).filter(
        models.SOSRequest.id == sos_id,
        or_(models.SOSRequest.payment_status.is_(None), models.SOSRequest.payment_status != "PAID"),
    ).update({"payment_status": "PAID", "payment_method": method, "paid_at": datetime.utcnow()}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="Đơn này đã được xác nhận thanh toán rồi!")

    message = f"✅ Thợ xác nhận đã nhận đủ {sos.agreed_price:,.0f} VNĐ bằng {METHOD_LABEL[method]}."
    db.add(models.Message(sos_id=sos_id, sender_id=current.id, content=message))
    db.commit()
    db.refresh(sos)
    realtime.sos_changed(sos)
    background.add_task(notify_in_background, sos.user_id, f"Đơn SOS #{sos.id}: đã thanh toán", message)
    return {"message": "Đã xác nhận thanh toán.", "payment_status": "PAID"}
