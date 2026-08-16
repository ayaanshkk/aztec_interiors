# db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./local.db"
    print("⚠️ Using local SQLite database (DATABASE_URL not found in environment).")
else:
    # ✅ Force transaction mode (port 6543) — prevents session mode connection exhaustion
    DATABASE_URL = DATABASE_URL.replace(
        "pooler.supabase.com:5432",
        "pooler.supabase.com:6543"
    )
    print("✅ Using hosted PostgreSQL database (transaction mode, port 6543).")

# ✅ Detect SQLite to skip PostgreSQL-specific pool args
is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {
    "pool_pre_ping": True,   # Test connection health before use
    "future": True,
}

if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 5,        # Max persistent connections in pool
        "max_overflow": 10,    # Extra connections allowed under burst load
        "pool_timeout": 30,    # Wait up to 30s for a free connection
        "pool_recycle": 300,   # Recycle connections every 5 minutes
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db():
    """Dependency-style session generator"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """Optional: Check DB connection for diagnostics"""
    try:
        with engine.connect() as conn:
            print("✅ Database connection successful.")
    except SQLAlchemyError as e:
        print("❌ Database connection failed:", e)


def get_db_connection():
    """
    Legacy wrapper for backward compatibility with old code expecting
    a raw connection. Now returns an SQLAlchemy connection.
    """
    try:
        conn = engine.connect()
        return conn
    except SQLAlchemyError as e:
        print(f"❌ Error creating database connection: {e}")
        raise


def init_db():
    """Initialize database tables - only creates if they don't exist"""
    from backend.models import (
        User, Customer, Project, Job, Assignment,
        CustomerFormData, DrawingDocument, FormDocument,
        MaterialOrder, ProductionNotification, Quotation, QuotationItem, Fitter
    )

    Base.metadata.create_all(bind=engine, checkfirst=True)
    print("✅ Database tables initialized")