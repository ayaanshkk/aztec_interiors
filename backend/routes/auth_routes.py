# backend/routes/auth_routes_corrected.py
from unittest import result

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
import jwt
from datetime import datetime, timedelta
from ..db import SessionLocal
from werkzeug.security import check_password_hash, generate_password_hash

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
        print(f"🔐 Verifying hashed password...")
        print(f"   Password hash starts with: {result.password[:20]}...")

        is_valid = check_password_hash(result.password, password)
        print(f"   Password valid: {is_valid}")

        if not is_valid:
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
        
        # Determine primary role (use first role or role_id 2 if Platform Admin)
        primary_role_id = role_ids[0] if role_ids else None
        is_platform_admin = 2 in role_ids
        
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
                'is_platform_admin': user.role_id == 2 or (hasattr(user, 'roles') and 2 in user.roles)  
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
            
            if not result or not check_password_hash(result.password, current_password):
                return jsonify({'error': 'Current password is incorrect'}), 401

            # Update password (hash it first)
            new_password_hash = generate_password_hash(new_password)

            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET password = :new_password_hash
                WHERE user_id = :user_id
            """)

            session.execute(update_query, {
                'new_password_hash': new_password_hash,
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

@auth_bp.route('/users', methods=['GET'])
def get_all_users():
    """
    Get all users - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    
    @token_required
    def _get_users():
        from flask import request
        user = request.current_user
        
        # Check permission: Platform Admin (role_id 2) or Salesperson (role_id 3)
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        session = SessionLocal()
        try:
            query = text("""
                SELECT 
                    u.user_id,
                    u.user_name,
                    u.employee_id,
                    u.is_active,
                    e.employee_name,
                    e.email,
                    e.first_name,
                    e.last_name,
                    r.role_name,
                    CASE WHEN u.password IS NULL OR u.password = '' THEN true ELSE false END as is_invited,
                    u.invitation_token
                FROM "StreemLyne_MT"."User_Master" u
                INNER JOIN "StreemLyne_MT"."Employee_Master" e 
                    ON u.employee_id = e.employee_id
                LEFT JOIN "StreemLyne_MT"."User_Role_Mapping" urm 
                    ON u.user_id = urm.user_id
                LEFT JOIN "StreemLyne_MT"."Role_Master" r 
                    ON urm.role_id = r.role_id
                WHERE u.tenant_id = :tenant_id
                ORDER BY e.employee_name
            """)
            
            results = session.execute(query, {'tenant_id': user.tenant_id}).fetchall()
            
            users = []
            for row in results:
                users.append({
                    'id': str(row.user_id),
                    'first_name': row.first_name or '',
                    'last_name': row.last_name or '',
                    'email': row.email,
                    'role': row.role_name or 'User',
                    'is_active': row.is_active,
                    'is_invited': row.is_invited,
                    'invitation_token': row.invitation_token
                })
            
            return jsonify({'users': users}), 200
            
        except Exception as e:
            current_app.logger.error(f"Get users error: {e}")
            return jsonify({'error': 'Failed to fetch users'}), 500
        finally:
            session.close()
    
    return _get_users()


@auth_bp.route('/invite-user', methods=['POST'])
def invite_user():
    """
    Create invitation for new user - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    import secrets
    
    @token_required
    def _invite():
        from flask import request
        user = request.current_user
        
        # Check permission
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        session = SessionLocal()
        try:
            data = request.get_json()
            first_name = data.get('first_name')
            last_name = data.get('last_name')
            email = data.get('email')
            role = data.get('role', 'Staff')
            
            if not all([first_name, last_name, email]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            # Check if email already exists
            check_query = text("""
                SELECT employee_id 
                FROM "StreemLyne_MT"."Employee_Master"
                WHERE email = :email AND tenant_id = :tenant_id
            """)
            existing = session.execute(check_query, {
                'email': email,
                'tenant_id': user.tenant_id
            }).fetchone()
            
            if existing:
                return jsonify({'error': 'Email already exists'}), 400
            
            # Generate invitation token
            invitation_token = secrets.token_urlsafe(32)
            
            # Get role_id for the role
            role_query = text("""
                SELECT role_id 
                FROM "StreemLyne_MT"."Role_Master"
                WHERE role_name = :role_name
            """)
            role_result = session.execute(role_query, {'role_name': role}).fetchone()
            role_id = role_result.role_id if role_result else 4  # Default to Staff
            
            # Create employee record
            employee_insert = text("""
                INSERT INTO "StreemLyne_MT"."Employee_Master" 
                (first_name, last_name, employee_name, email, tenant_id, role_ids, is_active)
                VALUES (:first_name, :last_name, :employee_name, :email, :tenant_id, :role_ids, true)
                RETURNING employee_id
            """)
            
            employee_result = session.execute(employee_insert, {
                'first_name': first_name,
                'last_name': last_name,
                'employee_name': f"{first_name} {last_name}",
                'email': email,
                'tenant_id': user.tenant_id,
                'role_ids': f'{{{role_id}}}'  # PostgreSQL array syntax
            }).fetchone()
            
            employee_id = employee_result.employee_id
            
            # Create user record with invitation token (no password yet)
            username = email.split('@')[0]  # Use email prefix as username
            
            user_insert = text("""
                INSERT INTO "StreemLyne_MT"."User_Master"
                (user_name, employee_id, tenant_id, is_active, invitation_token)
                VALUES (:user_name, :employee_id, :tenant_id, false, :invitation_token)
                RETURNING user_id
            """)
            
            user_result = session.execute(user_insert, {
                'user_name': username,
                'employee_id': employee_id,
                'tenant_id': user.tenant_id,
                'invitation_token': invitation_token
            }).fetchone()
            
            user_id = user_result.user_id
            
            # Create user-role mapping
            role_mapping_insert = text("""
                INSERT INTO "StreemLyne_MT"."User_Role_Mapping"
                (user_id, role_id)
                VALUES (:user_id, :role_id)
            """)
            
            session.execute(role_mapping_insert, {
                'user_id': user_id,
                'role_id': role_id
            })
            
            session.commit()
            
            return jsonify({
                'message': 'Invitation created successfully',
                'invitation_token': invitation_token,
                'user_id': user_id
            }), 201
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Invite user error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to create invitation', 'details': str(e)}), 500
        finally:
            session.close()
    
    return _invite()


@auth_bp.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """
    Update user details - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    
    @token_required
    def _update():
        from flask import request
        user = request.current_user
        
        # Check permission
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        session = SessionLocal()
        try:
            data = request.get_json()
            first_name = data.get('first_name')
            last_name = data.get('last_name')
            email = data.get('email')
            role = data.get('role')
            
            # Get employee_id for this user
            user_query = text("""
                SELECT employee_id 
                FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """)
            user_result = session.execute(user_query, {'user_id': user_id}).fetchone()
            
            if not user_result:
                return jsonify({'error': 'User not found'}), 404
            
            employee_id = user_result.employee_id
            
            # Update employee record
            update_employee = text("""
                UPDATE "StreemLyne_MT"."Employee_Master"
                SET first_name = :first_name,
                    last_name = :last_name,
                    employee_name = :employee_name,
                    email = :email
                WHERE employee_id = :employee_id
            """)
            
            session.execute(update_employee, {
                'first_name': first_name,
                'last_name': last_name,
                'employee_name': f"{first_name} {last_name}",
                'email': email,
                'employee_id': employee_id
            })
            
            # Update role if provided
            if role:
                # Get role_id
                role_query = text("""
                    SELECT role_id 
                    FROM "StreemLyne_MT"."Role_Master"
                    WHERE role_name = :role_name
                """)
                role_result = session.execute(role_query, {'role_name': role}).fetchone()
                
                if role_result:
                    # Delete existing role mappings
                    delete_roles = text("""
                        DELETE FROM "StreemLyne_MT"."User_Role_Mapping"
                        WHERE user_id = :user_id
                    """)
                    session.execute(delete_roles, {'user_id': user_id})
                    
                    # Insert new role mapping
                    insert_role = text("""
                        INSERT INTO "StreemLyne_MT"."User_Role_Mapping"
                        (user_id, role_id)
                        VALUES (:user_id, :role_id)
                    """)
                    session.execute(insert_role, {
                        'user_id': user_id,
                        'role_id': role_result.role_id
                    })
            
            session.commit()
            
            return jsonify({'message': 'User updated successfully'}), 200
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Update user error: {e}")
            return jsonify({'error': 'Failed to update user'}), 500
        finally:
            session.close()
    
    return _update()


@auth_bp.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """
    Delete user - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    
    @token_required
    def _delete():
        from flask import request
        user = request.current_user
        
        # Check permission
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        # Prevent self-deletion
        if user.id == user_id:
            return jsonify({'error': 'Cannot delete your own account'}), 400
        
        session = SessionLocal()
        try:
            # Delete role mappings first (foreign key constraint)
            delete_roles = text("""
                DELETE FROM "StreemLyne_MT"."User_Role_Mapping"
                WHERE user_id = :user_id
            """)
            session.execute(delete_roles, {'user_id': user_id})
            
            # Get employee_id before deleting user
            user_query = text("""
                SELECT employee_id 
                FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """)
            user_result = session.execute(user_query, {'user_id': user_id}).fetchone()
            
            if not user_result:
                return jsonify({'error': 'User not found'}), 404
            
            employee_id = user_result.employee_id
            
            # Delete user
            delete_user = text("""
                DELETE FROM "StreemLyne_MT"."User_Master"
                WHERE user_id = :user_id
            """)
            session.execute(delete_user, {'user_id': user_id})
            
            # Delete employee
            delete_employee = text("""
                DELETE FROM "StreemLyne_MT"."Employee_Master"
                WHERE employee_id = :employee_id
            """)
            session.execute(delete_employee, {'employee_id': employee_id})
            
            session.commit()
            
            return jsonify({'message': 'User deleted successfully'}), 200
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Delete user error: {e}")
            return jsonify({'error': 'Failed to delete user'}), 500
        finally:
            session.close()
    
    return _delete()


@auth_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
def toggle_user_status(user_id):
    """
    Toggle user active status - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    
    @token_required
    def _toggle():
        from flask import request
        user = request.current_user
        
        # Check permission
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        session = SessionLocal()
        try:
            data = request.get_json()
            is_active = data.get('is_active', False)
            
            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET is_active = :is_active
                WHERE user_id = :user_id
            """)
            
            session.execute(update_query, {
                'is_active': is_active,
                'user_id': user_id
            })
            session.commit()
            
            return jsonify({'message': 'User status updated successfully'}), 200
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Toggle user status error: {e}")
            return jsonify({'error': 'Failed to update user status'}), 500
        finally:
            session.close()
    
    return _toggle()


@auth_bp.route('/resend-invitation/<int:user_id>', methods=['POST'])
def resend_invitation(user_id):
    """
    Resend invitation link - requires Platform Admin or Salesperson role
    """
    from .auth_helpers import token_required
    import secrets
    
    @token_required
    def _resend():
        from flask import request
        user = request.current_user
        
        # Check permission
        if user.role_id not in [2, 3]:
            return jsonify({'error': 'Insufficient permissions'}), 403
        
        session = SessionLocal()
        try:
            # Generate new invitation token
            invitation_token = secrets.token_urlsafe(32)
            
            # Update user with new token
            update_query = text("""
                UPDATE "StreemLyne_MT"."User_Master"
                SET invitation_token = :invitation_token
                WHERE user_id = :user_id
            """)
            
            session.execute(update_query, {
                'invitation_token': invitation_token,
                'user_id': user_id
            })
            session.commit()
            
            return jsonify({
                'message': 'Invitation resent successfully',
                'invitation_token': invitation_token
            }), 200
            
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Resend invitation error: {e}")
            return jsonify({'error': 'Failed to resend invitation'}), 500
        finally:
            session.close()
    
    return _resend()