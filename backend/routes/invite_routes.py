from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime, timedelta
import secrets
import string
import bcrypt

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

invite_bp = Blueprint('invites', __name__)

def generate_invite_token(length=32):
    """Generate a secure random token for invites"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ==========================================
# DECORATOR: Platform Admin Only (role_id = 1)
# ==========================================

def platform_admin_required(f):
    """Decorator to check if user has Platform Admin role (role_id = 1)"""
    from functools import wraps
    
    @wraps(f)
    @token_required
    @require_tenant
    def decorated_function(tenant_id, employee_id, *args, **kwargs):
        session = SessionLocal()
        try:
            # Get user_id from employee
            user_query = text("""
                SELECT user_id FROM "StreemLyne_MT"."User_Master"
                WHERE employee_id = :employee_id AND tenant_id = :tenant_id
            """)
            
            user = session.execute(user_query, {
                'employee_id': employee_id,
                'tenant_id': str(tenant_id)
            }).fetchone()
            
            if not user:
                return jsonify({'error': 'User not found'}), 403
            
            # Check if user has Platform Admin role (role_id = 1) via User_Role_Mapping
            role_query = text("""
                SELECT EXISTS (
                    SELECT 1 FROM "StreemLyne_MT"."User_Role_Mapping"
                    WHERE user_id = :user_id AND role_id = 1
                ) as is_platform_admin
            """)
            
            result = session.execute(role_query, {'user_id': user.user_id}).fetchone()
            
            if not result.is_platform_admin:
                return jsonify({'error': 'Unauthorized - Platform Admin access required'}), 403
            
            return f(tenant_id, employee_id, *args, **kwargs)
            
        finally:
            session.close()
    
    return decorated_function


# ==========================================
# CREATE INVITE (Platform Admin only)
# ==========================================

@invite_bp.route('/invites/create', methods=['POST'])
@platform_admin_required
def create_invite(tenant_id, employee_id):
    """Create a new user invite (Platform Admin only)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        email = data.get('email')
        username = data.get('username')  # Username for login
        role_id = data.get('role_id')  # 1=Platform Admin, 5=Salesperson
        employee_name = data.get('employee_name')
        
        if not email or not username or not role_id or not employee_name:
            return jsonify({'error': 'Email, username, role_id, and employee_name are required'}), 400
        
        # Validate role_id (1=Platform Admin, 5=Salesperson)
        if role_id not in [1, 5]:
            return jsonify({'error': 'Invalid role_id. Use 1 for Platform Admin or 5 for Salesperson'}), 400
        
        # Check if username already exists
        existing_user_query = text("""
            SELECT user_id FROM "StreemLyne_MT"."User_Master"
            WHERE user_name = :username AND tenant_id = :tenant_id
        """)
        existing_user = session.execute(existing_user_query, {
            'username': username,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if existing_user:
            return jsonify({'error': 'Username already exists'}), 400
        
        # Check if email already exists in employees
        existing_email_query = text("""
            SELECT employee_id FROM "StreemLyne_MT"."Employee_Master"
            WHERE email = :email AND tenant_id = :tenant_id
        """)
        existing_email = session.execute(existing_email_query, {
            'email': email,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if existing_email:
            return jsonify({'error': 'Email already exists'}), 400
        
        # Check for pending invite
        pending_invite_query = text("""
            SELECT user_id FROM "StreemLyne_MT"."User_Master"
            WHERE user_name = :username 
                AND tenant_id = :tenant_id
                AND is_invite_pending = true
                AND invite_expires_at > CURRENT_TIMESTAMP
        """)
        pending_invite = session.execute(pending_invite_query, {
            'username': username,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if pending_invite:
            return jsonify({'error': 'An active invite already exists for this username'}), 400
        
        # Generate invite token
        invite_token = generate_invite_token()
        expires_at = datetime.utcnow() + timedelta(days=7)
        
        # Create employee record first
        employee_insert = text("""
            INSERT INTO "StreemLyne_MT"."Employee_Master"
            (tenant_id, employee_name, email, is_active)
            VALUES (:tenant_id, :employee_name, :email, false)
            RETURNING employee_id
        """)
        
        emp_result = session.execute(employee_insert, {
            'tenant_id': str(tenant_id),
            'employee_name': employee_name,
            'email': email
        })
        new_employee_id = emp_result.fetchone().employee_id
        
        # Create user record with invite
        user_insert = text("""
            INSERT INTO "StreemLyne_MT"."User_Master"
            (tenant_id, user_name, employee_id, is_invite_pending, 
             invite_token, invite_expires_at, created_by_employee_id, is_active)
            VALUES (:tenant_id, :username, :employee_id, true,
                    :invite_token, :expires_at, :created_by, false)
            RETURNING user_id
        """)
        
        user_result = session.execute(user_insert, {
            'tenant_id': str(tenant_id),
            'username': username,
            'employee_id': new_employee_id,
            'invite_token': invite_token,
            'expires_at': expires_at,
            'created_by': employee_id
        })
        new_user_id = user_result.fetchone().user_id
        
        # Add role mapping
        role_insert = text("""
            INSERT INTO "StreemLyne_MT"."User_Role_Mapping"
            (user_id, role_id)
            VALUES (:user_id, :role_id)
        """)
        session.execute(role_insert, {
            'user_id': new_user_id,
            'role_id': role_id
        })
        
        session.commit()
        
        # Generate registration link
        registration_link = f"{request.host_url}register?token={invite_token}"
        
        # Get role name
        role_name = 'Platform Admin' if role_id == 1 else 'Salesperson'
        
        current_app.logger.info(f"Invite created for {username} ({role_name}) by employee {employee_id}")
        
        return jsonify({
            'message': 'Invite created successfully',
            'invite': {
                'id': new_user_id,
                'username': username,
                'email': email,
                'employee_name': employee_name,
                'role_id': role_id,
                'role_name': role_name,
                'token': invite_token,
                'registration_link': registration_link,
                'expires_at': expires_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# GET ALL INVITES (Platform Admin only)
# ==========================================

@invite_bp.route('/invites', methods=['GET'])
@platform_admin_required
def get_invites(tenant_id, employee_id):
    """Get all pending invites (Platform Admin only)"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                e.employee_name,
                e.email,
                urm.role_id,
                CASE 
                    WHEN urm.role_id = 1 THEN 'Platform Admin'
                    WHEN urm.role_id = 5 THEN 'Salesperson'
                    ELSE 'Unknown'
                END as role_name,
                u.invite_token,
                u.invite_expires_at,
                u.created_at,
                u.created_by_employee_id,
                creator.employee_name as created_by_name
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" creator ON u.created_by_employee_id = creator.employee_id
            WHERE u.tenant_id = :tenant_id 
                AND u.is_invite_pending = true
            ORDER BY u.created_at DESC
        """)
        
        invites = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        invite_list = []
        for invite in invites:
            is_valid = invite.invite_expires_at > datetime.utcnow() if invite.invite_expires_at else False
            
            invite_list.append({
                'id': invite.user_id,
                'username': invite.user_name,
                'email': invite.email,
                'employee_name': invite.employee_name,
                'role_id': invite.role_id,
                'role_name': invite.role_name,
                'created_by': invite.created_by_name or 'System',
                'created_at': invite.created_at.isoformat() if invite.created_at else None,
                'expires_at': invite.invite_expires_at.isoformat() if invite.invite_expires_at else None,
                'is_valid': is_valid,
                'registration_link': f"{request.host_url}register?token={invite.invite_token}"
            })
        
        return jsonify({'invites': invite_list}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching invites: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# DELETE/REVOKE INVITE (Platform Admin only)
# ==========================================

@invite_bp.route('/invites/<int:invite_id>', methods=['DELETE'])
@platform_admin_required
def delete_invite(tenant_id, employee_id, invite_id):
    """Delete/revoke a pending invite (Platform Admin only)"""
    session = SessionLocal()
    try:
        # Check if invite exists and is pending
        check_query = text("""
            SELECT u.user_id, u.employee_id, u.is_invite_pending
            FROM "StreemLyne_MT"."User_Master" u
            WHERE u.user_id = :user_id AND u.tenant_id = :tenant_id
        """)
        
        invite = session.execute(check_query, {
            'user_id': invite_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not invite:
            return jsonify({'error': 'Invite not found'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'error': 'Cannot delete a completed invite'}), 400
        
        # Delete role mapping
        delete_role = text("""
            DELETE FROM "StreemLyne_MT"."User_Role_Mapping"
            WHERE user_id = :user_id
        """)
        session.execute(delete_role, {'user_id': invite_id})
        
        # Delete user record
        delete_user = text("""
            DELETE FROM "StreemLyne_MT"."User_Master"
            WHERE user_id = :user_id AND tenant_id = :tenant_id
        """)
        session.execute(delete_user, {
            'user_id': invite_id,
            'tenant_id': str(tenant_id)
        })
        
        # Delete employee record
        delete_employee = text("""
            DELETE FROM "StreemLyne_MT"."Employee_Master"
            WHERE employee_id = :employee_id AND tenant_id = :tenant_id
        """)
        session.execute(delete_employee, {
            'employee_id': invite.employee_id,
            'tenant_id': str(tenant_id)
        })
        
        session.commit()
        
        current_app.logger.info(f"Invite {invite_id} deleted by Platform Admin {employee_id}")
        
        return jsonify({'message': 'Invite deleted successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# VALIDATE INVITE TOKEN (Public - no auth)
# ==========================================

@invite_bp.route('/invites/validate/<token>', methods=['GET'])
def validate_invite(token):
    """Validate an invite token (public endpoint)"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                u.is_invite_pending,
                u.invite_expires_at,
                e.employee_name,
                e.email,
                urm.role_id,
                CASE 
                    WHEN urm.role_id = 1 THEN 'Platform Admin'
                    WHEN urm.role_id = 5 THEN 'Salesperson'
                    ELSE 'Unknown'
                END as role_name
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            WHERE u.invite_token = :token
        """)
        
        invite = session.execute(query, {'token': token}).fetchone()
        
        if not invite:
            return jsonify({'valid': False, 'error': 'Invalid invite token'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'valid': False, 'error': 'Invite already used'}), 400
        
        if invite.invite_expires_at and invite.invite_expires_at < datetime.utcnow():
            return jsonify({'valid': False, 'error': 'Invite expired'}), 400
        
        return jsonify({
            'valid': True,
            'username': invite.user_name,
            'email': invite.email,
            'employee_name': invite.employee_name,
            'role': invite.role_name,
            'role_id': invite.role_id,
            'expires_at': invite.invite_expires_at.isoformat() if invite.invite_expires_at else None
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error validating invite: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# REGISTER WITH INVITE TOKEN (Public - no auth)
# ==========================================

@invite_bp.route('/register', methods=['POST'])
def register_with_invite():
    """Complete registration using invite token (public endpoint)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        token = data.get('token')
        password = data.get('password')
        
        if not token or not password:
            return jsonify({'error': 'Token and password are required'}), 400
        
        # Validate invite
        invite_query = text("""
            SELECT 
                u.user_id,
                u.user_name,
                u.tenant_id,
                u.employee_id,
                u.is_invite_pending,
                u.invite_expires_at,
                e.employee_name,
                e.email,
                urm.role_id,
                CASE 
                    WHEN urm.role_id = 1 THEN 'Platform Admin'
                    WHEN urm.role_id = 5 THEN 'Salesperson'
                    ELSE 'Unknown'
                END as role_name
            FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."Employee_Master" e ON u.employee_id = e.employee_id
            LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            WHERE u.invite_token = :token
        """)
        
        invite = session.execute(invite_query, {'token': token}).fetchone()
        
        if not invite:
            return jsonify({'error': 'Invalid invite token'}), 404
        
        if not invite.is_invite_pending:
            return jsonify({'error': 'Invite already used'}), 400
        
        if invite.invite_expires_at and invite.invite_expires_at < datetime.utcnow():
            return jsonify({'error': 'Invite expired'}), 400
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Update user record
        update_user = text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET password = :password,
                is_invite_pending = false,
                invite_token = NULL,
                invite_expires_at = NULL,
                is_active = true
            WHERE user_id = :user_id
        """)
        
        session.execute(update_user, {
            'password': hashed_password,
            'user_id': invite.user_id
        })
        
        # Activate employee
        update_employee = text("""
            UPDATE "StreemLyne_MT"."Employee_Master"
            SET is_active = true
            WHERE employee_id = :employee_id
        """)
        
        session.execute(update_employee, {
            'employee_id': invite.employee_id
        })
        
        session.commit()
        
        current_app.logger.info(f"User {invite.user_name} completed registration as {invite.role_name}")
        
        # Generate JWT token for immediate login
        import jwt
        
        token_payload = {
            'user_id': invite.user_id,
            'employee_id': invite.employee_id,
            'tenant_id': invite.tenant_id,
            'username': invite.user_name,
            'employee_name': invite.employee_name,
            'role': invite.role_name,
            'role_id': invite.role_id,
            'exp': datetime.utcnow() + timedelta(days=30)
        }
        auth_token = jwt.encode(token_payload, current_app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'message': 'Registration successful',
            'token': auth_token,
            'user': {
                'id': invite.user_id,
                'username': invite.user_name,
                'employee_name': invite.employee_name,
                'email': invite.email,
                'role': invite.role_name,
                'role_id': invite.role_id,
                'tenant_id': invite.tenant_id
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error completing registration: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()