from flask import Flask, request, jsonify, g
from flask_cors import CORS
import os
from dotenv import load_dotenv
from .db import Base, engine, SessionLocal, test_connection, init_db
from . import models


load_dotenv()


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ============================================
    # DATABASE INITIALIZATION (NEW LOCATION)
    # ============================================
    print("[INFO] Initializing database schema...")
    try:
        # CRITICAL: Import models FIRST so SQLAlchemy knows about them
        from . import models
        
        # CRITICAL: checkfirst=True ensures we don't drop existing tables
        Base.metadata.create_all(bind=engine, checkfirst=True)
        
        # Verify tables
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"[OK] Database schema initialized - {len(tables)} tables exist")
        
    except Exception as e:
        print(f"[ERROR] Database initialization failed: {e}")
        import traceback
        traceback.print_exc()

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
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    # ============================================
    # REQUEST CONTEXT
    # ============================================
    @app.teardown_appcontext
    def remove_session(exception=None):
        from flask import g
        if 'session' in g:
            g.session.close()

    # ============================================
    # DATABASE SESSION MANAGEMENT
    # ============================================
    @app.before_request
    def get_db_session():
        from flask import g
        if not hasattr(g, 'session'):
            g.session = SessionLocal()
            
    @app.after_request
    def close_db_session(response):
        from flask import g
        if hasattr(g, 'session'):
            g.session.close()
            del g.session
        return response

    # ============================================
    # HEALTH CHECK
    # ============================================
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "message": "Backend is running"})

    # ============================================
    # CONFIGURE STRICT CORS FOR API ROUTES
    # ============================================
    @app.after_request
    def configure_cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Requested-With"
        resp.headers["Access-Control-Max-Age"] = "3600"
        return resp

    # ============================================
    # REGISTER BLUEPRINTS
    # ============================================
    # Import blueprints from routes package
    from .routes import (
        auth_routes, customer_routes, job_routes, 
        db_routes, file_routes, form_routes,
        pricelist_routes, appliance_routes, 
        materials_routes, notification_routes,
        auth_helpers, action_items_routes, assignment_routes,
        quotation_routes
    )
    
    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(customer_routes.customer_bp)
    app.register_blueprint(job_routes.job_bp)
    app.register_blueprint(db_routes.db_bp)
    app.register_blueprint(file_routes.file_bp)
    app.register_blueprint(form_routes.form_bp)
    app.register_blueprint(pricelist_routes.pricelist_bp)
    app.register_blueprint(appliance_routes.appliance_bp)
    app.register_blueprint(materials_routes.materials_bp)
    app.register_blueprint(notification_routes.notification_bp)
    app.register_blueprint(action_items_routes.action_items_bp)
    app.register_blueprint(assignment_routes.assignment_bp)
    app.register_blueprint(quotation_routes.quotation_bp)
    # NOTE: approvals_routes is commented out - uncomment when ready to use
    # app.register_blueprint(approvals_routes.approvals_bp, url_prefix="/api")

    # ============================================
    # ERROR HANDLERS
    # ============================================
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500
        
    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({"error": f"Method not allowed: {error}"}), 405

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    print(f"[INFO] Starting Flask server on port {port}, debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
