# backend/routes/auth_routes_corrected.py
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
import jwt
from datetime import datetime, timedelta
from ..db import SessionLocal

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login endpoint - username/password authentication (plain text for dev)
    """
    print("=" * 60)
    print("🔐 LOGIN ENDPOINT CALLED")
    print("=" * 60)
    
    session = SessionLocal()
    try:
        data = request.get_json()
        print(f"📦 Received data: {data}")
        
        username = data.get('username')
        password = data.get('password')
        
        print(f"👤 Username: '{username}'")
        print(f"🔑 Password: '{password}'")
        
        if not username or not password:
            print("❌ Missing username or password")
            return jsonify({'error': 'Username and password are required'}), 400
        
        # Query user by username
        query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                u.password,
                u.employee_id,
                u.tenant_id,
                u.is_active,
                e.employee_name,
                e.email,
                e.role_ids
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e 
                ON u.employee_id = e.employee_id
            WHERE u.user_name = :username
        """)
        
        print(f"🔍 Searching for user: {username}")
        result = session.execute(query, {'username': username}).fetchone()
        
        if not result:
            print(f"❌ User NOT FOUND in database")
            return jsonify({'error': 'Invalid credentials'}), 401
        
        print(f"✅ User FOUND in database!")
        print(f"   user_id: {result.user_id}")
        print(f"   user_name: '{result.user_name}'")
        print(f"   employee_id: {result.employee_id}")
        print(f"   tenant_id: {result.tenant_id}")
        print(f"   is_active: {result.is_active}")
        print(f"   DB password: '{result.password}'")
        
        # Check if user is active
        if not result.is_active:
            print(f"❌ User account is INACTIVE")
            return jsonify({'error': 'Account is inactive'}), 401
        
        print(f"✅ User is active")
        
        # Verify password (plain text - DEV ONLY)
        print(f"🔐 Comparing passwords:")
        print(f"   Provided: '{password}'")
        print(f"   Stored:   '{result.password}'")
        print(f"   Match: {password == result.password}")
        
        if password != result.password:
            print(f"❌ PASSWORD MISMATCH!")
            return jsonify({'error': 'Invalid credentials'}), 401
        
        print(f"✅ Password matches!")
        
        # Get all roles for this user from User_Role_Mapping
        roles_query = text("""
            SELECT role_id 
            FROM "StreemLyne_MT"."User_Role_Mapping"
            WHERE user_id = :user_id
        """)
        roles_result = session.execute(roles_query, {'user_id': result.user_id}).fetchall()
        role_ids = [r.role_id for r in roles_result] if roles_result else []
        
        print(f"👥 User roles: {role_ids}")
        
        # Determine primary role (use first role or role_id 1 if Platform Admin)
        primary_role_id = role_ids[0] if role_ids else None
        is_platform_admin = 1 in role_ids
        
        # Get role name
        if primary_role_id:
            role_name_query = text("""
                SELECT role_name 
                FROM "StreemLyne_MT"."Role_Master"
                WHERE role_id = :role_id
            """)
            role_name_result = session.execute(
                role_name_query, 
                {'role_id': primary_role_id}
            ).fetchone()
            role_name = role_name_result.role_name if role_name_result else "User"
        else:
            role_name = "User"
        
        print(f"🎭 Role: {role_name} (ID: {primary_role_id})")
        print(f"👑 Is Platform Admin: {is_platform_admin}")
        
        # Generate JWT token
        token_payload = {
            'user_id': result.user_id,
            'username': result.user_name,
            'employee_id': result.employee_id,
            'employee_name': result.employee_name,
            'tenant_id': result.tenant_id,
            'role_id': primary_role_id,
            'roles': role_ids,
            'is_platform_admin': is_platform_admin,
            'exp': datetime.utcnow() + timedelta(days=7)
        }
        
        token = jwt.encode(
            token_payload,
            current_app.config['SECRET_KEY'],
            algorithm='HS256'
        )
        
        print(f"🎟️ JWT token generated successfully")
        print(f"✅ LOGIN SUCCESSFUL!")
        print("=" * 60)
        
        return jsonify({
            'message': 'Login successful',
            'token': token,
            'user': {
                'id': result.user_id,
                'username': result.user_name,
                'employee_id': result.employee_id,
                'employee_name': result.employee_name,
                'email': result.email,
                'tenant_id': result.tenant_id,
                'role': role_name,
                'role_id': primary_role_id,
                'is_platform_admin': is_platform_admin,
                'can_access_dashboard': True  # ✅ Add this - all authenticated users can access
            }
        }), 200
        
    except Exception as e:
        print(f"💥 EXCEPTION OCCURRED!")
        print(f"Error: {e}")
        current_app.logger.error(f"Login error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Login failed', 'details': str(e)}), 500
    finally:
        session.close()

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """
    Get current user info from JWT token
    """
    from .auth_helpers import token_required
    
    @token_required
    def _get_user():
        from flask import request
        user = request.current_user
        
        return jsonify({
            'user': {
                'id': user.id,
                'username': user.username,
                'employee_id': user.employee_id,
                'employee_name': user.employee_name,
                'tenant_id': user.tenant_id,
                'role': user.role,
                'role_id': user.role_id,
                'is_platform_admin': user.role_id == 1 or (hasattr(user, 'roles') and 1 in user.roles)
            }
        }), 200
    
    return _get_user()


@auth_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """
    Refresh JWT token
    """
    from .auth_helpers import token_required
    
    @token_required
    def _refresh():
        from flask import request
        user = request.current_user
        
        # Generate new token
        token_payload = {
            'user_id': user.id,
            'username': user.username,
            'employee_id': user.employee_id,
            'employee_name': user.employee_name,
            'tenant_id': user.tenant_id,
            'role_id': user.role_id,
            'roles': user.roles,
            'exp': datetime.utcnow() + timedelta(days=7)
        }
        
        token = jwt.encode(
            token_payload,
            current_app.config['SECRET_KEY'],
            algorithm='HS256'
        )
        
        return jsonify({
            'message': 'Token refreshed',
            'token': token
        }), 200
    
    return _refresh()


@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    """
    Change user password (plain text - DEV ONLY)
    """
    from .auth_helpers import token_required
    
    @token_required
    def _change_password():
        from flask import request
        session = SessionLocal()
        
        try:
            data = request.get_json()
            current_password = data.get('current_password')
            new_password = data.get('new_password')
            
            if not current_password or not new_password:
                return jsonify({'error': 'Current and new passwords are required'}), 400
            
            user = request.current_user
            
            # Verify current password
            query = text("""
                SELECT password 
                FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """)
            result = session.execute(query, {'user_id': user.id}).fetchone()
            
            if not result or result.password != current_password:
                return jsonify({'error': 'Current password is incorrect'}), 401
            
            # Update password (plain text)
            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET password = :new_password
                WHERE user_id = :user_id
            """)
            
            session.execute(update_query, {
                'new_password': new_password,
                'user_id': user.id
            })
            session.commit()
            
            return jsonify({'message': 'Password changed successfully'}), 200
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Change password error: {e}")
            return jsonify({'error': 'Failed to change password'}), 500
        finally:
            session.close()
    
    return _change_password()