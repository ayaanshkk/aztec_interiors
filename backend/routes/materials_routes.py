from flask import Blueprint, request, jsonify, current_app
from ..models import (MaterialOrder, MaterialChangeLog, MaterialStatus, Customer, User)
from .auth_helpers import token_required
from ..db import SessionLocal
from datetime import datetime, timedelta
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload
import uuid

materials_bp = Blueprint('materials', __name__)

# ==========================================
# SIMPLE IN-MEMORY CACHE (Replace with Redis in production)
# ==========================================

_cache = {}
_cache_timeout = 300  # 5 minutes

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
# MATERIALS CRUD OPERATIONS (OPTIMIZED)
# ==========================================

@materials_bp.route('/materials', methods=['GET', 'OPTIONS'])
@token_required
def get_all_materials():
    """
    Get all material orders with optional filtering
    
    OPTIMIZATIONS:
    - 5-minute cache for material lists
    - Eager loading of customer relationship
    - Pagination support
    - Single query with joins instead of N+1 queries
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager, HR, and Production can view materials'}), 403
    
    # Get filter parameters
    customer_id = request.args.get('customer_id')
    status = request.args.get('status')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    per_page = min(per_page, 500)
    
    # Build cache key from filters
    cache_key = f"materials_{customer_id}_{status}_{date_from}_{date_to}_{page}_{per_page}"
    
    # Check cache first
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug(f"Cache hit for materials: {cache_key}")
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single query with eager loading
        query = session.query(MaterialOrder).options(
            joinedload(MaterialOrder.customer)
        )
        
        # Apply filters
        if customer_id:
            query = query.filter(MaterialOrder.customer_id == customer_id)
        
        if status:
            try:
                status_enum = MaterialStatus(status)
                query = query.filter(MaterialOrder.status == status_enum)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status}'}), 400
        
        if date_from:
            query = query.filter(MaterialOrder.order_date >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(MaterialOrder.order_date <= datetime.fromisoformat(date_to))
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        materials = query.order_by(MaterialOrder.created_at.desc())\
                        .limit(per_page)\
                        .offset((page - 1) * per_page)\
                        .all()
        
        result = {
            'materials': [material.to_dict() for material in materials],
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
        current_app.logger.exception(f"Error fetching materials: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials/<material_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_material(material_id):
    """
    Get single material order by ID
    
    OPTIMIZATIONS:
    - 5-minute cache for individual materials
    - Eager loading of customer and change logs
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager, HR, and Production can view material details'}), 403
    
    # Check cache first
    cache_key = f"material_{material_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load customer and change logs
        material = session.query(MaterialOrder)\
            .options(
                joinedload(MaterialOrder.customer),
                joinedload(MaterialOrder.change_logs)
            )\
            .filter(MaterialOrder.id == material_id)\
            .first()
            
        if not material:
            return jsonify({'error': 'Material order not found'}), 404
        
        # Include change log
        change_logs = [log.to_dict() for log in material.change_logs]
        
        result = material.to_dict()
        result['change_logs'] = change_logs
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching material {material_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials/customer/<customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_materials(customer_id):
    """
    Get all material orders for a specific customer
    
    OPTIMIZATIONS:
    - 5-minute cache for customer materials
    - Single aggregation query for summary stats
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager, HR, and Production can view customer materials'}), 403
    
    # Check cache first
    cache_key = f"customer_materials_{customer_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all materials for this customer
        materials = session.query(MaterialOrder)\
            .filter(MaterialOrder.customer_id == customer_id)\
            .order_by(MaterialOrder.created_at.desc())\
            .all()
        
        # Check if ANY materials have been ordered
        any_ordered = any(m.status != MaterialStatus.NOT_ORDERED for m in materials)
        all_delivered = all(m.status == MaterialStatus.DELIVERED for m in materials) if materials else False
        
        # OPTIMIZED: Count pending deliveries in single pass
        pending_deliveries = sum(
            1 for m in materials 
            if m.status in [MaterialStatus.ORDERED, MaterialStatus.IN_TRANSIT]
        )
        
        result = {
            'customer_id': customer_id,
            'customer_name': customer.name,
            'materials': [m.to_dict() for m in materials],
            'summary': {
                'total_orders': len(materials),
                'modifications_safe': not any_ordered,
                'all_delivered': all_delivered,
                'pending_deliveries': pending_deliveries
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching materials for customer {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials', methods=['POST'])
@token_required
def create_material_order():
    """
    Create a new material order
    
    OPTIMIZATIONS:
    - Cache invalidation for material lists
    - Batch change log creation
    """
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    current_user_id = request.current_user.id
    
    if user_role not in ['manager', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager and Production can create material orders'}), 403
    
    session = SessionLocal()
    try:
        data = request.json
        
        current_app.logger.info(f"📥 Material order creation request: {data}")
        current_app.logger.info(f"👤 User: {current_user_id}, Role: {user_role}")
        
        # Validate required fields
        if not data.get('customer_id'):
            return jsonify({'error': 'customer_id is required'}), 400
        if not data.get('material_description'):
            return jsonify({'error': 'material_description is required'}), 400
        
        # Check if customer exists
        customer = session.get(Customer, data['customer_id'])
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Parse status
        status_value = data.get('status', 'ordered').lower()
        try:
            status = MaterialStatus(status_value)
        except ValueError:
            status = MaterialStatus.ORDERED
        
        current_app.logger.info(f"📊 Status enum created: {status}, value: {status.value}")
        
        # Handle date parsing
        order_date = None
        if data.get('order_date'):
            try:
                order_date = datetime.fromisoformat(data['order_date'].replace('Z', '+00:00'))
            except:
                order_date = datetime.utcnow()
        else:
            order_date = datetime.utcnow() if status != MaterialStatus.NOT_ORDERED else None
        
        expected_delivery_date = None
        if data.get('expected_delivery_date'):
            try:
                expected_delivery_date = datetime.fromisoformat(data['expected_delivery_date'].replace('Z', '+00:00'))
            except:
                expected_delivery_date = None
        
        # Create material order
        material_order = MaterialOrder(
            id=str(uuid.uuid4()),
            customer_id=data['customer_id'],
            job_id=data.get('job_id'),
            project_id=data.get('project_id'),
            ordered_by_user_id=current_user_id if status != MaterialStatus.NOT_ORDERED else None,
            material_description=data['material_description'],
            supplier_name=data.get('supplier_name'),
            supplier_reference=data.get('supplier_reference'),
            status=status.value,
            order_date=order_date,
            expected_delivery_date=expected_delivery_date,
            estimated_cost=data.get('estimated_cost'),
            notes=data.get('notes')
        )
        
        session.add(material_order)
        
        # Create change log
        change_log = MaterialChangeLog(
            id=str(uuid.uuid4()),
            material_order_id=material_order.id,
            changed_by_user_id=current_user_id,
            change_type='created',
            new_value=status.value,
            change_description=f"Material order created"
        )
        session.add(change_log)
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('materials', f'customer_materials_{data["customer_id"]}', 'materials_dashboard', 'pending_orders')
        
        current_app.logger.info(f"✅ Material order {material_order.id} created for customer {data['customer_id']}")
        
        return jsonify({
            'message': 'Material order created successfully',
            'material_order': material_order.to_dict()
        }), 201
        
    except ValueError as e:
        session.rollback()
        current_app.logger.exception(f"❌ ValueError creating material order: {e}")
        return jsonify({'error': f'Invalid status value: {str(e)}'}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating material order: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials/<string:material_id>', methods=['PATCH', 'OPTIONS'])
@token_required
def update_material_order(material_id):
    """
    Update a material order
    
    OPTIMIZATIONS:
    - Cache invalidation for updated material
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        material_order = session.get(MaterialOrder, material_id)
        if not material_order:
            return jsonify({'error': 'Material order not found'}), 404
        
        data = request.get_json()
        old_status = material_order.status
        
        new_status = data.get('status')
        
        # Update fields
        if 'material_description' in data:
            material_order.material_description = data['material_description']
        if 'supplier_name' in data:
            material_order.supplier_name = data['supplier_name']
        if 'supplier_reference' in data:
            material_order.supplier_reference = data['supplier_reference']
        if 'status' in data:
            material_order.status = data['status']
            new_status = data['status']
        if 'order_date' in data:
            material_order.order_date = datetime.fromisoformat(data['order_date']) if data['order_date'] else None
        if 'expected_delivery_date' in data:
            material_order.expected_delivery_date = datetime.fromisoformat(data['expected_delivery_date']) if data['expected_delivery_date'] else None
        if 'actual_delivery_date' in data:
            material_order.actual_delivery_date = datetime.fromisoformat(data['actual_delivery_date']) if data['actual_delivery_date'] else None
        if 'estimated_cost' in data:
            material_order.estimated_cost = data['estimated_cost']
        if 'actual_cost' in data:
            material_order.actual_cost = data['actual_cost']
        if 'notes' in data:
            material_order.notes = data['notes']
        
        if new_status == MaterialStatus.ORDERED and not material_order.order_date:
            material_order.order_date = datetime.utcnow()
        
        if new_status == MaterialStatus.DELIVERED and not material_order.actual_delivery_date:
            material_order.actual_delivery_date = datetime.utcnow()
        
        material_order.updated_at = datetime.utcnow()
        
        # Create notification if status changed
        if old_status != new_status:
            from backend.routes.notification_routes import create_activity_notification
            
            user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.email
            
            status_emoji = {
                'not_ordered': '📝',
                'ordered': '✅',
                'in_transit': '🚚',
                'delivered': '📦',
                'delayed': '⚠️'
            }
            
            old_status_value = old_status if isinstance(old_status, str) else old_status.value if old_status else 'not_ordered'
            new_status_value = new_status if isinstance(new_status, str) else new_status.value if new_status else 'not_ordered'
            
            emoji = status_emoji.get(new_status_value, '🔄')
            
            create_activity_notification(
                session=session,
                message=f"{emoji} Material order for {material_order.customer.name} updated: {old_status_value} → {new_status_value} | Material: {material_order.material_description}",
                customer_id=material_order.customer_id,
                moved_by=user_name
            )
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('materials', f'material_{material_id}', f'customer_materials_{material_order.customer_id}', 'materials_dashboard', 'pending_orders')
        
        return jsonify({
            'success': True,
            'material': material_order.to_dict()
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating material order {material_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials/<material_id>', methods=['DELETE'])
@token_required
def delete_material_order(material_id):
    """
    Delete a material order
    
    OPTIMIZATIONS:
    - Batch deletion of change logs
    - Cache invalidation
    """
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager, HR, and Production can delete material orders'}), 403
    
    session = SessionLocal()
    try:
        material_order = session.get(MaterialOrder, material_id)
        if not material_order:
            return jsonify({'error': 'Material order not found'}), 404
        
        customer_id = material_order.customer_id
        
        # OPTIMIZED: Batch delete change logs
        session.query(MaterialChangeLog).filter(
            MaterialChangeLog.material_order_id == material_id
        ).delete(synchronize_session='fetch')
        
        session.delete(material_order)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('materials', f'material_{material_id}', f'customer_materials_{customer_id}', 'materials_dashboard', 'pending_orders')
        
        current_app.logger.info(f"Material order {material_id} deleted")
        
        return jsonify({'message': 'Material order deleted successfully'}), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting material order {material_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# MANAGER DASHBOARD ENDPOINTS (OPTIMIZED)
# ==========================================

@materials_bp.route('/materials/dashboard/overview', methods=['GET'])
@token_required
def materials_dashboard_overview():
    """
    Get overview of all materials for manager dashboard
    
    OPTIMIZATIONS:
    - 5-minute cache for dashboard
    - Single aggregation query instead of 5 separate queries
    - Batch loading of upcoming deliveries
    """
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr']:
        return jsonify({'error': 'Unauthorized - Only Manager and HR can view dashboard overview'}), 403
    
    # Check cache first
    cache_key = "materials_dashboard"
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug("Cache hit for materials dashboard")
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single aggregation query for status counts
        status_counts_raw = session.query(
            MaterialOrder.status,
            func.count(MaterialOrder.id)
        ).group_by(MaterialOrder.status).all()
        
        # Convert to dict with defaults
        status_counts = {
            'not_ordered': 0,
            'ordered': 0,
            'in_transit': 0,
            'delivered': 0,
            'delayed': 0
        }
        
        total = 0
        for status, count in status_counts_raw:
            status_value = status if isinstance(status, str) else status.value
            status_counts[status_value] = count
            total += count
        
        status_counts['total'] = total
        
        # Get deliveries expected this week/month
        today = datetime.utcnow()
        week_end = today + timedelta(days=7)
        month_end = today + timedelta(days=30)
        
        # OPTIMIZED: Single query with eager loading
        deliveries_this_week = session.query(MaterialOrder)\
            .options(joinedload(MaterialOrder.customer))\
            .filter(
                and_(
                    MaterialOrder.expected_delivery_date >= today,
                    MaterialOrder.expected_delivery_date <= week_end,
                    MaterialOrder.status.in_([MaterialStatus.ORDERED, MaterialStatus.IN_TRANSIT])
                )
            ).all()
        
        deliveries_this_month_count = session.query(func.count(MaterialOrder.id))\
            .filter(
                and_(
                    MaterialOrder.expected_delivery_date >= today,
                    MaterialOrder.expected_delivery_date <= month_end,
                    MaterialOrder.status.in_([MaterialStatus.ORDERED, MaterialStatus.IN_TRANSIT])
                )
            ).scalar()
        
        result = {
            'status_counts': status_counts,
            'deliveries': {
                'expected_this_week': len(deliveries_this_week),
                'expected_this_month': deliveries_this_month_count,
                'upcoming_deliveries': [m.to_dict() for m in deliveries_this_week]
            },
            'alerts': {
                'delayed_orders': status_counts['delayed'],
                'needs_ordering': status_counts['not_ordered']
            }
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching materials dashboard: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@materials_bp.route('/materials/timeline/<customer_id>', methods=['GET'])
@token_required
def get_customer_project_timeline(customer_id):
    """
    Get project timeline for a specific customer
    
    OPTIMIZATIONS:
    - 5-minute cache for customer timelines
    - Single query for materials
    """
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'hr', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager, HR, and Production can view customer timelines'}), 403
    
    # Check cache first
    cache_key = f"customer_timeline_{customer_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all materials for this customer
        materials = session.query(MaterialOrder)\
            .filter(MaterialOrder.customer_id == customer_id)\
            .all()
        
        if not materials:
            result = {
                'customer_id': customer_id,
                'customer_name': customer.name,
                'timeline': {
                    'materials_ordered': False,
                    'can_modify_project': True,
                    'estimated_start_date': None,
                    'estimated_completion_date': None,
                    'message': 'No materials ordered yet - Project can be fully modified'
                }
            }
            
            # Cache the result
            simple_cache_set(cache_key, result)
            
            return jsonify(result), 200
        
        # Calculate timeline
        any_ordered = any(m.status != MaterialStatus.NOT_ORDERED for m in materials)
        all_delivered = all(m.status == MaterialStatus.DELIVERED for m in materials)
        
        # Find latest expected delivery
        pending_deliveries = [
            m for m in materials 
            if m.expected_delivery_date and m.status in [MaterialStatus.ORDERED, MaterialStatus.IN_TRANSIT]
        ]
        latest_delivery = max([m.expected_delivery_date for m in pending_deliveries]) if pending_deliveries else None
        
        # Estimate completion (delivery date + 2 weeks installation time)
        estimated_completion = None
        if latest_delivery:
            estimated_completion = latest_delivery + timedelta(days=14)
        
        result = {
            'customer_id': customer_id,
            'customer_name': customer.name,
            'timeline': {
                'materials_ordered': any_ordered,
                'all_materials_delivered': all_delivered,
                'can_modify_project': not any_ordered,
                'latest_expected_delivery': latest_delivery.isoformat() if latest_delivery else None,
                'estimated_completion_date': estimated_completion.isoformat() if estimated_completion else None,
                'message': _get_timeline_message(materials, any_ordered, all_delivered, latest_delivery, estimated_completion)
            },
            'materials_breakdown': [
                {
                    'id': m.id,
                    'description': m.material_description,
                    'status': m.status.value if hasattr(m.status, 'value') else m.status,
                    'delivery_status': f"{(m.status.value if hasattr(m.status, 'value') else m.status).replace('_', ' ').title()}"
                } for m in materials
            ]
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching project timeline for {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

def _get_timeline_message(materials, any_ordered, all_delivered, latest_delivery, estimated_completion):
    """Generate human-readable timeline message for managers"""
    if not any_ordered:
        return "✅ No materials ordered yet - Full modifications possible"
    elif all_delivered:
        return "✅ All materials delivered - Ready for installation"
    elif latest_delivery and estimated_completion:
        delivery_str = latest_delivery.strftime('%d %b %Y')
        completion_str = estimated_completion.strftime('%d %b %Y')
        return f"📦 Materials expected by {delivery_str} - Estimated completion: {completion_str}"
    else:
        return "⚠️ Materials ordered but no delivery dates confirmed - Check with supplier"


# ==========================================
# PRODUCTION TEAM NOTIFICATIONS (OPTIMIZED)
# ==========================================

@materials_bp.route('/materials/notifications/pending-orders', methods=['GET'])
@token_required
def get_pending_material_orders():
    """
    Get list of customers waiting for materials to be ordered
    
    OPTIMIZATIONS:
    - 5-minute cache for pending orders
    - Eager loading of customer relationship
    """
    user_role = request.current_user.role.lower() if request.current_user.role else ''
    
    if user_role not in ['manager', 'production']:
        return jsonify({'error': 'Unauthorized - Only Manager and Production can view pending orders'}), 403
    
    # Check cache first
    cache_key = "pending_orders"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load customer data
        pending = session.query(MaterialOrder)\
            .options(joinedload(MaterialOrder.customer))\
            .filter(MaterialOrder.status == MaterialStatus.NOT_ORDERED)\
            .order_by(MaterialOrder.created_at.asc())\
            .all()
        
        result = {
            'pending_count': len(pending),
            'pending_orders': [
                {
                    'material_order_id': m.id,
                    'customer_name': m.customer.name if m.customer else 'Unknown',
                    'customer_id': m.customer_id,
                    'material_description': m.material_description,
                    'created_at': m.created_at.isoformat(),
                    'days_pending': (datetime.utcnow() - m.created_at).days
                } for m in pending
            ]
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching pending orders: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


if __name__ == "__main__":
    print("Material Tracking API Routes Ready!")
    print("\nEndpoints created:")
    print("- GET    /materials (list all)")
    print("- GET    /materials/<id> (get single)")
    print("- GET    /materials/customer/<customer_id> (by customer)")
    print("- POST   /materials (create)")
    print("- PATCH  /materials/<id> (update)")
    print("- DELETE /materials/<id> (delete)")
    print("- GET    /materials/dashboard/overview (manager dashboard)")
    print("- GET    /materials/timeline/<customer_id> (project timeline)")
    print("- GET    /materials/notifications/pending-orders (production notifications)")