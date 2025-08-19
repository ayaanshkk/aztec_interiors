# File: /backend/routes/form_routes.py
from flask import request, jsonify
from config import app, db
from models import Customer
import secrets
import string
import json
from datetime import datetime, timedelta

# In-memory storage for form tokens (in production, use Redis or database)
form_tokens = {}

def generate_secure_token(length=32):
    """Generate a cryptographically secure random token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.route('/generate-form-link', methods=['POST', 'OPTIONS'])
def generate_form_link():
    """Generate a secure form link for customers"""
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "POST,OPTIONS")
        return response
    
    try:
        # Generate a unique token
        token = generate_secure_token()
        
        # Store token with expiration (24 hours)
        expiration = datetime.now() + timedelta(hours=24)
        form_tokens[token] = {
            'created_at': datetime.now(),
            'expires_at': expiration,
            'used': False
        }
        
        print(f"Generated form token: {token}")
        print(f"Token expires at: {expiration}")
        
        return jsonify({
            'success': True,
            'token': token,
            'expires_at': expiration.isoformat(),
            'message': 'Form link generated successfully'
        }), 200
        
    except Exception as e:
        print(f"Error generating form link: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to generate form link: {str(e)}'
        }), 500

@app.route('/validate-form-token/<token>', methods=['GET', 'OPTIONS'])
def validate_form_token(token):
    """Validate if a form token is still valid"""
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "GET,OPTIONS")
        return response
    
    try:
        print(f"Validating token: {token}")
        print(f"Available tokens: {list(form_tokens.keys())}")
        
        if token not in form_tokens:
            return jsonify({
                'valid': False,
                'error': 'Invalid token'
            }), 404
            
        token_data = form_tokens[token]
        
        # Check if token has expired
        if datetime.now() > token_data['expires_at']:
            # Clean up expired token
            del form_tokens[token]
            return jsonify({
                'valid': False,
                'error': 'Token has expired'
            }), 410
            
        # Check if token has already been used
        if token_data['used']:
            return jsonify({
                'valid': False,
                'error': 'Token has already been used'
            }), 410
            
        return jsonify({
            'valid': True,
            'expires_at': token_data['expires_at'].isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error validating token: {str(e)}")
        return jsonify({
            'valid': False,
            'error': f'Validation failed: {str(e)}'
        }), 500

@app.route('/submit-customer-form', methods=['POST', 'OPTIONS'])
def submit_customer_form():
    """Handle customer form submission and create new customer"""
    if request.method == 'OPTIONS':
        response = jsonify()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add('Access-Control-Allow-Headers', "Content-Type")
        response.headers.add('Access-Control-Allow-Methods', "POST,OPTIONS")
        return response
    
    try:
        data = request.json
        token = data.get('token')
        form_data = data.get('formData', {})
        
        print(f"Received form submission for token: {token}")
        
        if not token or not form_data:
            return jsonify({
                'success': False,
                'error': 'Missing token or form data'
            }), 400
            
        # Validate token
        if token not in form_tokens:
            return jsonify({
                'success': False,
                'error': 'Invalid token'
            }), 404
            
        token_data = form_tokens[token]
        
        # Check if token has expired
        if datetime.now() > token_data['expires_at']:
            del form_tokens[token]
            return jsonify({
                'success': False,
                'error': 'Token has expired'
            }), 410
            
        # Check if token has already been used
        if token_data['used']:
            return jsonify({
                'success': False,
                'error': 'Token has already been used'
            }), 410
        
        # Extract customer information
        customer_name = form_data.get('customer_name', '').strip()
        customer_phone = form_data.get('customer_phone', '').strip()
        customer_email = form_data.get('customer_email', '').strip()
        customer_address = form_data.get('customer_address', '').strip()
        
        if not customer_name:
            return jsonify({
                'success': False,
                'error': 'Customer name is required'
            }), 400
        
        # Create new customer
        new_customer = Customer(
            name=customer_name,
            phone=customer_phone,
            address=customer_address,
            status='New Lead'  # Default status for form submissions
        )
        
        # Add email field if your Customer model supports it
        if hasattr(new_customer, 'email'):
            new_customer.email = customer_email
        
        db.session.add(new_customer)
        db.session.commit()
        
        # Mark token as used
        form_tokens[token]['used'] = True
        
        # Log the form data for reference
        customer_id = new_customer.id
        print(f"Created customer {customer_id} from form data")
        print(f"Full form data: {json.dumps(form_data, indent=2)}")
        
        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'message': 'Customer created successfully'
        }), 201
        
    except Exception as e:
        print(f"Error submitting customer form: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Form submission failed: {str(e)}'
        }), 500

@app.route('/cleanup-expired-tokens', methods=['POST'])
def cleanup_expired_tokens():
    """Clean up expired form tokens (can be called periodically)"""
    try:
        current_time = datetime.now()
        expired_tokens = [
            token for token, data in form_tokens.items() 
            if current_time > data['expires_at']
        ]
        
        for token in expired_tokens:
            del form_tokens[token]
            
        return jsonify({
            'success': True,
            'cleaned_tokens': len(expired_tokens),
            'remaining_tokens': len(form_tokens)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Cleanup failed: {str(e)}'
        }), 500