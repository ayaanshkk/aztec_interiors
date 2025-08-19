# File: /backend/app.py
from flask import Flask
from flask_cors import CORS
from config import app, db

# Import models first
from models import Customer, Job

# Import all routes
from routes import db_routes, file_routes, form_routes

# Enable CORS for all routes
CORS(app, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database tables created successfully!")
    
    print("Starting Flask server...")
    app.run(debug=True, host='127.0.0.1', port=5000)