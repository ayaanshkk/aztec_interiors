from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime, timedelta
import jwt
import bcrypt

from ..db import SessionLocal

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    """User login with username and password"""
    session = SessionLocal()
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        # Get user with employee and role info
        query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                u.password,
                u.tenant_id,
                u.employee_id,
                u.is_active,
                e.employee_name,
                e.email,
                e.tenant_id as employee_tenant_id,
                ARRAY_AGG(urm.role_id) as role_ids,
                STRING_AGG(r.role_name, ', ') as role_names
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            LEFT JOIN "StreemLyne_MT"."Role_Master" r ON urm.role_id = r.role_id
            WHERE u.user_name = :username
            GROUP BY u.user_id, u.user_name, u.password, u.tenant_id, u.employee_id,
                     u.is_active, e.employee_name, e.email, e.tenant_id
        """)
        
        user = session.execute(query, {'username': username}).fetchone()
        
        if not user:
            return jsonify({'error': 'Invalid username or password'}), 401
        
        if not user.is_active:
            return jsonify({'error': 'Account is not active. Please contact administrator.'}), 401
        
        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return jsonify({'error': 'Invalid username or password'}), 401
        
        # Use tenant_id from User_Master if available, otherwise from Employee_Master
        tenant_id = user.tenant_id if user.tenant_id else user.employee_tenant_id
        
        # Determine primary role (Platform Admin takes precedence)
        role_ids = user.role_ids if user.role_ids and user.role_ids[0] is not None else []
        is_platform_admin = 1 in role_ids
        primary_role_id = 1 if is_platform_admin else (role_ids[0] if role_ids else 5)
        primary_role_name = 'Platform Admin' if is_platform_admin else user.role_names.split(', ')[0] if user.role_names else 'Salesperson'
        
        # Generate JWT token
        token_payload = {
            'user_id': user.user_id,
            'employee_id': user.employee_id,
            'tenant_id': tenant_id,
            'username': user.user_name,
            'employee_name': user.employee_name,
            'role': primary_role_name,
            'role_id': primary_role_id,
            'roles': role_ids,  # All roles
            'exp': datetime.utcnow() + timedelta(days=30)
        }
        
        token = jwt.encode(token_payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        current_app.logger.info(f"User {username} logged in successfully")
        
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': user.user_id,
                'username': user.user_name,
                'employee_id': user.employee_id,
                'employee_name': user.employee_name,
                'email': user.email,
                'tenant_id': tenant_id,
                'role': primary_role_name,
                'role_id': primary_role_id,
                'is_platform_admin': is_platform_admin
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Login error: {e}")
        return jsonify({'error': 'An error occurred during login'}), 500
    finally:
        session.close()


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Get current user info from JWT token"""
    try:
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Decode JWT
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        # Fetch fresh user data from database
        session = SessionLocal()
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
                    e.tenant_id as employee_tenant_id,
                    ARRAY_AGG(urm.role_id) as role_ids,
                    STRING_AGG(r.role_name, ', ') as role_names
                FROM "StreemLyne_MT"."User_Master" u
                INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
                LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
                LEFT JOIN "StreemLyne_MT"."Role_Master" r ON urm.role_id = r.role_id
                WHERE u.user_id = :user_id
                GROUP BY u.user_id, u.user_name, u.tenant_id, u.employee_id,
                         u.is_active, e.employee_name, e.email, e.tenant_id
            """)
            
            user = session.execute(query, {'user_id': payload['user_id']}).fetchone()
            
            if not user or not user.is_active:
                return jsonify({'error': 'User not found or inactive'}), 401
            
            # Use tenant_id from User_Master if available
            tenant_id = user.tenant_id if user.tenant_id else user.employee_tenant_id
            
            # Determine roles
            role_ids = user.role_ids if user.role_ids and user.role_ids[0] is not None else []
            is_platform_admin = 1 in role_ids
            primary_role_id = 1 if is_platform_admin else (role_ids[0] if role_ids else 5)
            primary_role_name = 'Platform Admin' if is_platform_admin else user.role_names.split(', ')[0] if user.role_names else 'Salesperson'
            
            return jsonify({
                'user': {
                    'id': user.user_id,
                    'username': user.user_name,
                    'employee_id': user.employee_id,
                    'employee_name': user.employee_name,
                    'email': user.email,
                    'tenant_id': tenant_id,
                    'role': primary_role_name,
                    'role_id': primary_role_id,
                    'is_platform_admin': is_platform_admin,
                    'all_roles': role_ids
                }
            }), 200
            
        finally:
            session.close()
        
    except Exception as e:
        current_app.logger.error(f"Error fetching current user: {e}")
        return jsonify({'error': 'Failed to fetch user info'}), 500


@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """Refresh JWT token"""
    try:
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Decode JWT (ignoring expiration for refresh)
        try:
            payload = jwt.decode(
                token, 
                current_app.config['SECRET_KEY'], 
                algorithms=['HS256'],
                options={'verify_exp': False}
            )
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        # Generate new token
        new_payload = {
            'user_id': payload['user_id'],
            'employee_id': payload['employee_id'],
            'tenant_id': payload['tenant_id'],
            'username': payload['username'],
            'employee_name': payload['employee_name'],
            'role': payload['role'],
            'role_id': payload['role_id'],
            'roles': payload.get('roles', []),
            'exp': datetime.utcnow() + timedelta(days=30)
        }
        
        new_token = jwt.encode(new_payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'message': 'Token refreshed successfully',
            'token': new_token
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Token refresh error: {e}")
        return jsonify({'error': 'Failed to refresh token'}), 500


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    """Change user password"""
    try:
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'No token provided'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        # Decode JWT
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        data = request.get_json()
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'error': 'Current password and new password are required'}), 400
        
        session = SessionLocal()
        try:
            # Get user
            query = text("""
                SELECT user_id, password FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """)
            
            user = session.execute(query, {'user_id': payload['user_id']}).fetchone()
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            # Verify current password
            if not bcrypt.checkpw(current_password.encode('utf-8'), user.password.encode('utf-8')):
                return jsonify({'error': 'Current password is incorrect'}), 401
            
            # Hash new password
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Update password
            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET password = :password
                WHERE user_id = :user_id
            """)
            
            session.execute(update_query, {
                'password': hashed_password,
                'user_id': payload['user_id']
            })
            session.commit()
            
            current_app.logger.info(f"Password changed for user {payload['username']}")
            
            return jsonify({'message': 'Password changed successfully'}), 200
            
        finally:
            session.close()
        
    except Exception as e:
        current_app.logger.error(f"Password change error: {e}")
        return jsonify({'error': 'Failed to change password'}), 500