from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
from backend.database import engine
from backend.models import Base
from backend.routers import sos, chat, features

# Tự động tạo bảng trong Database (nếu chưa có)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Do An Tot Nghiep - SOS System", version="1.0.0")

# Cấu hình trỏ ra thư mục static ở gốc dự án để chạy giao diện web & PWA
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(ROOT_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Nạp toàn bộ các router đã tách
app.include_router(sos.router)
app.include_router(chat.router)
app.include_router(features.router)

@app.get("/")
def read_root():
    return {"message": "API Đồ án Tốt nghiệp đang chạy ổn định!"}