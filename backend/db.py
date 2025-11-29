# db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
import logging

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

# Load DATABASE_URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

# Fallback to local SQLite database if DATABASE_URL not set
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is missing. Please set it in the environment.")
else:
    logger.info("✅ Using hosted PostgreSQL database.")

# ==========================================
# CONNECTION POOL SETTINGS (OPTIMIZED)
# ==========================================

# Pool size configuration from environment with sensible defaults
POOL_SIZE = int(os.getenv("SQLALCHEMY_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "20"))
POOL_TIMEOUT = int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "3600"))
POOL_PRE_PING = os.getenv("SQLALCHEMY_POOL_PRE_PING", "true").lower() == "true"
ECHO_SQL = os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"

# ==========================================
# CREATE SQLALCHEMY ENGINE (OPTIMIZED)
# ==========================================

engine = create_engine(
    DATABASE_URL,
    
    # Connection pool settings
    poolclass=pool.QueuePool,  # Use QueuePool for PostgreSQL
    pool_size=POOL_SIZE,  # Number of persistent connections (default: 10)
    max_overflow=MAX_OVERFLOW,  # Additional connections during high load (default: 20)
    pool_timeout=POOL_TIMEOUT,  # Seconds to wait for available connection (default: 30)
    pool_recycle=POOL_RECYCLE,  # Recycle connections after N seconds (default: 3600 = 1 hour)
    pool_pre_ping=POOL_PRE_PING,  # Test connections before using (default: True)
    
    # Performance settings
    echo=ECHO_SQL,  # Log all SQL statements (default: False, set True for debugging)
    echo_pool=False,  # Log pool checkouts/checkins (set True for pool debugging)
    future=True,  # Use SQLAlchemy 2.0 style
    
    # Connection arguments for PostgreSQL
    connect_args={
        "connect_timeout": 10,  # Connection timeout in seconds
        "application_name": "aztec_crm",  # Identify connections in pg_stat_activity
    } if "postgresql" in DATABASE_URL else {},
    
    # Execution options
    execution_options={
        "isolation_level": "READ COMMITTED"  # Default isolation level
    }
)

logger.info(f"✅ Database engine created with pool_size={POOL_SIZE}, max_overflow={MAX_OVERFLOW}")

# ==========================================
# CONNECTION POOL EVENT LISTENERS (MONITORING)
# ==========================================

@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """
    Called when a new database connection is created
    Useful for monitoring and debugging
    """
    logger.debug("🔌 New database connection created")


@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """
    Called when a connection is retrieved from the pool
    Useful for monitoring pool usage
    """
    logger.debug("📤 Connection checked out from pool")


@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """
    Called when a connection is returned to the pool
    Useful for monitoring pool usage
    """
    logger.debug("📥 Connection returned to pool")


# ==========================================
# SESSION CONFIGURATION (OPTIMIZED)
# ==========================================

SessionLocal = sessionmaker(
    autocommit=False,  # Manual transaction control
    autoflush=False,  # Manual flush control (better performance)
    bind=engine,
    future=True,  # SQLAlchemy 2.0 style
    expire_on_commit=False,  # Prevents attributes from expiring after commit (CRITICAL for performance)
)

logger.info("✅ Session factory configured")

# ==========================================
# BASE CLASS FOR MODELS
# ==========================================

Base = declarative_base()

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_db():
    """
    Dependency-style session generator
    
    Usage in FastAPI/similar:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """
    Test database connection for diagnostics
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            # Execute a simple query to verify connection
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
            logger.info("✅ Database connection test successful")
            return True
    except SQLAlchemyError as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False


def get_db_connection():
    """
    Legacy wrapper for backward compatibility
    
    Returns raw SQLAlchemy connection
    NOT RECOMMENDED - use SessionLocal() instead
    """
    try:
        conn = engine.connect()
        logger.debug("🔌 Raw connection created (legacy method)")
        return conn
    except SQLAlchemyError as e:
        logger.error(f"❌ Error creating database connection: {e}")
        raise


def init_db():
    """
    Initialize database tables
    
    IMPORTANT: Uses checkfirst=True to avoid dropping existing data
    Only creates tables that don't exist
    """
    try:
        from backend.models import (
            User, Customer, Project, Job, Assignment, 
            CustomerFormData, DrawingDocument, FormDocument,
            MaterialOrder, ProductionNotification, Quotation, 
            QuotationItem, Fitter, ActionItem, Brand, 
            ApplianceCategory, Product, DataImport
        )
        
        # Create all tables (only if they don't exist)
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("✅ Database tables initialized")
        return True
        
    except ImportError as e:
        logger.error(f"❌ Error importing models: {e}")
        return False
    except SQLAlchemyError as e:
        logger.error(f"❌ Error initializing database: {e}")
        return False


def get_pool_status():
    """
    Get current connection pool status
    
    Useful for monitoring and debugging
    
    Returns:
        dict: Pool statistics
    """
    pool_obj = engine.pool
    
    return {
        "pool_size": pool_obj.size(),
        "checked_in": pool_obj.checkedin(),
        "checked_out": pool_obj.checkedout(),
        "overflow": pool_obj.overflow(),
        "total_connections": pool_obj.size() + pool_obj.overflow(),
        "settings": {
            "pool_size": POOL_SIZE,
            "max_overflow": MAX_OVERFLOW,
            "pool_timeout": POOL_TIMEOUT,
            "pool_recycle": POOL_RECYCLE,
        }
    }


def close_all_connections():
    """
    Close all database connections in the pool
    
    Useful for cleanup during shutdown or testing
    """
    try:
        engine.dispose()
        logger.info("✅ All database connections closed")
        return True
    except Exception as e:
        logger.error(f"❌ Error closing connections: {e}")
        return False


def reset_pool():
    """
    Reset the connection pool
    
    Useful for recovering from connection issues
    """
    try:
        engine.dispose()
        logger.info("✅ Connection pool reset")
        return True
    except Exception as e:
        logger.error(f"❌ Error resetting pool: {e}")
        return False


# ==========================================
# HEALTH CHECK FUNCTION
# ==========================================

def health_check():
    """
    Comprehensive database health check
    
    Returns:
        dict: Health status with details
    """
    health = {
        "database": "unknown",
        "connection": False,
        "pool": {},
        "errors": []
    }
    
    try:
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0] if result else "unknown"
            health["database"] = "postgresql"
            health["connection"] = True
            health["version"] = version
            
        # Get pool status
        health["pool"] = get_pool_status()
        
    except SQLAlchemyError as e:
        health["connection"] = False
        health["errors"].append(str(e))
        logger.error(f"❌ Health check failed: {e}")
    
    return health


# ==========================================
# STARTUP VALIDATION
# ==========================================

def validate_database_config():
    """
    Validate database configuration on startup
    
    Checks:
    - DATABASE_URL is set
    - Connection pool settings are reasonable
    - Database is accessible
    """
    issues = []
    
    # Check DATABASE_URL
    if not DATABASE_URL:
        issues.append("DATABASE_URL not set")
    
    # Check pool settings
    if POOL_SIZE < 5:
        issues.append(f"POOL_SIZE ({POOL_SIZE}) is very low, recommend at least 5")
    
    if POOL_SIZE > 50:
        issues.append(f"POOL_SIZE ({POOL_SIZE}) is very high, may waste resources")
    
    if MAX_OVERFLOW < POOL_SIZE:
        issues.append(f"MAX_OVERFLOW ({MAX_OVERFLOW}) should be >= POOL_SIZE ({POOL_SIZE})")
    
    if POOL_TIMEOUT < 10:
        issues.append(f"POOL_TIMEOUT ({POOL_TIMEOUT}s) is very low, may cause frequent timeouts")
    
    # Test connection
    if not test_connection():
        issues.append("Database connection test failed")
    
    # Log results
    if issues:
        logger.warning("⚠️ Database configuration issues detected:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    else:
        logger.info("✅ Database configuration validated successfully")
    
    return len(issues) == 0


# ==========================================
# RUN VALIDATION ON IMPORT
# ==========================================

# Validate configuration when module is imported
# This ensures issues are caught early
validate_database_config()