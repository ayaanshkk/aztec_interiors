# File: /backend/routes/form_routes.py
from flask import request, jsonify
from config import app
from models import db
from models import Customer, CustomerFormData
import secrets
import string
import json
from datetime import datetime, timedelta
from flask_cors import CORS

CORS(app, origins="*")

# In-memory storage for form tokens (in production, use Redis or database)
form_tokens = {}

def generate_secure_token(length=32):
    """Generate a cryptographically secure random token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.route('/generate-form-link', methods=['POST'])
def generate_form_link():
    """Generate a secure form link for customers"""
    if request.method == 'OPTIONS':
        response = jsonify()
        
        
        
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
        
        
        
        return response
    
    try:
        data = request.json
        token = data.get('token')
        form_data = data.get('formData', {})
        
        if not form_data:
            response = jsonify({
                'success': False,
                'error': 'Missing form data'
            })
            
            return response, 400
        
        # Validate token if provided
        if token:
            if token not in form_tokens:
                response = jsonify({
                    'success': False,
                    'error': 'Invalid token'
                })
                
                return response, 404
                
            token_data = form_tokens[token]
            if datetime.now() > token_data['expires_at']:
                del form_tokens[token]
                response = jsonify({
                    'success': False,
                    'error': 'Token has expired'
                })
                
                return response, 410
            if token_data['used']:
                response = jsonify({
                    'success': False,
                    'error': 'Token has already been used'
                })
                
                return response, 410

        # Extract customer info
        customer_name = form_data.get('customer_name', '').strip()
        customer_phone = form_data.get('customer_phone', '').strip()
        customer_address = form_data.get('customer_address', '').strip()

        if not customer_name:
            response = jsonify({
                'success': False,
                'error': 'Customer name is required'
            })
            
            return response, 400

        if not customer_address:
            response = jsonify({
                'success': False,
                'error': 'Customer address is required'
            })
            
            return response, 400

        # Create customer and save form data
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
            token_used=token if token else '',
            submitted_at=datetime.utcnow()
        )
        db.session.add(customer_form_data)
        db.session.commit()

        if token and token in form_tokens:
            form_tokens[token]['used'] = True

        response = jsonify({
            'success': True,
            'customer_id': new_customer.id,
            'message': 'Customer created successfully'
        })
        
        return response, 201

    except Exception as e:
        db.session.rollback()
        response = jsonify({
            'success': False,
            'error': f'Form submission failed: {str(e)}'
        })
        
        return response, 500


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