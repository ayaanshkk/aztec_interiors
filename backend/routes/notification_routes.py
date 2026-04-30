from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import text
from datetime import datetime

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

notification_bp = Blueprint('notification', __name__)


# ============================================================================
# HELPER FUNCTION: Create Activity Notification
# ============================================================================

def create_activity_notification(session, tenant_id, message, client_id=None, 
                                contract_id=None, property_id=None, employee_id=None,
                                notification_type='activity', priority='medium'):
    """
    Create notification for all users in tenant or specific employee
    
    Args:
        session: Active SQLAlchemy session
        tenant_id: Tenant ID (required)
        message: Notification message text
        client_id: Optional client ID reference
        contract_id: Optional contract ID reference
        property_id: Optional property ID reference
        employee_id: Optional - if provided, notification goes to this employee only
        notification_type: Type of notification
        priority: Priority level (low, medium, high)
    """
    try:
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Notification_Master"
            (tenant_id, employee_id, client_id, contract_id, property_id,
             notification_type, priority, message, read, dismissed)
            VALUES (:tenant_id, :employee_id, :client_id, :contract_id, :property_id,
                    :notification_type, :priority, :message, false, false)
        """)
        
        session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id,
            'client_id': client_id,
            'contract_id': contract_id,
            'property_id': property_id,
            'notification_type': notification_type,
            'priority': priority,
            'message': message
        })
        
        session.commit()
        current_app.logger.info(f"✅ Created notification for tenant {tenant_id}")
        
    except Exception as e:
        current_app.logger.error(f"❌ Failed to create notification: {e}")
        session.rollback()
        raise


# ============================================================================
# GET ALL NOTIFICATIONS (for current user)
# ============================================================================

@notification_bp.route('/notifications', methods=['GET'])
@token_required
@require_tenant
def get_notifications(tenant_id, employee_id):
    """Get notifications for current employee (not dismissed)"""
    session = SessionLocal()
    try:
        # Get notifications for this employee or tenant-wide notifications
        query = text("""
            SELECT 
                n.*,
                c.client_company_name
            FROM "StreemLyne_MT"."Notification_Master" n
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON n.client_id = c.client_id
            WHERE n.tenant_id = :tenant_id
                AND n.dismissed = false
                AND (n.employee_id = :employee_id OR n.employee_id IS NULL)
            ORDER BY n.created_at DESC
        """)
        
        notifications = session.execute(query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        }).fetchall()
        
        result = []
        for n in notifications:
            result.append({
                'notification_id': n.notification_id,
                'employee_id': n.employee_id,
                'client_id': n.client_id,
                'client_name': n.client_company_name if hasattr(n, 'client_company_name') else None,
                'contract_id': n.contract_id,
                'property_id': n.property_id,
                'notification_type': n.notification_type,
                'priority': n.priority,
                'message': n.message,
                'read': n.read,
                'dismissed': n.dismissed,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'read_at': n.read_at.isoformat() if n.read_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/all', methods=['GET'])
@token_required
@require_tenant
def get_all_notifications_including_dismissed(tenant_id, employee_id):
    """Get ALL notifications for current employee (including dismissed)"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                n.*,
                c.client_company_name
            FROM "StreemLyne_MT"."Notification_Master" n
            LEFT JOIN "StreemLyne_MT"."Client_Master" c ON n.client_id = c.client_id
            WHERE n.tenant_id = :tenant_id
                AND (n.employee_id = :employee_id OR n.employee_id IS NULL)
            ORDER BY n.created_at DESC
        """)
        
        notifications = session.execute(query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        }).fetchall()
        
        result = []
        for n in notifications:
            result.append({
                'notification_id': n.notification_id,
                'employee_id': n.employee_id,
                'client_id': n.client_id,
                'client_name': n.client_company_name if hasattr(n, 'client_company_name') else None,
                'contract_id': n.contract_id,
                'property_id': n.property_id,
                'notification_type': n.notification_type,
                'priority': n.priority,
                'message': n.message,
                'read': n.read,
                'dismissed': n.dismissed,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'read_at': n.read_at.isoformat() if n.read_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# MARK AS READ
# ============================================================================

@notification_bp.route('/notifications/<int:notification_id>/read', methods=['PATCH'])
@token_required
@require_tenant
def mark_as_read(notification_id, tenant_id, employee_id):
    """Mark a specific notification as read"""
    session = SessionLocal()
    try:
        # Verify notification exists and belongs to user
        check_query = text("""
            SELECT notification_id FROM "StreemLyne_MT"."Notification_Master"
            WHERE notification_id = :notification_id
                AND tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
        """)
        
        notification = session.execute(check_query, {
            'notification_id': notification_id,
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        }).fetchone()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # Mark as read
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET read = true,
                read_at = CURRENT_TIMESTAMP
            WHERE notification_id = :notification_id
        """)
        
        session.execute(update_query, {'notification_id': notification_id})
        session.commit()
        
        return jsonify({'message': 'Notification marked as read'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error marking notification as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/mark-all-read', methods=['PATCH'])
@token_required
@require_tenant
def mark_all_as_read(tenant_id, employee_id):
    """Mark all unread notifications as read for current employee"""
    session = SessionLocal()
    try:
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET read = true,
                read_at = CURRENT_TIMESTAMP
            WHERE tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
                AND read = false
        """)
        
        result = session.execute(update_query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        })
        
        session.commit()
        
        return jsonify({
            'message': 'All notifications marked as read',
            'count': result.rowcount
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error marking all as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# DISMISS NOTIFICATION
# ============================================================================

@notification_bp.route('/notifications/<int:notification_id>/dismiss', methods=['POST'])
@token_required
@require_tenant
def dismiss_notification(notification_id, tenant_id, employee_id):
    """Dismiss notification from sidebar (but keep in full notifications page)"""
    session = SessionLocal()
    try:
        # Verify notification exists
        check_query = text("""
            SELECT notification_id FROM "StreemLyne_MT"."Notification_Master"
            WHERE notification_id = :notification_id
                AND tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
        """)
        
        notification = session.execute(check_query, {
            'notification_id': notification_id,
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        }).fetchone()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # Mark as dismissed
        update_query = text("""
            UPDATE "StreemLyne_MT"."Notification_Master"
            SET dismissed = true
            WHERE notification_id = :notification_id
        """)
        
        session.execute(update_query, {'notification_id': notification_id})
        session.commit()
        
        return jsonify({'success': True, 'message': 'Notification dismissed'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error dismissing notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# DELETE NOTIFICATION
# ============================================================================

@notification_bp.route('/notifications/<int:notification_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_notification(notification_id, tenant_id, employee_id):
    """Permanently delete notification"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE notification_id = :notification_id
                AND tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
        """)
        
        result = session.execute(delete_query, {
            'notification_id': notification_id,
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        })
        
        if result.rowcount == 0:
            return jsonify({'error': 'Notification not found'}), 404
        
        session.commit()
        
        return jsonify({'message': 'Notification deleted'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/clear-all', methods=['DELETE'])
@token_required
@require_tenant
def clear_all_notifications(tenant_id, employee_id):
    """Delete all notifications permanently for current employee"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
        """)
        
        result = session.execute(delete_query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        })
        
        session.commit()
        
        return jsonify({
            'message': 'All notifications cleared',
            'count': result.rowcount
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error clearing all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/clear-dismissed', methods=['POST'])
@token_required
@require_tenant
def clear_dismissed_notifications(tenant_id, employee_id):
    """Clear all dismissed notifications for current employee"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
                AND dismissed = true
        """)
        
        result = session.execute(delete_query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        })
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Cleared {result.rowcount} dismissed notifications',
            'count': result.rowcount
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error clearing dismissed notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# NOTIFICATION STATS
# ============================================================================

@notification_bp.route('/notifications/stats', methods=['GET'])
@token_required
@require_tenant
def get_notification_stats(tenant_id, employee_id):
    """Get statistics about notifications for current employee"""
    session = SessionLocal()
    try:
        stats_query = text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN read = false THEN 1 ELSE 0 END) as unread,
                SUM(CASE WHEN read = true THEN 1 ELSE 0 END) as read,
                SUM(CASE WHEN dismissed = true THEN 1 ELSE 0 END) as dismissed
            FROM "StreemLyne_MT"."Notification_Master"
            WHERE tenant_id = :tenant_id
                AND (employee_id = :employee_id OR employee_id IS NULL)
        """)
        
        stats = session.execute(stats_query, {
            'tenant_id': str(tenant_id),
            'employee_id': employee_id
        }).fetchone()
        
        return jsonify({
            'total': stats.total or 0,
            'unread': stats.unread or 0,
            'read': stats.read or 0,
            'dismissed': stats.dismissed or 0
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching notification stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()