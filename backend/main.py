import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Import database và models sẵn có
from backend.database import engine
from backend.models import Base

# Import các router mới trong thư mục backend/routers/
from backend.routers import sos, chat, features

# Tự động tạo bảng cơ sở dữ liệu nếu chưa có
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Do An Tot Nghiep - SOS System", version="1.0.0")

# Tự động tìm chính xác thư mục static ở cả thư mục gốc lẫn thư mục backend (phòng hờ khi deploy trên Render)
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Thư mục backend
ROOT_DIR = os.path.dirname(BASE_DIR)                  # Thư mục gốc DoAnTotNghiep

STATIC_DIR = os.path.join(ROOT_DIR, "static")
if not os.path.exists(STATIC_DIR):
    STATIC_DIR = os.path.join(BASE_DIR, "static")

# Mount thư mục static để chạy giao diện web, PWA (manifest.json, sw.js)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Nạp toàn bộ các router chức năng mới
app.include_router(sos.router)
app.include_router(chat.router)
app.include_router(features.router)

# Route trang chủ: Tự động trả về file index.html thay vì hiện dòng chữ JSON
@app.get("/")
def read_root():
    if STATIC_DIR:
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    return {"message": "API Đồ án Tốt nghiệp đang chạy ổn định!"}