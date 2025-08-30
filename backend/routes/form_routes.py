# routes/form_routes.py
from flask import Blueprint, request, jsonify, current_app
from models import db, Customer, CustomerFormData
import secrets
import string
import json
from datetime import datetime, timedelta

form_bp = Blueprint("form", __name__)

# In-memory storage for form tokens (for production use Redis/DB)
form_tokens = {}

def generate_secure_token(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@form_bp.route('/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_form_link():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        token = generate_secure_token()
        expiration = datetime.now() + timedelta(hours=24)
        form_tokens[token] = {
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        current_app.logger.debug(f"Generated token {token} expires {expiration}")

        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expiration.isoformat(),
            'message': 'Form link generated successfully'
        }), 200

    except Exception as e:
        current_app.logger.exception("Failed to generate form link")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500

@form_bp.route('/validate-form-token/<token>', methods=['GET', 'OPTIONS'])
def validate_form_token(token):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_app.logger.debug(f"Validating token: {token}")
        if token not in form_tokens:
            return jsonify({'valid': False, 'error': 'Invalid token'}), 404

        token_data = form_tokens[token]

        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({'valid': False, 'error': 'Token has expired'}), 410

        if token_data['used']:
            return jsonify({'valid': False, 'error': 'Token has already been used'}), 410

        return jsonify({'valid': True, 'expires_at': token_data['expires_at'].isoformat()}), 200

    except Exception as e:
        current_app.logger.exception("Token validation failed")
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'}), 500

@form_bp.route('/submit-customer-form', methods=['POST', 'OPTIONS'])
def submit_customer_form():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        data = request.get_json(silent=True) or {}
        token = data.get('token')
        form_data = data.get('formData', {})

        if not form_data:
            return jsonify({'success': False, 'error': 'Missing form data'}), 400

        # Validate token if provided
        if token:
            if token not in form_tokens:
                return jsonify({'success': False, 'error': 'Invalid token'}), 404

            token_data = form_tokens[token]
            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                return jsonify({'success': False, 'error': 'Token has expired'}), 410
            if token_data['used']:
                return jsonify({'success': False, 'error': 'Token has already been used'}), 410

        customer_name = (form_data.get('customer_name') or '').strip()
        customer_phone = (form_data.get('customer_phone') or '').strip()
        customer_address = (form_data.get('customer_address') or '').strip()

        if not customer_name:
            return jsonify({'success': False, 'error': 'Customer name is required'}), 400
        if not customer_address:
            return jsonify({'success': False, 'error': 'Customer address is required'}), 400

        new_customer = Customer(
            name=customer_name,
            phone=customer_phone,
            address=customer_address,
            status='New Lead'
        )
        db.session.add(new_customer)
        db.session.flush()

        customer_form_data = CustomerFormData(
            customer_id=new_customer.id,
            form_data=json.dumps(form_data),
            token_used=token or '',
            submitted_at=datetime.utcnow()
        )
        db.session.add(customer_form_data)
        db.session.commit()

        if token and token in form_tokens:
            form_tokens[token]['used'] = True

        return jsonify({'success': True, 'customer_id': new_customer.id, 'message': 'Customer created successfully'}), 201

    except Exception as e:
        current_app.logger.exception("Form submission failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Form submission failed: {str(e)}'}), 500

@form_bp.route('/cleanup-expired-tokens', methods=['POST', 'OPTIONS'])
def cleanup_expired_tokens():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        current_time = datetime.now()
        expired_tokens = [t for t, d in form_tokens.items() if current_time > d['expires_at']]
        for t in expired_tokens:
            del form_tokens[t]
        return jsonify({'success': True, 'cleaned_tokens': len(expired_tokens), 'remaining_tokens': len(form_tokens)}), 200
    except Exception as e:
        current_app.logger.exception("Cleanup failed")
        return jsonify({'success': False, 'error': f'Cleanup failed: {str(e)}'}), 500
