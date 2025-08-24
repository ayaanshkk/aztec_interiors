# db_routes.py - Fixed to use Blueprint
from flask import Blueprint, request, jsonify
from database import db
from models import Customer, CustomerFormData, Quotation, QuotationItem
import json
from datetime import datetime

# Create blueprint
db_bp = Blueprint('database', __name__)

@db_bp.route('/customers/<int:customer_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'GET':
        # Fetch all form submissions for this customer
        form_entries = CustomerFormData.query.filter_by(customer_id=customer.id).all()
        form_submissions = []
        for f in form_entries:
            try:
                parsed = json.loads(f.form_data)
            except Exception:
                parsed = {"raw": f.form_data}
            form_submissions.append({
                "id": f.id,
                "token_used": f.token_used,
                "submitted_at": f.submitted_at.isoformat() if f.submitted_at else None,
                "form_data": parsed
            })

        return jsonify({
            'id': customer.id,
            'name': customer.name,
            'address': customer.address,
            'phone': customer.phone,
            'email': customer.email,
            'status': customer.status,
            'created_at': customer.created_at.isoformat() if customer.created_at else None,
            'form_submissions': form_submissions
        })
    
    elif request.method == 'PUT':
        data = request.json
        customer.name = data.get('name', customer.name)
        customer.address = data.get('address', customer.address)
        customer.phone = data.get('phone', customer.phone)
        customer.email = data.get('email', customer.email)
        customer.status = data.get('status', customer.status)
        
        if 'form_submissions' in data and data['form_submissions']:
            form_sub = data['form_submissions'][0]
            if 'form_data' in form_sub:
                form_entry = CustomerFormData.query.filter_by(customer_id=customer.id).order_by(CustomerFormData.id.asc()).first()
                if form_entry:
                    form_entry.form_data = json.dumps(form_sub['form_data'])
                else:
                    new_form = CustomerFormData(
                        customer_id=customer.id,
                        form_data=json.dumps(form_sub['form_data']),
                        token_used='',
                        submitted_at=datetime.utcnow()
                    )
                    db.session.add(new_form)
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})
    
@db_bp.route('/customers', methods=['GET'])
def get_customers():
    customers = Customer.query.all()
    return jsonify([
        {
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'phone': c.phone,
            'email': c.email,
            'status': c.status,
            'created_at': c.created_at.isoformat() if c.created_at else None
        }
        for c in customers
    ])

@db_bp.route('/quotations', methods=['GET', 'POST'])
def handle_quotations():
    if request.method == 'POST':
        data = request.json
        quotation = Quotation(
            customer_id=data['customer_id'],
            total=data['total'],
            notes=data.get('notes')
        )
        db.session.add(quotation)
        db.session.flush()  # get quotation.id before committing

        # Add items
        for item in data.get('items', []):
            q_item = QuotationItem(
                quotation_id=quotation.id,
                item=item['item'],
                description=item.get('description'),
                color=item.get('color'),
                amount=item['amount']
            )
            db.session.add(q_item)

        db.session.commit()
        return jsonify({'id': quotation.id}), 201

    # GET all quotations, optionally filtered by customer_id
    customer_id = request.args.get('customer_id', type=int)
    if customer_id:
        quotations = Quotation.query.filter_by(customer_id=customer_id).all()
    else:
        quotations = Quotation.query.all()
        
    return jsonify([
        {
            'id': q.id,
            'customer_id': q.customer_id,
            'customer_name': q.customer.name if q.customer else None,
            'total': q.total,
            'notes': q.notes,
            'created_at': q.created_at.isoformat() if q.created_at else None,
            'items': [
                {
                    'id': i.id,
                    'item': i.item,
                    'description': i.description,
                    'color': i.color,
                    'amount': i.amount
                } for i in q.items
            ]
        } for q in quotations
    ])

@db_bp.route('/quotations/<int:quotation_id>', methods=['GET', 'PUT', 'DELETE'])
def handle_single_quotation(quotation_id):
    quotation = Quotation.query.get_or_404(quotation_id)

    if request.method == 'GET':
        return jsonify({
            'id': quotation.id,
            'customer_id': quotation.customer_id,
            'customer_name': quotation.customer.name if quotation.customer else None,
            'total': quotation.total,
            'notes': quotation.notes,
            'created_at': quotation.created_at.isoformat() if quotation.created_at else None,
            'updated_at': quotation.updated_at.isoformat() if quotation.updated_at else None,
            'items': [
                {
                    'id': i.id,
                    'item': i.item,
                    'description': i.description,
                    'color': i.color,
                    'amount': i.amount
                } for i in quotation.items
            ]
        })

    elif request.method == 'PUT':
        data = request.json
        quotation.total = data.get('total', quotation.total)
        quotation.notes = data.get('notes', quotation.notes)

        # Replace items
        if 'items' in data:
            QuotationItem.query.filter_by(quotation_id=quotation.id).delete()
            for item in data['items']:
                q_item = QuotationItem(
                    quotation_id=quotation.id,
                    item=item['item'],
                    description=item.get('description'),
                    color=item.get('color'),
                    amount=item['amount']
                )
                db.session.add(q_item)

        db.session.commit()
        return jsonify({'message': 'Quotation updated successfully'})

    elif request.method == 'DELETE':
        db.session.delete(quotation)
        db.session.commit()
        return jsonify({'message': 'Quotation deleted successfully'})