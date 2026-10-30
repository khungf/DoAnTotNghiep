import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sos_database.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

MIGRATIONS = {
    "users": {
        "email": "varchar",
        "is_verified": "boolean default false",
        "vehicle_info": "varchar",
        "vehicle_photo": "varchar",
        "cert_photo": "varchar",
        "verification_status": "varchar default 'NONE'",
        "verification_note": "varchar",
        "current_lat": "float",
        "current_lon": "float",
    },
    "sos_requests": {
        "cancel_reason": "varchar",
        "cancelled_by": "integer",
    },
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from . import models
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, new_columns in MIGRATIONS.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in new_columns.items():
                if name not in existing:
                    conn.execute(text(f"alter table {table} add column {name} {ddl}"))
        conn.execute(text("create unique index if not exists ix_users_email on users (email)"))