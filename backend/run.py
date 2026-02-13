# File: /backend/run.py
#!/usr/bin/env python3

import os
import sys

# Add parent directory to Python path so 'backend' can be found as a package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from backend.app import app
    print("[OK] Successfully imported app")
except ImportError as e:
    print(f"[ERROR] Import error: {e}")
    sys.exit(1)

def create_tables():
    """Create database tables"""
    try:
        with app.app_context():
            from backend.db import Base, engine
            from backend import models
            Base.metadata.create_all(bind=engine)
            print("[OK] Database tables created")
    except Exception as e:
        print(f"[ERROR] Failed to create tables: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run the Flask backend server")
    parser.add_argument("--init-db", action="store_true", help="Initialize database tables")
    args = parser.parse_args()
    
    if args.init_db:
        create_tables()
    
    port = int(os.getenv("PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    print(f"[INFO] Starting Flask server on port {port}, debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
