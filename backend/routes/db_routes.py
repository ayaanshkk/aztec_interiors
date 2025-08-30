# db_routes.py - Updated customer routes
from flask import Blueprint, request, jsonify
from database import db
from models import Customer, CustomerFormData, Quotation, QuotationItem
import json
from datetime import datetime

# Create blueprint
db_bp = Blueprint('database', __name__)

@db_bp.route('/customers', methods=['GET', 'POST'])
def handle_customers():
    if request.method == 'POST':
        data = request.json
        
        # Create new customer
        customer = Customer(
            name=data.get('name', ''),
            date_of_measure=datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date() if data.get('date_of_measure') else None,
            address=data.get('address', ''),
            phone=data.get('phone', ''),
            email=data.get('email', ''),
            contact_made=data.get('contact_made', 'Unknown'),
            preferred_contact_method=data.get('preferred_contact_method'),
            marketing_opt_in=data.get('marketing_opt_in', False),
            notes=data.get('notes', ''),
            created_by=data.get('created_by', 'System'),  # You might want to get this from auth
            status=data.get('status', 'Active')
        )
        
        customer.save()  # This will auto-extract postcode
        
        return jsonify({
            'id': customer.id,
            'message': 'Customer created successfully'
        }), 201
    
    # GET all customers
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return jsonify([
        {
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'postcode': c.postcode,
            'phone': c.phone,
            'email': c.email,
            'contact_made': c.contact_made,
            'preferred_contact_method': c.preferred_contact_method,
            'marketing_opt_in': c.marketing_opt_in,
            'date_of_measure': c.date_of_measure.isoformat() if c.date_of_measure else None,
            'status': c.status,
            'notes': c.notes,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'created_by': c.created_by
        }
        for c in customers
    ])

@db_bp.route('/customers/<string:customer_id>', methods=['GET', 'PUT', 'DELETE'])
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
            'postcode': customer.postcode,
            'phone': customer.phone,
            'email': customer.email,
            'contact_made': customer.contact_made,
            'preferred_contact_method': customer.preferred_contact_method,
            'marketing_opt_in': customer.marketing_opt_in,
            'date_of_measure': customer.date_of_measure.isoformat() if customer.date_of_measure else None,
            'status': customer.status,
            'notes': customer.notes,
            'created_at': customer.created_at.isoformat() if customer.created_at else None,
            'updated_at': customer.updated_at.isoformat() if customer.updated_at else None,
            'created_by': customer.created_by,
            'updated_by': customer.updated_by,
            'form_submissions': form_submissions
        })
    
    elif request.method == 'PUT':
        data = request.json
        customer.name = data.get('name', customer.name)
        customer.address = data.get('address', customer.address)
        customer.phone = data.get('phone', customer.phone)
        customer.email = data.get('email', customer.email)
        customer.contact_made = data.get('contact_made', customer.contact_made)
        customer.preferred_contact_method = data.get('preferred_contact_method', customer.preferred_contact_method)
        customer.marketing_opt_in = data.get('marketing_opt_in', customer.marketing_opt_in)
        customer.status = data.get('status', customer.status)
        customer.notes = data.get('notes', customer.notes)
        customer.updated_by = data.get('updated_by', 'System')
        
        if data.get('date_of_measure'):
            customer.date_of_measure = datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date()
        
        # Auto-extract postcode if address changed
        if 'address' in data:
            customer.postcode = customer.extract_postcode_from_address()
        
        db.session.commit()
        return jsonify({'message': 'Customer updated successfully'})
    
    elif request.method == 'DELETE':
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': 'Customer deleted successfully'})

@db_bp.route('/customers/<string:customer_id>/generate-form-link', methods=['POST'])
def generate_customer_form_link(customer_id):
    """Generate a form link for an existing customer"""
    customer = Customer.query.get_or_404(customer_id)
    data = request.json
    form_type = data.get('formType', 'general')
    
    # Generate unique token for this form
    import secrets
    token = secrets.token_urlsafe(32)
    
    # Store the token with customer association
    # You might want to create a FormToken model for this
    # For now, we'll return the token
    
    return jsonify({
        'token': token,
        'customer_id': customer_id,
        'form_type': form_type,
        'message': f'Form link generated for customer {customer.name}'
    })

# Keep existing quotation routes unchanged
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
        db.session.flush()

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

    customer_id = request.args.get('customer_id', type=str)
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