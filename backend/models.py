# File: /backend/models.py
from config import db
from datetime import datetime

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(100), nullable=True)  # Add email field
    status = db.Column(db.String(50), default='Active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Customer {self.name}>'

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    type = db.Column(db.String(100), nullable=False)
    stage = db.Column(db.String(50), nullable=False)
    quote_price = db.Column(db.Float, nullable=True)
    delivery_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref=db.backref('jobs', lazy=True))

    def __repr__(self):
        return f'<Job {self.id} for Customer {self.customer_id}>'

# Optional: Create a model to store detailed form data
class CustomerFormData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    form_data = db.Column(db.Text, nullable=False)  # JSON string of form data
    token_used = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    customer = db.relationship('Customer', backref=db.backref('form_data', lazy=True))

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Customer {self.customer_id}>'