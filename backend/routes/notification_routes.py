from flask import Blueprint, jsonify, request, current_app
from ..models import ProductionNotification
from .auth_helpers import token_required 
from datetime import datetime
from ..db import SessionLocal
from sqlalchemy.exc import SQLAlchemyError

notification_bp = Blueprint('notification', __name__)

@notification_bp.route('/notifications/production', methods=['GET', 'OPTIONS'])
@token_required
def get_production_notifications():
    """
    Get all production notifications for the current user.
    Returns notifications sorted by creation date (newest first).
    Now accessible to all user roles: Manager, HR, Sales, Production
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # Get all notifications (both read and unread) sorted by newest first
        notifications = session.query(ProductionNotification).order_by(
            ProductionNotification.created_at.desc()
        ).all()

        return jsonify([
            {
                'id': n.id,
                'job_id': n.job_id,
                'customer_id': n.customer_id,
                'message': n.message,
                'created_at': n.created_at.isoformat() if n.created_at else None,
                'moved_by': n.moved_by,
                'read': getattr(n, 'read', False)  # Safe access to 'read' field
            } for n in notifications
        ])
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error fetching production notifications: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Unexpected error fetching production notifications: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>/read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_as_read(notification_id):
    """
    Mark a specific notification as read (but don't delete it).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() 
    try:
        # Fetch the notification within the current transaction session
        notification = session.get(ProductionNotification, notification_id)
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404

        # Check if 'read' field exists before setting it
        if hasattr(notification, 'read'):
            notification.read = True
            session.commit()
            return jsonify({'message': 'Notification marked as read'}), 200
        else:
            current_app.logger.warning(f"ProductionNotification model missing 'read' field for notification {notification_id}")
            return jsonify({'error': 'Read status not supported'}), 501
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking notification {notification_id} as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking notification {notification_id} as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/mark-all-read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_all_as_read():
    """
    Mark all unread production notifications as read (but don't delete them).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Check if the model has a 'read' field before updating
        sample_notification = session.query(ProductionNotification).first()
        if sample_notification and hasattr(sample_notification, 'read'):
            # Update all unread notifications in one query
            updated_count = session.query(ProductionNotification).filter_by(read=False).update(
                {'read': True},
                synchronize_session='fetch'
            )
            session.commit()
            
            return jsonify({
                'message': 'All notifications marked as read',
                'count': updated_count
            }), 200
        else:
            current_app.logger.warning("ProductionNotification model missing 'read' field")
            return jsonify({'error': 'Read status not supported'}), 501
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking all notifications as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking all notifications as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/clear-all', methods=['DELETE', 'OPTIONS'])
@token_required
def clear_all_notifications():
    """
    Delete all production notifications permanently.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Delete all notifications
        deleted_count = session.query(ProductionNotification).delete(synchronize_session='fetch')
        session.commit()
        
        return jsonify({
            'message': 'All notifications cleared',
            'count': deleted_count
        }), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error clearing all notifications: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error clearing all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_notification(notification_id):
    """
    Delete a specific notification permanently.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        notification = session.get(ProductionNotification, notification_id)
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        session.delete(notification)
        session.commit()
        
        return jsonify({'message': 'Notification deleted'}), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error deleting notification {notification_id}: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting notification {notification_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/history', methods=['GET', 'OPTIONS'])
@token_required
def get_notification_history():
    """
    Get all production notifications (both read and unread).
    Useful for viewing notification history.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # Get query parameters for pagination
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Ensure reasonable limits
        limit = min(limit, 100)  # Max 100 notifications per request
        
        notifications = session.query(ProductionNotification).order_by(
            ProductionNotification.created_at.desc()
        ).limit(limit).offset(offset).all()
        
        total_count = session.query(ProductionNotification).count()

        return jsonify({
            'notifications': [
                {
                    'id': n.id,
                    'job_id': n.job_id,
                    'customer_id': n.customer_id,
                    'message': n.message,
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'moved_by': n.moved_by,
                    'read': getattr(n, 'read', False)
                } for n in notifications
            ],
            'total': total_count,
            'limit': limit,
            'offset': offset
        })
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error fetching notification history: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notification history: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_notification_stats():
    """
    Get statistics about production notifications.
    Returns counts of read/unread notifications.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        total_count = session.query(ProductionNotification).count()
        
        # Try to get unread count if 'read' field exists
        try:
            unread_count = session.query(ProductionNotification).filter_by(read=False).count()
            read_count = total_count - unread_count
            
            return jsonify({
                'total': total_count,
                'unread': unread_count,
                'read': read_count
            })
        except AttributeError:
            # If 'read' field doesn't exist, just return total
            return jsonify({
                'total': total_count,
                'unread': None,
                'read': None,
                'note': 'Read status not supported'
            })
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error fetching notification stats: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notification stats: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        session.close()