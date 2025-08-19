# File: /backend/routes/db_routes.py
from flask import request, jsonify
from config import app, db
from models import Customer, Job

@app.route('/customers', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        data = request.json
        new_customer = Customer(
            name=data['name'],
            address=data.get('address', ''),
            phone=data.get('phone', ''),
            email=data.get('email', ''),  # Add email support
            status=data.get('status', 'Active')
        )
        db.session.add(new_customer)
        db.session.commit()
        return jsonify({'id': new_customer.id}), 201
    
    customers = Customer.query.all()
    return jsonify([
        {
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'phone': c.phone,
            'email': c.email,  # Include email in response
            'status': c.status,
            'created_at': c.created_at.isoformat() if c.created_at else None
        } for c in customers
    ])

@app.route('/customers/<int:customer_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'GET':
        return jsonify({
            'id': customer.id,
            'name': customer.name,
            'address': customer.address,
            'phone': customer.phone,
            'email': customer.email,
            'status': customer.status,
            'created_at': customer.created_at.isoformat() if customer.created_at else None
        })
    
    elif request.method == 'PUT':
        data = request.json
        customer.name = data.get('name', customer.name)
        customer.address = data.get('address', customer.address)
        customer.phone = data.get('phone', customer.phone)
        customer.email = data.get('email', customer.email)
        customer.status = data.get('status', customer.status)
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})

@app.route('/jobs', methods=['GET', 'POST'])
def handle_jobs():
    if request.method == 'POST':
        data = request.json
        new_job = Job(
            customer_id=data['customer_id'],
            type=data['type'],
            stage=data['stage'],
            quote_price=data.get('quote_price'),
            delivery_date=data.get('delivery_date')
        )
        db.session.add(new_job)
        db.session.commit()
        return jsonify({'id': new_job.id}), 201
    
    jobs = Job.query.all()
    return jsonify([
        {
            'id': j.id,
            'customer_id': j.customer_id,
            'customer_name': j.customer.name if j.customer else None,
            'type': j.type,
            'stage': j.stage,
            'quote_price': j.quote_price,
            'delivery_date': j.delivery_date.isoformat() if j.delivery_date else None,
            'created_at': j.created_at.isoformat() if j.created_at else None
        } for j in jobs
    ])