from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from backend.database import engine
from backend.models import Base
from backend.routers import sos, chat, features

# Tự động tạo bảng trong Database
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Do An Tot Nghiep - SOS System", version="1.0.0")

# Tự động quét tìm thư mục static ở cả thư mục gốc lẫn thư mục backend
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # Thư mục backend
ROOT_DIR = os.path.dirname(BASE_DIR)                  # Thư mục gốc DoAnTotNghiep

possible_static_dirs = [
    os.path.join(ROOT_DIR, "static"),
    os.path.join(BASE_DIR, "static"),
    "static"
]

STATIC_DIR = None
for d in possible_static_dirs:
    if os.path.exists(d):
        STATIC_DIR = d
        break

# Mount static files nếu tìm thấy
if STATIC_DIR:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Nạp các router
app.include_router(sos.router)
app.include_router(chat.router)
app.include_router(features.router)

# Route trang chủ trả về thẳng giao diện index.html luôn
@app.get("/")
def read_root():
    if STATIC_DIR:
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    return {"message": "API Đồ án Tốt nghiệp đang chạy ổn định!"}