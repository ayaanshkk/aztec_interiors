from flask import Blueprint, jsonify, request, current_app
from ..models import ProductionNotification, User
from .auth_helpers import token_required 
from datetime import datetime
from ..db import SessionLocal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, case
import uuid

notification_bp = Blueprint('notification', __name__)

# ==========================================
# SIMPLE IN-MEMORY CACHE (Replace with Redis in production)
# ==========================================

_cache = {}
_cache_timeout = 60  # 1 minute (notifications need fresher cache)

def simple_cache_get(key):
    """Get cached data if not expired"""
    if key in _cache:
        cached_data, cached_time = _cache[key]
        if (datetime.utcnow() - cached_time).seconds < _cache_timeout:
            return cached_data
    return None

def simple_cache_set(key, data):
    """Store data in cache with current timestamp"""
    _cache[key] = (data, datetime.utcnow())

def invalidate_cache(*patterns):
    """Remove cache entries matching any of the patterns"""
    for pattern in patterns:
        keys_to_remove = [k for k in _cache.keys() if pattern in k]
        for k in keys_to_remove:
            _cache.pop(k, None)

def invalidate_user_notification_cache(user_id):
    """Invalidate all notification-related cache for a specific user"""
    invalidate_cache(f'notifications_{user_id}', f'notification_stats_{user_id}')

# ============================================================================
# HELPER FUNCTION: Create Activity Notification (OPTIMIZED)
# ============================================================================

def create_activity_notification(session, message, job_id=None, customer_id=None, 
                                moved_by=None, form_submission_id=None, form_type=None):
    """
    Create notifications for ALL eligible users (Manager, HR, Production)
    
    OPTIMIZATIONS:
    - Batch insert instead of individual adds
    - Cache invalidation for affected users
    - Single query to get eligible users
    
    Args:
        session: Active SQLAlchemy session
        message: Notification message text
        job_id: Optional job ID reference
        customer_id: Optional customer ID reference
        moved_by: Username or ID of person who performed the action
        form_submission_id: Optional form submission ID
        form_type: Optional form type (kitchen, bedroom, etc.)
    """
    try:
        # Get all users who should receive notifications
        eligible_roles = ['Manager', 'HR', 'Production']
        users = session.query(User).filter(
            User.role.in_(eligible_roles),
            User.is_active == True
        ).all()
        
        if not users:
            current_app.logger.warning("⚠️ No eligible users found for notifications")
            return
        
        # OPTIMIZED: Create notifications in batch
        notifications = []
        for user in users:
            notification = ProductionNotification(
                id=str(uuid.uuid4()),
                user_id=user.id,
                customer_id=customer_id,
                job_id=job_id,
                form_submission_id=form_submission_id,
                form_type=form_type,
                message=message,
                moved_by=moved_by,
                read=False,
                dismissed=False,
                created_at=datetime.utcnow()
            )
            notifications.append(notification)
        
        # OPTIMIZED: Bulk insert (much faster than individual adds)
        session.bulk_save_objects(notifications)
        session.commit()
        
        # INVALIDATE CACHE for all affected users
        for user in users:
            invalidate_user_notification_cache(user.id)
        
        current_app.logger.info(f"✅ Created {len(users)} notifications for eligible users")
        
    except Exception as e:
        current_app.logger.error(f"❌ Failed to create notifications: {e}")
        session.rollback()
        raise


# ============================================================================
# GET ALL NOTIFICATIONS (OPTIMIZED)
# ============================================================================

@notification_bp.route('/notifications/production', methods=['GET', 'OPTIONS'])
@token_required
def get_production_notifications():
    """
    Get notifications for the CURRENT USER ONLY (not dismissed)
    
    OPTIMIZATIONS:
    - 1-minute cache for notification lists
    - Pagination support
    - Efficient filtering
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    user_id = request.current_user.id
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)  # Max 200 per page
    
    # Check cache first
    cache_key = f"notifications_{user_id}_{page}_{per_page}"
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug(f"Cache hit for notifications: {cache_key}")
        return jsonify(cached), 200

    session = SessionLocal()
    try:
        # Filter by current user (not dismissed)
        query = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id,
            ProductionNotification.dismissed == False
        )
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        notifications = query.order_by(
            ProductionNotification.created_at.desc()
        ).limit(per_page).offset((page - 1) * per_page).all()

        result = {
            'notifications': [
                {
                    'id': n.id,
                    'job_id': n.job_id,
                    'customer_id': n.customer_id,
                    'form_submission_id': n.form_submission_id,
                    'form_type': n.form_type,
                    'message': n.message,
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'moved_by': n.moved_by,
                    'read': n.read,
                    'dismissed': n.dismissed
                } for n in notifications
            ],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': (total_count + per_page - 1) // per_page
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error fetching notifications: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notifications: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/all', methods=['GET', 'OPTIONS'])
@token_required
def get_all_notifications_including_dismissed():
    """
    Get ALL notifications for current user (including dismissed)
    
    OPTIMIZATIONS:
    - 1-minute cache
    - Pagination support
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    user_id = request.current_user.id
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)
    
    # Check cache first
    cache_key = f"notifications_all_{user_id}_{page}_{per_page}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200

    session = SessionLocal()
    try:
        # Get ALL notifications for current user
        query = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id
        )
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        notifications = query.order_by(
            ProductionNotification.created_at.desc()
        ).limit(per_page).offset((page - 1) * per_page).all()

        result = {
            'notifications': [
                {
                    'id': n.id,
                    'job_id': n.job_id,
                    'customer_id': n.customer_id,
                    'form_submission_id': n.form_submission_id,
                    'form_type': n.form_type,
                    'message': n.message,
                    'created_at': n.created_at.isoformat() if n.created_at else None,
                    'moved_by': n.moved_by,
                    'read': n.read,
                    'dismissed': n.dismissed
                } for n in notifications
            ],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': (total_count + per_page - 1) // per_page
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching all notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>/read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_as_read(notification_id):
    """
    Mark a specific notification as read
    
    OPTIMIZATIONS:
    - Cache invalidation for affected user
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() 
    try:
        notification = session.get(ProductionNotification, notification_id)
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404

        # Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        notification.read = True
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(notification.user_id)
        
        return jsonify({'message': 'Notification marked as read'}), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking notification as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking notification as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/mark-all-read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_all_as_read():
    """
    Mark all unread notifications as read for CURRENT USER ONLY
    
    OPTIMIZATIONS:
    - Batch update operation
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_id = request.current_user.id
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch update
        updated_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id,
            ProductionNotification.read == False
        ).update(
            {'read': True},
            synchronize_session='fetch'
        )
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
        return jsonify({
            'message': 'All notifications marked as read',
            'count': updated_count
        }), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error marking all as read: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking all as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>/dismiss', methods=['POST', 'OPTIONS'])
@token_required
def dismiss_notification(notification_id):
    """
    Dismiss notification from sidebar
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        notification = session.get(ProductionNotification, notification_id)
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        notification.dismissed = True
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(notification.user_id)
        
        return jsonify({'success': True, 'message': 'Notification dismissed'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error dismissing notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/<string:notification_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_notification(notification_id):
    """
    Permanently delete notification
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        notification = session.get(ProductionNotification, notification_id)
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # Check ownership
        if notification.user_id != request.current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        user_id = notification.user_id
        
        session.delete(notification)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
        return jsonify({'message': 'Notification deleted'}), 200
            
    except SQLAlchemyError as e:
        session.rollback()
        current_app.logger.exception(f"Database error deleting notification: {e}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting notification: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/clear-all', methods=['DELETE', 'OPTIONS'])
@token_required
def clear_all_notifications():
    """
    Delete all notifications permanently for CURRENT USER ONLY
    
    OPTIMIZATIONS:
    - Batch deletion
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_id = request.current_user.id
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch delete
        deleted_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id
        ).delete(synchronize_session='fetch')
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
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


@notification_bp.route('/notifications/production/clear-dismissed', methods=['POST', 'OPTIONS'])
@token_required
def clear_dismissed_notifications():
    """
    Clear all dismissed notifications for current user
    
    OPTIMIZATIONS:
    - Batch deletion
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_id = request.current_user.id
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch delete
        deleted_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id,
            ProductionNotification.dismissed == True
        ).delete(synchronize_session='fetch')
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} dismissed notifications',
            'count': deleted_count
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error clearing dismissed notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_notification_stats():
    """
    Get statistics about notifications for CURRENT USER ONLY
    
    OPTIMIZATIONS:
    - 1-minute cache for stats
    - Single aggregation query instead of 4 separate queries
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    user_id = request.current_user.id
    
    # Check cache first
    cache_key = f"notification_stats_{user_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200

    session = SessionLocal()
    try:
        # OPTIMIZED: Single aggregation query instead of 4 separate queries
        stats = session.query(
            func.count(ProductionNotification.id).label('total'),
            func.sum(case((ProductionNotification.read == False, 1), else_=0)).label('unread'),
            func.sum(case((ProductionNotification.read == True, 1), else_=0)).label('read'),
            func.sum(case((ProductionNotification.dismissed == True, 1), else_=0)).label('dismissed')
        ).filter(
            ProductionNotification.user_id == user_id
        ).first()
        
        result = {
            'total': stats.total or 0,
            'unread': stats.unread or 0,
            'read': stats.read or 0,
            'dismissed': stats.dismissed or 0
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
            
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error fetching notification stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# BATCH OPERATIONS (NEW)
# ============================================================================

@notification_bp.route('/notifications/production/mark-multiple-read', methods=['PATCH', 'OPTIONS'])
@token_required
def mark_multiple_as_read():
    """
    Mark multiple notifications as read in one request
    
    OPTIMIZATIONS:
    - Batch update operation
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_id = request.current_user.id
    data = request.get_json()
    notification_ids = data.get('notification_ids', [])
    
    if not notification_ids:
        return jsonify({'error': 'No notification IDs provided'}), 400
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch update
        updated_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id,
            ProductionNotification.id.in_(notification_ids)
        ).update(
            {'read': True},
            synchronize_session='fetch'
        )
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
        return jsonify({
            'message': f'{updated_count} notifications marked as read',
            'count': updated_count
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error marking multiple as read: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@notification_bp.route('/notifications/production/delete-multiple', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_multiple_notifications():
    """
    Delete multiple notifications in one request
    
    OPTIMIZATIONS:
    - Batch deletion
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_id = request.current_user.id
    data = request.get_json()
    notification_ids = data.get('notification_ids', [])
    
    if not notification_ids:
        return jsonify({'error': 'No notification IDs provided'}), 400
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch delete
        deleted_count = session.query(ProductionNotification).filter(
            ProductionNotification.user_id == user_id,
            ProductionNotification.id.in_(notification_ids)
        ).delete(synchronize_session='fetch')
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_user_notification_cache(user_id)
        
        return jsonify({
            'message': f'{deleted_count} notifications deleted',
            'count': deleted_count
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting multiple notifications: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()