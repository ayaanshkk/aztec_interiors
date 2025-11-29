from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
import uuid
from ..models import ActionItem, Customer
from ..db import SessionLocal
from .auth_helpers import token_required
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_

action_items_bp = Blueprint('action_items', __name__)

# ==========================================
# SIMPLE IN-MEMORY CACHE (Replace with Redis in production)
# ==========================================

_cache = {}
_cache_timeout = 120  # 2 minutes (action items change less frequently)

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

# ==========================================
# ACTION ITEMS ROUTES (OPTIMIZED)
# ==========================================

@action_items_bp.route('/action-items', methods=['GET'])
@token_required
def get_action_items():
    """
    Get all pending action items
    
    OPTIMIZATIONS:
    - 2-minute cache for action items
    - Eager loading of customer relationship
    - Pagination support
    - Filtering by stage, priority, customer
    """
    # Get filter parameters
    stage = request.args.get('stage')
    priority = request.args.get('priority')
    customer_id = request.args.get('customer_id')
    completed = request.args.get('completed', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    per_page = min(per_page, 500)
    
    # Build cache key from filters
    cache_key = f"action_items_{stage}_{priority}_{customer_id}_{completed}_{page}_{per_page}"
    
    # Check cache first
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug(f"Cache hit for action items: {cache_key}")
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single query with eager loading
        query = session.query(ActionItem).options(
            joinedload(ActionItem.customer)
        )
        
        # Apply filters
        query = query.filter(ActionItem.completed == completed)
        
        if stage:
            query = query.filter(ActionItem.stage == stage)
        if priority:
            query = query.filter(ActionItem.priority == priority)
        if customer_id:
            query = query.filter(ActionItem.customer_id == customer_id)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        action_items = query.order_by(ActionItem.created_at.desc())\
                           .limit(per_page)\
                           .offset((page - 1) * per_page)\
                           .all()
        
        result = {
            'action_items': [{
                'id': item.id,
                'customer_name': item.customer.name if item.customer else 'Unknown',
                'customer_id': item.customer_id,
                'stage': item.stage,
                'priority': item.priority,
                'created_at': item.created_at.isoformat(),
                'completed': item.completed,
                'completed_at': item.completed_at.isoformat() if item.completed_at else None
            } for item in action_items],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': (total_count + per_page - 1) // per_page
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching action items: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/<string:action_id>', methods=['GET'])
@token_required
def get_action_item(action_id):
    """
    Get a single action item by ID
    
    OPTIMIZATIONS:
    - 2-minute cache
    - Eager loading of customer
    """
    # Check cache first
    cache_key = f"action_item_{action_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load customer
        action_item = session.query(ActionItem)\
            .options(joinedload(ActionItem.customer))\
            .filter(ActionItem.id == action_id)\
            .first()
        
        if not action_item:
            return jsonify({'error': 'Action item not found'}), 404
        
        result = {
            'id': action_item.id,
            'customer_name': action_item.customer.name if action_item.customer else 'Unknown',
            'customer_id': action_item.customer_id,
            'stage': action_item.stage,
            'priority': action_item.priority,
            'created_at': action_item.created_at.isoformat(),
            'completed': action_item.completed,
            'completed_at': action_item.completed_at.isoformat() if action_item.completed_at else None
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching action item {action_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/<string:action_id>/complete', methods=['PATCH'])
@token_required
def complete_action_item(action_id):
    """
    Mark an action item as completed
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        action_item = session.query(ActionItem).filter(ActionItem.id == action_id).first()
        if not action_item:
            return jsonify({'error': 'Action item not found'}), 404
        
        action_item.completed = True
        action_item.completed_at = datetime.utcnow()
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('action_items', f'action_item_{action_id}', 'action_items_stats')
        
        return jsonify({'message': 'Action item marked as completed'})
        
    except Exception as e:
        current_app.logger.exception(f"Error completing action item: {e}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items', methods=['POST'])
def create_action_item():
    """
    Create a new action item
    
    OPTIMIZATIONS:
    - Check for duplicates in single query
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'customer_id is required'}), 400
        
        # Check if action item already exists for this customer
        existing = session.query(ActionItem).filter(
            ActionItem.customer_id == data['customer_id'],
            ActionItem.stage == data.get('stage', 'Accepted'),
            ActionItem.completed == False
        ).first()
        
        if existing:
            return jsonify({'message': 'Action item already exists', 'action_item': {
                'id': existing.id,
                'customer_id': existing.customer_id,
                'stage': existing.stage
            }}), 200
        
        action_item = ActionItem(
            id=str(uuid.uuid4()),
            customer_id=data['customer_id'],
            stage=data.get('stage', 'Accepted'),
            priority=data.get('priority', 'High'),
            completed=False
        )
        
        session.add(action_item)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('action_items', 'action_items_stats')
        
        return jsonify({
            'message': 'Action item created successfully',
            'action_item': {
                'id': action_item.id,
                'customer_id': action_item.customer_id,
                'stage': action_item.stage,
                'priority': action_item.priority
            }
        }), 201
        
    except Exception as e:
        current_app.logger.exception(f"Error creating action item: {e}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/<string:action_id>', methods=['DELETE'])
@token_required
def delete_action_item(action_id):
    """
    Delete an action item
    
    OPTIMIZATIONS:
    - Cache invalidation
    """
    session = SessionLocal()
    try:
        action_item = session.query(ActionItem).filter(ActionItem.id == action_id).first()
        if not action_item:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.delete(action_item)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('action_items', f'action_item_{action_id}', 'action_items_stats')
        
        return jsonify({'message': 'Action item deleted successfully'})
        
    except Exception as e:
        current_app.logger.exception(f"Error deleting action item {action_id}: {e}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# BATCH OPERATIONS (NEW)
# ==========================================

@action_items_bp.route('/action-items/complete-multiple', methods=['PATCH'])
@token_required
def complete_multiple_action_items():
    """
    Mark multiple action items as completed
    
    OPTIMIZATIONS:
    - Batch update operation
    - Cache invalidation
    """
    data = request.get_json()
    action_item_ids = data.get('action_item_ids', [])
    
    if not action_item_ids:
        return jsonify({'error': 'No action item IDs provided'}), 400
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch update
        updated_count = session.query(ActionItem).filter(
            ActionItem.id.in_(action_item_ids)
        ).update(
            {
                'completed': True,
                'completed_at': datetime.utcnow()
            },
            synchronize_session='fetch'
        )
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('action_items', 'action_items_stats')
        
        return jsonify({
            'message': f'{updated_count} action items marked as completed',
            'count': updated_count
        })
        
    except Exception as e:
        current_app.logger.exception(f"Error completing multiple action items: {e}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@action_items_bp.route('/action-items/delete-multiple', methods=['DELETE'])
@token_required
def delete_multiple_action_items():
    """
    Delete multiple action items
    
    OPTIMIZATIONS:
    - Batch deletion
    - Cache invalidation
    """
    data = request.get_json()
    action_item_ids = data.get('action_item_ids', [])
    
    if not action_item_ids:
        return jsonify({'error': 'No action item IDs provided'}), 400
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch delete
        deleted_count = session.query(ActionItem).filter(
            ActionItem.id.in_(action_item_ids)
        ).delete(synchronize_session='fetch')
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('action_items', 'action_items_stats')
        
        return jsonify({
            'message': f'{deleted_count} action items deleted',
            'count': deleted_count
        })
        
    except Exception as e:
        current_app.logger.exception(f"Error deleting multiple action items: {e}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# STATISTICS (NEW)
# ==========================================

@action_items_bp.route('/action-items/stats', methods=['GET'])
@token_required
def get_action_items_stats():
    """
    Get statistics about action items
    
    OPTIMIZATIONS:
    - 2-minute cache for stats
    - Single aggregation query
    """
    # Check cache first
    cache_key = "action_items_stats"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single aggregation query for all stats
        stats = session.query(
            func.count(ActionItem.id).label('total'),
            func.sum(func.case((ActionItem.completed == False, 1), else_=0)).label('pending'),
            func.sum(func.case((ActionItem.completed == True, 1), else_=0)).label('completed')
        ).first()
        
        # Get counts by priority (for pending items only)
        priority_counts = session.query(
            ActionItem.priority,
            func.count(ActionItem.id)
        ).filter(
            ActionItem.completed == False
        ).group_by(ActionItem.priority).all()
        
        priority_breakdown = {priority: count for priority, count in priority_counts}
        
        # Get counts by stage (for pending items only)
        stage_counts = session.query(
            ActionItem.stage,
            func.count(ActionItem.id)
        ).filter(
            ActionItem.completed == False
        ).group_by(ActionItem.stage).all()
        
        stage_breakdown = {stage: count for stage, count in stage_counts}
        
        result = {
            'total': stats.total or 0,
            'pending': stats.pending or 0,
            'completed': stats.completed or 0,
            'by_priority': priority_breakdown,
            'by_stage': stage_breakdown
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching action items stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# CUSTOMER-SPECIFIC ACTIONS
# ==========================================

@action_items_bp.route('/action-items/customer/<string:customer_id>', methods=['GET'])
@token_required
def get_customer_action_items(customer_id):
    """
    Get all action items for a specific customer
    
    OPTIMIZATIONS:
    - 2-minute cache
    - Eager loading of customer
    """
    # Check cache first
    cache_key = f"customer_action_items_{customer_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # Check if customer exists
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all action items for this customer
        action_items = session.query(ActionItem)\
            .filter(ActionItem.customer_id == customer_id)\
            .order_by(ActionItem.created_at.desc())\
            .all()
        
        result = {
            'customer_id': customer_id,
            'customer_name': customer.name,
            'action_items': [{
                'id': item.id,
                'stage': item.stage,
                'priority': item.priority,
                'created_at': item.created_at.isoformat(),
                'completed': item.completed,
                'completed_at': item.completed_at.isoformat() if item.completed_at else None
            } for item in action_items],
            'summary': {
                'total': len(action_items),
                'pending': sum(1 for item in action_items if not item.completed),
                'completed': sum(1 for item in action_items if item.completed)
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching action items for customer {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()