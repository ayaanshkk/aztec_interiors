# backend/app.py - CORRECTED for StreemLyne_MT schema

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv

from .db import SessionLocal, test_connection

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-in-production"
    )

    # ============================================
    # DATABASE CONNECTION TEST
    # ============================================
    print("Testing database connection...")
    try:
        test_connection()
        print("Database connection successful")
    except Exception as e:
        print(f"Database connection failed: {e}")
        import traceback
        traceback.print_exc()

    # ============================================
    # CORS
    # ============================================
    #
    # Keep CORS configuration in ONE place.
    #
    # Explicitly allowed production/local origins:
    # - localhost development
    # - Vercel production deployment
    # - custom StreemLyne domain
    #
    # The regex also allows Vercel preview deployments:
    # https://anything.vercel.app
    #
    # Credentials are enabled because the frontend may
    # send authentication credentials/cookies.
    #
    allowed_origins = [
        r"http://localhost:3000",
        r"http://127\.0\.0\.1:3000",
        r"https://streemlyne\.vercel\.app",
        r"https://streemlyne\.techmynt\.com",
        r"https://[a-zA-Z0-9-]+\.vercel\.app",
    ]

    CORS(
        app,
        resources={
            r"/*": {
                "origins": allowed_origins,
                "methods": [
                    "GET",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                ],
                "allow_headers": [
                    "Content-Type",
                    "Authorization",
                    "X-Requested-With",
                    "X-Tenant-ID",
                ],
                "expose_headers": [
                    "Content-Type",
                    "Authorization",
                ],
                "supports_credentials": True,
                "max_age": 3600,
            }
        },
    )

    # ============================================
    # BLUEPRINTS - Direct imports
    # ============================================

    from .routes.auth_routes import auth_bp
    from .routes.invite_routes import invite_bp
    from .routes.project_routes import project_bp
    from .routes.notification_routes import notification_bp
    from .routes.materials_routes import materials_bp
    from .routes.quotation_routes import quotation_bp
    from .routes.pricelist_routes import pricelist_bp

    # Split form routes
    from .routes.checklist_routes import checklist_bp
    from .routes.receipt_routes import receipt_bp
    from .routes.invoice_routes import invoice_bp
    from .routes.form_token_routes import form_token_bp

    # Existing routes
    from .routes.customer_routes import customer_bp
    from .routes.appliance_routes import appliance_bp
    from .routes.file_routes import file_bp
    from .routes.pipeline_routes import pipeline_bp
    from .routes.tasks_routes import tasks_bp
    from .routes.calendar_routes import calendar_bp
    from .routes.action_items_routes import action_items_bp
    from .routes.payment_terms_routes import payment_terms_bp

    # ============================================
    # REGISTER BLUEPRINTS
    # ============================================

    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(invite_bp)

    app.register_blueprint(
        checklist_bp,
        url_prefix="/api/form"
    )

    app.register_blueprint(
        receipt_bp,
        url_prefix="/api/form"
    )

    app.register_blueprint(
        invoice_bp,
        url_prefix="/api/form"
    )

    app.register_blueprint(
        form_token_bp,
        url_prefix="/api/form"
    )

    app.register_blueprint(customer_bp)
    app.register_blueprint(project_bp)

    app.register_blueprint(
        notification_bp,
        url_prefix="/api"
    )

    app.register_blueprint(appliance_bp)
    app.register_blueprint(file_bp)

    app.register_blueprint(
        materials_bp,
        url_prefix="/api"
    )

    app.register_blueprint(
        pipeline_bp,
        url_prefix="/api"
    )

    app.register_blueprint(
        tasks_bp,
        url_prefix="/api"
    )

    app.register_blueprint(
        calendar_bp,
        url_prefix="/api"
    )

    app.register_blueprint(
        action_items_bp,
        url_prefix="/api"
    )

    app.register_blueprint(quotation_bp)

    app.register_blueprint(
        pricelist_bp,
        url_prefix="/api"
    )

    app.register_blueprint(
        payment_terms_bp,
        url_prefix="/api/form"
    )

    # ============================================
    # HEALTH CHECK
    # ============================================

    @app.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint."""

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
            "environment": (
                "development"
                if os.getenv("DEV_MODE", "false").lower() == "true"
                else "production"
            ),
            "version": "2.0.0-mt"
        }), 200

    # ============================================
    # ROOT
    # ============================================

    @app.route("/", methods=["GET"])
    def root():
        """Root endpoint."""

        return jsonify({
            "message": "StreemLyne Multi-Tenant CRM API",
            "version": "2.0.0",
            "endpoints": {
                "health": "/health",
                "api": "/api",
                "auth": "/api/login"
            }
        }), 200

    # ============================================
    # ERROR HANDLERS
    # ============================================

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            "error": "Not Found",
            "message": "The requested endpoint does not exist"
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        }), 500

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            "error": "Unauthorized",
            "message": "Authentication required"
        }), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            "error": "Forbidden",
            "message": "You do not have permission to access this resource"
        }), 403

    return app


# ============================================
# STANDALONE LAUNCH
# ============================================

if __name__ == "__main__":
    app = create_app()

    print("\n" + "=" * 60)
    print("STREEMLYNE MULTI-TENANT CRM API")
    print("=" * 60)

    print("\nDatabase Schema: StreemLyne_MT")
    print("Authentication: JWT with username/password")
    print("Multi-Tenant: tenant_id isolation")
    print("Roles: Platform Admin (1), Salesperson (5)")

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"

    print(f"\nStarting Flask server on http://localhost:{port}")
    print(f"Debug mode: {debug_mode}")
    print(f"Health check: http://localhost:{port}/health")

    print("=" * 60 + "\n")

    app.run(
        debug=debug_mode,
        host="0.0.0.0",
        port=port,
        threaded=True
    )