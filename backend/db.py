# db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

# Load DATABASE_URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

# Fallback to local SQLite database if DATABASE_URL not set
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./local.db"
    print("[WARNING] Using local SQLite database (DATABASE_URL not found in environment).")
else:
    print("[OK] Using hosted PostgreSQL database.")

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True
)

# Create a configured "Session" class
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False  # ✅ ADD THIS LINE - Prevents attributes from expiring after commit
)

# Base class for declarative models
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


# 👇 Legacy compatibility function for routes still using get_db_connection()
def get_db_connection():
    """
    Legacy wrapper for backward compatibility with old code expecting
    a raw connection (like SQLite). Now returns an SQLAlchemy connection.
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
    
    # ✅ CRITICAL: checkfirst=True ensures existing data is NOT dropped
    Base.metadata.create_all(bind=engine, checkfirst=True)
    print("✅ Database tables initialized")