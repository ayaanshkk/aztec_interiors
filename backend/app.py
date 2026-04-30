# backend/app.py (FULL create_app function replacement)
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import os
from dotenv import load_dotenv

from backend.routes import tasks_routes
from .db import Base, engine, SessionLocal, test_connection, init_db

load_dotenv()

def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ============================================
    # ⚙️ DATABASE INITIALIZATION
    # ============================================
    print("🔧 Initializing database schema...")
    try:
        from backend import models
        Base.metadata.create_all(bind=engine, checkfirst=True)
        
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"✅ Database schema initialized - {len(tables)} tables exist")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()

    # ============================================
    # CORS - FIXED FOR LOCALHOST
    # ============================================
    CORS(
        app,
        resources={r"/*": {
            "origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "https://aztec-interior.vercel.app",  # Add your Vercel URL later
            ],
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            "expose_headers": ["Content-Type", "Authorization"],
            "supports_credentials": True,
            "max_age": 3600
        }},
        supports_credentials=True,
    )

    # ============================================
    # PREFLIGHT HANDLER
    # ============================================
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            resp = jsonify({"status": "ok"})
            resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Requested-With"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp, 200

    # ============================================
    # AFTER-REQUEST HEADERS
    # ============================================
    @app.after_request
    def add_cors_headers(resp):
        origin = request.headers.get("Origin")
        allowed_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://aztec-interior.vercel.app",
        ]
        
        if origin in allowed_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
        else:
            resp.headers["Access-Control-Allow-Origin"] = allowed_origins[0]
            
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Requested-With"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

    # ============================================
    # MOCK AUTH (DEV MODE)
    # ============================================
    @app.before_request
    def set_mock_user():
        if request.method == "OPTIONS":
            return None

        from backend.models import User
        try:
            session = SessionLocal()
            user = session.query(User).first()
            session.close()
            if user:
                g.user = user
            else:
                g.user = type("User", (), {
                    "id": 1,
                    "email": "dev@test.com",
                    "first_name": "Dev",
                    "last_name": "User",
                    "role": "Manager",
                    "is_active": True,
                })()
        except Exception:
            g.user = type("User", (), {
                "id": 1,
                "email": "dev@test.com",
                "first_name": "Dev",
                "last_name": "User",
                "role": "Manager",
                "is_active": True,
            })()
        return None

    # ============================================
    # BLUEPRINTS
    # ============================================
    from backend.routes import (
        auth_routes, form_routes,
        notification_routes, appliance_routes,
        customer_routes, file_routes, materials_routes, 
        action_items_routes, quotation_routes, pipeline_routes, tasks_routes, calendar_routes, project_routes,
    )

    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(form_routes.form_bp)
    app.register_blueprint(customer_routes.customer_bp)
    app.register_blueprint(notification_routes.notification_bp)
    app.register_blueprint(appliance_routes.appliance_bp)
    app.register_blueprint(file_routes.file_bp)
    app.register_blueprint(materials_routes.materials_bp)
    app.register_blueprint(pipeline_routes.pipeline_bp)
    app.register_blueprint(tasks_routes.tasks_bp)
    app.register_blueprint(calendar_routes.calendar_bp)
    app.register_blueprint(project_routes.project_bp)
    app.register_blueprint(action_items_routes.action_items_bp)
    app.register_blueprint(quotation_routes.quotation_bp)

    # ============================================
    # HEALTH CHECK
    # ============================================
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({
            "status": "ok", 
            "message": "Server is running",
            "environment": "development" if os.getenv("DEV_MODE", "false").lower() == "true" else "production"
        }), 200

    return app

# ============================================
# STANDALONE LAUNCH
# ============================================
if __name__ == "__main__":
    app = create_app()

    print("=" * 60)
    print("🔧 INITIALISING DATABASE...")
    print("=" * 60)

    from backend import models
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\n📋 {len(tables)} tables detected:")
    for t in tables:
        print(f"   ✓ {t}")

    print("\n✅ Database initialised successfully!\n")
    print("=" * 60)

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    
    print(f"\n🚀 Starting Flask server on http://localhost:{port}")
    print(f"🔧 Debug mode: {debug_mode}")
    print("=" * 60 + "\n")
    
    app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)