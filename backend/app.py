from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv

from .db import SessionLocal, test_connection

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-in-production"
    )

    print("Testing database connection...")
    try:
        test_connection()
        print("Database connection successful")
    except Exception as e:
        print(f"Database connection failed: {e}")
        import traceback
        traceback.print_exc()

    # ============================================
    # CORS - Manual only (no flask-cors, avoids duplicate headers)
    # ============================================
    ALLOWED_ORIGINS = [
        'https://streemlyne.techmynt.com',
        'https://aztec.techmynt.com',
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ]

    @app.before_request
    def handle_options():
        if request.method == 'OPTIONS':
            origin = request.headers.get('Origin', '')
            response = app.make_default_options_response()
            if origin in ALLOWED_ORIGINS:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Credentials'] = 'true'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Tenant-ID, X-Requested-With'
                response.headers['Access-Control-Max-Age'] = '3600'
            return response

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Tenant-ID, X-Requested-With'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        return response

    # ============================================
    # BLUEPRINTS
    # ============================================

    from .routes.auth_routes import auth_bp
    from .routes.invite_routes import invite_bp
    from .routes.project_routes import project_bp
    from .routes.notification_routes import notification_bp
    from .routes.materials_routes import materials_bp
    from .routes.quotation_routes import quotation_bp
    from .routes.pricelist_routes import pricelist_bp
    from .routes.checklist_routes import checklist_bp
    from .routes.receipt_routes import receipt_bp
    from .routes.invoice_routes import invoice_bp
    from .routes.form_token_routes import form_token_bp
    from .routes.customer_routes import customer_bp
    from .routes.appliance_routes import appliance_bp
    from .routes.file_routes import file_bp
    from .routes.pipeline_routes import pipeline_bp
    from .routes.tasks_routes import tasks_bp
    from .routes.calendar_routes import calendar_bp
    from .routes.action_items_routes import action_items_bp
    from .routes.payment_terms_routes import payment_terms_bp

    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(invite_bp)
    app.register_blueprint(checklist_bp, url_prefix="/api/form")
    app.register_blueprint(receipt_bp, url_prefix="/api/form")
    app.register_blueprint(invoice_bp, url_prefix="/api/form")
    app.register_blueprint(form_token_bp, url_prefix="/api/form")
    app.register_blueprint(customer_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(notification_bp, url_prefix="/api")
    app.register_blueprint(appliance_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(materials_bp, url_prefix="/api")
    app.register_blueprint(pipeline_bp, url_prefix="/api")
    app.register_blueprint(tasks_bp, url_prefix="/api")
    app.register_blueprint(calendar_bp, url_prefix="/api")
    app.register_blueprint(action_items_bp, url_prefix="/api")
    app.register_blueprint(quotation_bp)
    app.register_blueprint(pricelist_bp, url_prefix="/api")
    app.register_blueprint(payment_terms_bp, url_prefix="/api/form")

    # ============================================
    # HEALTH CHECK
    # ============================================

    @app.route("/health", methods=["GET"])
    def health_check():
        session = SessionLocal()
        try:
            from sqlalchemy import text
            session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception as e:
            db_status = f"error: {str(e)}"
        finally:
            session.close()

        return jsonify({
            "status": "ok",
            "message": "StreemLyne API Server",
            "database": db_status,
            "environment": "development" if os.getenv("DEV_MODE", "false").lower() == "true" else "production",
            "version": "2.0.0-mt"
        }), 200

    @app.route("/", methods=["GET"])
    def root():
        return jsonify({
            "message": "StreemLyne Multi-Tenant CRM API",
            "version": "2.0.0",
            "endpoints": {"health": "/health", "api": "/api", "auth": "/api/login"}
        }), 200

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not Found", "message": "The requested endpoint does not exist"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred"}), 500

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({"error": "Forbidden", "message": "You do not have permission to access this resource"}), 403

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)