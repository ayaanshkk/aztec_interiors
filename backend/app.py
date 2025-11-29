from flask import Flask, request, jsonify, g
from flask_cors import CORS
import os
from dotenv import load_dotenv
from .db import Base, engine, SessionLocal, test_connection, init_db
from datetime import datetime

load_dotenv()

# ==========================================
# SIMPLE IN-MEMORY CACHE FOR MOCK USER
# ==========================================
_mock_user_cache = None
_mock_user_cache_time = None
_mock_user_cache_ttl = 300  # 5 minutes


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
    
    # CRITICAL: SQLAlchemy connection pool settings
    # These ensure efficient database connection reuse
    app.config["SQLALCHEMY_POOL_SIZE"] = int(os.getenv("SQLALCHEMY_POOL_SIZE", "10"))
    app.config["SQLALCHEMY_POOL_TIMEOUT"] = int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "30"))
    app.config["SQLALCHEMY_POOL_RECYCLE"] = int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "3600"))
    app.config["SQLALCHEMY_MAX_OVERFLOW"] = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "20"))

    # ============================================
    # CORS
    # ============================================
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
    )

    # ============================================
    # PREFLIGHT HANDLER
    # ============================================
    @app.before_request
    def handle_preflight():
        """Handle CORS preflight requests efficiently"""
        if request.method == "OPTIONS":
            resp = jsonify({"status": "ok"})
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "*"
            return resp, 200

    # ============================================
    # AFTER-REQUEST HEADERS
    # ============================================
    @app.after_request
    def add_cors_headers(resp):
        """Add CORS headers to all responses"""
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    # ============================================
    # REQUEST LIFECYCLE MANAGEMENT (OPTIMIZED)
    # ============================================
    
    @app.before_request
    def setup_request_context():
        """
        Setup request context with database session
        
        OPTIMIZATIONS:
        - Reusable database session per request
        - Request timing for monitoring
        - Skip for OPTIONS requests
        """
        if request.method == "OPTIONS":
            return None
        
        # Start request timer for performance monitoring
        g.request_start_time = datetime.utcnow()
        
        # CRITICAL: Create database session for this request
        # This allows routes to use g.db_session instead of creating their own
        g.db_session = SessionLocal()
        
        return None
    
    
    @app.teardown_request
    def teardown_request_context(exception=None):
        """
        Cleanup request context
        
        CRITICAL: Always close database session to prevent leaks
        """
        # Close database session if it exists
        db_session = g.pop('db_session', None)
        if db_session is not None:
            try:
                if exception:
                    db_session.rollback()
                db_session.close()
            except Exception as e:
                app.logger.error(f"Error closing database session: {e}")
        
        # Log request duration for monitoring (dev mode only)
        if app.debug and hasattr(g, 'request_start_time'):
            duration = (datetime.utcnow() - g.request_start_time).total_seconds()
            if duration > 1.0:  # Log slow requests (>1 second)
                app.logger.warning(
                    f"SLOW REQUEST: {request.method} {request.path} took {duration:.2f}s"
                )

    # ============================================
    # MOCK AUTH (OPTIMIZED)
    # ============================================
    
    @app.before_request
    def set_mock_user():
        """
        Set mock user for development
        
        OPTIMIZATIONS:
        - 5-minute cache for mock user (avoids DB query on every request)
        - Skip for OPTIONS requests
        - Proper error handling
        - Uses request context session
        """
        global _mock_user_cache, _mock_user_cache_time
        
        if request.method == "OPTIONS":
            return None

        from backend.models import User
        
        try:
            # OPTIMIZED: Check cache first (avoid DB query)
            if _mock_user_cache and _mock_user_cache_time:
                cache_age = (datetime.utcnow() - _mock_user_cache_time).seconds
                if cache_age < _mock_user_cache_ttl:
                    g.user = _mock_user_cache
                    return None
            
            # OPTIMIZED: Use request context session
            if hasattr(g, 'db_session'):
                user = g.db_session.query(User).first()
                if user:
                    # Cache the user object
                    _mock_user_cache = user
                    _mock_user_cache_time = datetime.utcnow()
                    g.user = user
                    return None
            
            # Fallback: create mock user object
            g.user = type("User", (), {
                "id": 1,
                "email": "dev@test.com",
                "first_name": "Dev",
                "last_name": "User",
                "full_name": "Dev User",
                "role": "Manager",
                "is_active": True,
            })()
            
        except Exception as e:
            app.logger.warning(f"Error setting mock user: {e}")
            # Create mock user object on error
            g.user = type("User", (), {
                "id": 1,
                "email": "dev@test.com",
                "first_name": "Dev",
                "last_name": "User",
                "full_name": "Dev User",
                "role": "Manager",
                "is_active": True,
            })()
        
        return None

    # ============================================
    # BLUEPRINTS
    # ============================================
    from backend.routes import (
        auth_routes, approvals_routes, form_routes, db_routes,
        notification_routes, assignment_routes, appliance_routes,
        customer_routes, file_routes, materials_routes, job_routes, 
        action_items_routes,
    )

    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(approvals_routes.approvals_bp)
    app.register_blueprint(form_routes.form_bp)
    app.register_blueprint(customer_routes.customer_bp)
    app.register_blueprint(db_routes.db_bp)
    app.register_blueprint(notification_routes.notification_bp)
    app.register_blueprint(assignment_routes.assignment_bp)
    app.register_blueprint(appliance_routes.appliance_bp)
    app.register_blueprint(file_routes.file_bp)
    app.register_blueprint(materials_routes.materials_bp)
    app.register_blueprint(job_routes.job_bp)
    app.register_blueprint(action_items_routes.action_items_bp)

    # ============================================
    # HEALTH CHECK
    # ============================================
    
    @app.route("/health", methods=["GET"])
    def health_check():
        """
        Health check endpoint
        
        OPTIMIZATIONS:
        - Tests database connectivity
        - Returns performance metrics
        """
        health_status = {
            "status": "ok",
            "message": "Server is running",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Optional: Test database connectivity
        try:
            if hasattr(g, 'db_session'):
                g.db_session.execute("SELECT 1")
                health_status["database"] = "connected"
            else:
                # Quick connectivity test
                session = SessionLocal()
                session.execute("SELECT 1")
                session.close()
                health_status["database"] = "connected"
        except Exception as e:
            health_status["database"] = "error"
            health_status["database_error"] = str(e)
            app.logger.error(f"Database health check failed: {e}")
        
        return jsonify(health_status), 200
    
    
    # ============================================
    # PERFORMANCE MONITORING ENDPOINT
    # ============================================
    
    @app.route("/metrics", methods=["GET"])
    def metrics():
        """
        Performance metrics endpoint (development only)
        
        Returns:
        - Database connection pool stats
        - Cache statistics
        - Request performance
        """
        if not app.debug:
            return jsonify({"error": "Metrics only available in debug mode"}), 403
        
        metrics_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "database": {
                "pool_size": app.config["SQLALCHEMY_POOL_SIZE"],
                "max_overflow": app.config["SQLALCHEMY_MAX_OVERFLOW"],
                "pool_timeout": app.config["SQLALCHEMY_POOL_TIMEOUT"],
            },
            "cache": {
                "mock_user_cached": _mock_user_cache is not None,
                "mock_user_cache_age": (
                    (datetime.utcnow() - _mock_user_cache_time).seconds 
                    if _mock_user_cache_time else None
                )
            }
        }
        
        return jsonify(metrics_data), 200
    
    
    # ============================================
    # ERROR HANDLERS
    # ============================================
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors"""
        return jsonify({
            "error": "Not found",
            "message": "The requested resource was not found"
        }), 404
    
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors"""
        app.logger.error(f"Internal server error: {error}")
        
        # Rollback any pending transactions
        if hasattr(g, 'db_session'):
            try:
                g.db_session.rollback()
            except:
                pass
        
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        }), 500
    
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        """Handle all unhandled exceptions"""
        app.logger.exception(f"Unhandled exception: {error}")
        
        # Rollback any pending transactions
        if hasattr(g, 'db_session'):
            try:
                g.db_session.rollback()
            except:
                pass
        
        return jsonify({
            "error": "An error occurred",
            "message": str(error) if app.debug else "An unexpected error occurred"
        }), 500

    # ============================================
    # STARTUP TASKS
    # ============================================
    
    with app.app_context():
        # Test database connection on startup
        try:
            app.logger.info("Testing database connection...")
            if test_connection():
                app.logger.info("✅ Database connection successful")
            else:
                app.logger.warning("⚠️ Database connection failed")
        except Exception as e:
            app.logger.error(f"❌ Database connection error: {e}")
        
        # Initialize database if needed
        try:
            app.logger.info("Initializing database...")
            init_db()
            app.logger.info("✅ Database initialized")
        except Exception as e:
            app.logger.error(f"❌ Database initialization error: {e}")

    return app


# ============================================
# HELPER FUNCTION FOR ROUTES (OPTIONAL)
# ============================================

def get_db_session():
    """
    Get database session from request context
    
    Usage in routes:
        from backend.app import get_db_session
        session = get_db_session()
    
    IMPORTANT: Don't close this session - it's managed by teardown_request
    """
    if hasattr(g, 'db_session'):
        return g.db_session
    
    # Fallback: create new session (not recommended)
    # This should only happen outside request context
    return SessionLocal()