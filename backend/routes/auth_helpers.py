# backend/routes/auth_helpers.py
from functools import wraps
from flask import request, jsonify, current_app
import jwt
from sqlalchemy import text
from ..db import SessionLocal


def token_required(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # "Bearer <token>"
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode JWT token
            payload = jwt.decode(
                token, 
                current_app.config['SECRET_KEY'], 
                algorithms=['HS256']
            )
            
            # Extract user info from payload
            request.current_user = type('User', (), {
                'id': payload.get('user_id'),
                'employee_id': payload.get('employee_id'),
                'tenant_id': payload.get('tenant_id'),
                'username': payload.get('username'),
                'employee_name': payload.get('employee_name'),
                'role': payload.get('role'),
                'role_id': payload.get('role_id'),
                'roles': payload.get('roles', []),
            })()
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            current_app.logger.error(f"Token verification error: {e}")
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated


def require_tenant(f):
    """
    Decorator to extract tenant_id and employee_id from JWT token.
    Must be used AFTER @token_required
    
    Usage:
        @token_required
        @require_tenant
        def my_route(tenant_id, employee_id):
            # tenant_id and employee_id are now available
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(request, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        tenant_id = request.current_user.tenant_id
        employee_id = request.current_user.employee_id
        
        if not tenant_id:
            return jsonify({'error': 'Tenant ID not found in token'}), 401
        
        if not employee_id:
            return jsonify({'error': 'Employee ID not found in token'}), 401
        
        # Pass tenant_id and employee_id as first two arguments
        return f(tenant_id, employee_id, *args, **kwargs)
    
    return decorated


def get_current_user():
    """
    Helper function to get current user from request context.
    Returns None if no user is authenticated.
    """
    return getattr(request, 'current_user', None)


def verify_platform_admin():
    """
    Check if current user is a Platform Admin (role_id = 1).
    Returns True if Platform Admin, False otherwise.
    """
    user = get_current_user()
    if not user:
        return False
    
    # Check if role_id is 1 OR if 1 is in the roles array
    return user.role_id == 1 or (hasattr(user, 'roles') and 1 in user.roles)


def require_platform_admin(f):
    """
    Decorator to require Platform Admin access.
    Must be used AFTER @token_required
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not verify_platform_admin():
            return jsonify({'error': 'Platform Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated


def get_user_from_db(user_id, session=None):
    """
    Fetch user details from database using raw SQL.
    
    Args:
        user_id: The user's ID
        session: Optional SQLAlchemy session (will create one if not provided)
    
    Returns:
        User object or None if not found
    """
    should_close = False
    if session is None:
        session = SessionLocal()
        should_close = True
    
    try:
        query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                u.tenant_id,
                u.employee_id,
                u.is_active,
                e.employee_name,
                e.email,
                ARRAY_AGG(urm.role_id) as role_ids
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            WHERE u.user_id = :user_id
            GROUP BY u.user_id, u.user_name, u.tenant_id, u.employee_id,
                     u.is_active, e.employee_name, e.email
        """)
        
        result = session.execute(query, {'user_id': user_id}).fetchone()
        
        if not result or not result.is_active:
            return None
        
        # Create a simple user object
        role_ids = result.role_ids if result.role_ids and result.role_ids[0] is not None else []
        is_platform_admin = 1 in role_ids
        
        return type('User', (), {
            'id': result.user_id,
            'user_id': result.user_id,
            'username': result.user_name,
            'employee_id': result.employee_id,
            'employee_name': result.employee_name,
            'email': result.email,
            'tenant_id': result.tenant_id,
            'role_ids': role_ids,
            'is_platform_admin': is_platform_admin,
            'is_active': result.is_active
        })()
        
    finally:
        if should_close:
            session.close()