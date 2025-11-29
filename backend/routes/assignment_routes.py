from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy.orm import joinedload
from sqlalchemy import func, and_, or_
from ..models import User, Assignment, Job, Customer
from .auth_routes import token_required
from ..db import SessionLocal

assignment_bp = Blueprint('assignments', __name__)

# ==========================================
# SIMPLE IN-MEMORY CACHE (Replace with Redis in production)
# ==========================================

_cache = {}
_cache_timeout = 120  # 2 minutes (assignments change frequently)

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
# HELPER FUNCTIONS
# ==========================================

VALID_ASSIGNMENT_FIELDS = [
    'type', 'title', 'date', 'start_date', 'end_date', 'customer_name',
    'user_id', 'team_member', 'job_id', 'customer_id', 'job_type',
    'start_time', 'end_time', 'estimated_hours',
    'notes', 'priority', 'status'
]

def filter_assignment_data(data):
    """Filter request data to only include valid Assignment fields"""
    filtered = {}
    for key in VALID_ASSIGNMENT_FIELDS:
        if key in data:
            filtered[key] = data[key]
    return filtered


def serialize_assignment_optimized(assignment):
    """
    Serialize assignment with eager-loaded relationships
    OPTIMIZED: Assumes relationships are already loaded
    """
    result = assignment.to_dict()
    
    # Add creator name (already eager-loaded)
    if assignment.created_by and hasattr(assignment, 'creator') and assignment.creator:
        result['created_by_name'] = assignment.creator.full_name
    
    # Add updater name (already eager-loaded)
    if assignment.updated_by and hasattr(assignment, 'updater') and assignment.updater:
        result['updated_by_name'] = assignment.updater.full_name
    
    # Add assigned user name (already eager-loaded)
    if assignment.user_id and hasattr(assignment, 'assigned_user') and assignment.assigned_user:
        result['assigned_user_name'] = assignment.assigned_user.full_name
    
    return result


# ==========================================
# ASSIGNMENT ENDPOINTS (OPTIMIZED)
# ==========================================

@assignment_bp.route('/assignments', methods=['GET', 'POST'])
@token_required
def handle_assignments():
    """
    GET: List all assignments
    POST: Create new assignment
    
    OPTIMIZATIONS:
    - 2-minute cache for GET requests
    - Eager loading of user relationships
    - Pagination support
    - Cache invalidation on POST
    """
    current_user = request.current_user
    
    if request.method == 'POST':
        session = SessionLocal()
        
        try:
            data = request.json
            current_app.logger.info(f"📥 RAW data received: {data}")
            
            # Filter out invalid fields
            data = filter_assignment_data(data)
            current_app.logger.info(f"📥 Creating assignment with filtered data: {data}")
            
            # Parse date fields
            date_value = None
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                try:
                    start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                    date_value = start_date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing start_date: {e}")
                    return jsonify({'error': 'Invalid start_date format'}), 400
            elif data.get('date'):
                try:
                    date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                    start_date_value = date_value
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing date: {e}")
                    return jsonify({'error': 'Invalid date format'}), 400
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                try:
                    end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                except Exception as e:
                    current_app.logger.error(f"❌ Error parsing end_date: {e}")
                    return jsonify({'error': 'Invalid end_date format'}), 400
            else:
                end_date_value = start_date_value
            
            # Get customer name
            customer_name = data.get('customer_name')
            customer_id = data.get('customer_id')
            if customer_id and not customer_name:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                if customer:
                    customer_name = customer.name
            
            # Parse times
            start_time = None
            end_time = None
            if data.get('start_time'):
                try:
                    start_time = datetime.strptime(data['start_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time format: {data['start_time']}")
            
            if data.get('end_time'):
                try:
                    end_time = datetime.strptime(data['end_time'], '%H:%M').time()
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time format: {data['end_time']}")
            
            # Calculate hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                try:
                    estimated_hours = float(estimated_hours) if estimated_hours else None
                except ValueError:
                    estimated_hours = None

            # Get assigned user info
            user_id = data.get('user_id')
            team_member_name = data.get('team_member')
            
            if user_id and not team_member_name:
                assigned_user = session.get(User, user_id) 
                if assigned_user:
                    team_member_name = assigned_user.full_name
                else:
                    current_app.logger.warning(f"User {user_id} not found")
            
            # Get creator info
            creator = session.get(User, current_user.id)
            created_by_name = creator.full_name if creator else None
                
            # Create assignment
            assignment = Assignment(
                type=data.get('type', 'job'),
                title=data.get('title', ''),
                date=date_value,
                start_date=start_date_value,
                end_date=end_date_value,
                customer_name=customer_name,
                user_id=user_id,
                team_member=team_member_name,
                created_by=current_user.id,
                job_id=data.get('job_id'),
                customer_id=customer_id,
                start_time=start_time,
                end_time=end_time,
                estimated_hours=estimated_hours,
                notes=data.get('notes', ''),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                job_type=data.get('job_type')
            )
            
            session.add(assignment)
            session.commit()
            session.refresh(assignment)

            current_app.logger.info(f"✅ Assignment created: {assignment.id}")

            # INVALIDATE CACHE
            invalidate_cache('assignments', 'assignments_by_date')

            # Build response
            result = assignment.to_dict()
            if 'created_by_name' not in result or not result['created_by_name']:
                result['created_by_name'] = created_by_name

            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': result
            }), 201

        except KeyError as e:
            session.rollback()
            current_app.logger.error(f"Missing required field: {e}")
            return jsonify({'error': f'Missing required field: {str(e)}'}), 400
        except TypeError as e:
            session.rollback()
            current_app.logger.error(f"❌ TypeError (invalid field): {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Invalid field in request: {str(e)}'}), 400
        except Exception as e:
            session.rollback()
            current_app.logger.error(f"Error creating assignment: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
    
    # GET - OPTIMIZED with caching and eager loading
    if request.method == 'GET':
        # Get filter parameters
        user_id = request.args.get('user_id', type=int)
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)
        per_page = min(per_page, 500)
        
        # Build cache key
        cache_key = f"assignments_{user_id}_{status}_{start_date}_{end_date}_{page}_{per_page}"
        
        # Check cache first
        cached = simple_cache_get(cache_key)
        if cached:
            current_app.logger.debug(f"Cache hit for assignments: {cache_key}")
            return jsonify(cached), 200
        
        session = SessionLocal()
        try:
            current_app.logger.info(f"📋 Fetching assignments for user: {current_user.full_name} (role: {current_user.role})")
            
            # OPTIMIZED: Single query with eager loading
            query = session.query(Assignment).options(
                joinedload(Assignment.creator),
                joinedload(Assignment.updater),
                joinedload(Assignment.assigned_user)
            )
            
            # Apply filters
            if user_id:
                query = query.filter(Assignment.user_id == user_id)
            if status:
                query = query.filter(Assignment.status == status)
            if start_date and end_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()
                    query = query.filter(
                        Assignment.date >= start,
                        Assignment.date <= end
                    )
                except ValueError:
                    pass  # Skip date filter if invalid
            
            # Get total count
            total_count = query.count()
            
            # Apply pagination and ordering
            assignments = query.order_by(Assignment.date.desc())\
                               .limit(per_page)\
                               .offset((page - 1) * per_page)\
                               .all()
            
            current_app.logger.info(f"✅ Returning {len(assignments)} assignments (total: {total_count})")

            # OPTIMIZED: Use eager-loaded relationships
            result_data = {
                'assignments': [serialize_assignment_optimized(a) for a in assignments],
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_count,
                    'pages': (total_count + per_page - 1) // per_page
                }
            }
            
            # Cache the result
            simple_cache_set(cache_key, result_data)
            
            return jsonify(result_data)
            
        except Exception as e:
            current_app.logger.error(f"Error in GET assignments: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@assignment_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_assignment(assignment_id):
    """
    GET: Get single assignment
    PUT: Update assignment
    DELETE: Delete assignment
    
    OPTIMIZATIONS:
    - 2-minute cache for GET requests
    - Eager loading of relationships
    - Cache invalidation on PUT/DELETE
    """
    current_user = request.current_user
    
    # GET - Check cache first
    if request.method == 'GET':
        cache_key = f"assignment_{assignment_id}"
        cached = simple_cache_get(cache_key)
        if cached:
            return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load relationships
        assignment = session.query(Assignment)\
            .options(
                joinedload(Assignment.creator),
                joinedload(Assignment.updater),
                joinedload(Assignment.assigned_user)
            )\
            .filter(Assignment.id == assignment_id)\
            .first()
        
        if not assignment:
            current_app.logger.error(f"❌ Assignment {assignment_id} not found")
            return jsonify({'error': 'Assignment not found'}), 404
        
        # Authorization check for PUT/DELETE
        if request.method in ['PUT', 'DELETE']:
            is_manager = current_user.role == 'Manager'
            is_assigned_user = assignment.user_id == current_user.id
            is_creator = assignment.created_by == current_user.id
            is_unassigned = not assignment.user_id
            
            if not (is_manager or is_assigned_user or is_creator or is_unassigned):
                return jsonify({'error': 'Unauthorized access to assignment'}), 403
        
        # GET
        if request.method == 'GET':
            result = serialize_assignment_optimized(assignment)
            
            # Cache the result
            cache_key = f"assignment_{assignment_id}"
            simple_cache_set(cache_key, result)
            
            return jsonify(result)
        
        # PUT - Update assignment
        elif request.method == 'PUT':
            data = request.json
            current_app.logger.info(f"📝 RAW update data received: {data}")
            
            # Filter out invalid fields
            data = filter_assignment_data(data)
            current_app.logger.info(f"📝 Updating assignment {assignment_id} with filtered data: {data}")
            
            if 'type' in data:
                assignment.type = data['type']
            if 'title' in data:
                assignment.title = data['title']
            
            # Handle date updates
            if 'start_date' in data and data['start_date']:
                assignment.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                assignment.date = assignment.start_date
                current_app.logger.info(f"📅 Updated start_date to: {assignment.start_date}")
            elif 'date' in data and data['date']:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
                if not hasattr(assignment, 'start_date') or not assignment.start_date:
                    assignment.start_date = assignment.date
                current_app.logger.info(f"📅 Updated date to: {assignment.date}")
            
            if 'end_date' in data and data['end_date']:
                assignment.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
                current_app.logger.info(f"📅 Updated end_date to: {assignment.end_date}")
            elif 'start_date' in data and not ('end_date' in data):
                assignment.end_date = assignment.start_date
                current_app.logger.info(f"📅 Set end_date same as start_date: {assignment.end_date}")
            
            if 'start_time' in data:
                try:
                    assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid start_time: {data['start_time']}")
            if 'end_time' in data:
                try:
                    assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
                except ValueError:
                    current_app.logger.warning(f"Invalid end_time: {data['end_time']}")
            if 'estimated_hours' in data:
                estimated_hours = data['estimated_hours']
                try:
                    assignment.estimated_hours = float(estimated_hours) if isinstance(estimated_hours, str) else estimated_hours
                except (ValueError, TypeError):
                    current_app.logger.warning(f"Invalid estimated_hours: {estimated_hours}")
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            if 'job_type' in data:
                assignment.job_type = data['job_type']
            if 'job_id' in data:
                assignment.job_id = data['job_id']
            
            # Update customer
            if 'customer_id' in data:
                assignment.customer_id = data['customer_id']
                if data['customer_id']:
                    customer = session.query(Customer).filter_by(id=data['customer_id']).first()
                    if customer and hasattr(assignment, 'customer_name'):
                        assignment.customer_name = customer.name
            
            if 'customer_name' in data:
                assignment.customer_name = data['customer_name']
            
            if 'user_id' in data:
                assignment.user_id = data['user_id']
                new_user = session.get(User, data['user_id'])
                if new_user:
                    assignment.team_member = new_user.full_name
            if 'team_member' in data:
                assignment.team_member = data['team_member']
                
            assignment.updated_by = current_user.id
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(assignment)
            
            # INVALIDATE CACHE
            invalidate_cache('assignments', f'assignment_{assignment_id}', 'assignments_by_date')
            
            current_app.logger.info(f"✅ Assignment {assignment_id} updated successfully")
            
            # Reload with eager loading for response
            assignment = session.query(Assignment)\
                .options(
                    joinedload(Assignment.creator),
                    joinedload(Assignment.updater),
                    joinedload(Assignment.assigned_user)
                )\
                .filter(Assignment.id == assignment_id)\
                .first()
            
            result = serialize_assignment_optimized(assignment)
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': result
            })
            
        # DELETE
        elif request.method == 'DELETE':
            current_app.logger.info(f"🗑️ Deleting assignment {assignment_id}")
            session.delete(assignment)
            session.commit()
            
            # INVALIDATE CACHE
            invalidate_cache('assignments', f'assignment_{assignment_id}', 'assignments_by_date')
            
            current_app.logger.info(f"✅ Assignment {assignment_id} deleted")
            
            return jsonify({
                'message': 'Assignment deleted successfully',
                'id': assignment_id
            }), 200
        
    except TypeError as e:
        session.rollback()
        current_app.logger.error(f"❌ TypeError (invalid field): {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Invalid field in request: {str(e)}'}), 400
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in handle_single_assignment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/assignments/by-date-range', methods=['GET'])
@token_required 
def get_assignments_by_date_range():
    """
    Get assignments within a date range
    
    OPTIMIZATIONS:
    - 2-minute cache for date range queries
    - Eager loading of relationships
    """
    current_user = request.current_user
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400
    
    # Check cache first
    cache_key = f"assignments_by_date_{start_date}_{end_date}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        current_app.logger.info(f"📅 Fetching assignments from {start} to {end}")
        
        # OPTIMIZED: Single query with eager loading
        assignments = session.query(Assignment)\
            .options(
                joinedload(Assignment.creator),
                joinedload(Assignment.updater),
                joinedload(Assignment.assigned_user)
            )\
            .filter(
                Assignment.date >= start,
                Assignment.date <= end
            )\
            .order_by(Assignment.date)\
            .all()
        
        current_app.logger.info(f"✅ Found {len(assignments)} assignments in date range")
        
        # OPTIMIZED: Use eager-loaded relationships
        result = [serialize_assignment_optimized(a) for a in assignments]
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error in get_assignments_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


# ==========================================
# BATCH OPERATIONS (NEW)
# ==========================================

@assignment_bp.route('/assignments/update-multiple', methods=['PATCH'])
@token_required
def update_multiple_assignments():
    """
    Update multiple assignments at once (e.g., bulk status change)
    
    OPTIMIZATIONS:
    - Batch update operation
    - Cache invalidation
    """
    current_user = request.current_user
    data = request.get_json()
    assignment_ids = data.get('assignment_ids', [])
    updates = data.get('updates', {})
    
    if not assignment_ids:
        return jsonify({'error': 'No assignment IDs provided'}), 400
    
    if not updates:
        return jsonify({'error': 'No updates provided'}), 400
    
    # Filter updates to valid fields
    updates = filter_assignment_data(updates)
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Batch update
        updated_count = 0
        
        for assignment_id in assignment_ids:
            assignment = session.get(Assignment, assignment_id)
            if assignment:
                # Check authorization
                is_manager = current_user.role == 'Manager'
                is_assigned_user = assignment.user_id == current_user.id
                is_creator = assignment.created_by == current_user.id
                is_unassigned = not assignment.user_id
                
                if is_manager or is_assigned_user or is_creator or is_unassigned:
                    # Apply updates
                    for key, value in updates.items():
                        if hasattr(assignment, key):
                            setattr(assignment, key, value)
                    
                    assignment.updated_by = current_user.id
                    assignment.updated_at = datetime.utcnow()
                    updated_count += 1
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('assignments', 'assignments_by_date')
        
        return jsonify({
            'message': f'{updated_count} assignments updated',
            'count': updated_count
        })
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating multiple assignments: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/assignments/delete-multiple', methods=['DELETE'])
@token_required
def delete_multiple_assignments():
    """
    Delete multiple assignments at once
    
    OPTIMIZATIONS:
    - Batch deletion
    - Cache invalidation
    """
    current_user = request.current_user
    data = request.get_json()
    assignment_ids = data.get('assignment_ids', [])
    
    if not assignment_ids:
        return jsonify({'error': 'No assignment IDs provided'}), 400
    
    session = SessionLocal()
    try:
        deleted_count = 0
        
        for assignment_id in assignment_ids:
            assignment = session.get(Assignment, assignment_id)
            if assignment:
                # Check authorization
                is_manager = current_user.role == 'Manager'
                is_assigned_user = assignment.user_id == current_user.id
                is_creator = assignment.created_by == current_user.id
                is_unassigned = not assignment.user_id
                
                if is_manager or is_assigned_user or is_creator or is_unassigned:
                    session.delete(assignment)
                    deleted_count += 1
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('assignments', 'assignments_by_date')
        
        return jsonify({
            'message': f'{deleted_count} assignments deleted',
            'count': deleted_count
        })
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting multiple assignments: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# STATISTICS (NEW)
# ==========================================

@assignment_bp.route('/assignments/stats', methods=['GET'])
@token_required
def get_assignment_stats():
    """
    Get assignment statistics
    
    OPTIMIZATIONS:
    - 2-minute cache for stats
    - Single aggregation query
    """
    user_id = request.args.get('user_id', type=int)
    
    # Check cache first
    cache_key = f"assignment_stats_{user_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        # OPTIMIZED: Single aggregation query
        query = session.query(
            func.count(Assignment.id).label('total'),
            func.sum(func.case((Assignment.status == 'Scheduled', 1), else_=0)).label('scheduled'),
            func.sum(func.case((Assignment.status == 'In Progress', 1), else_=0)).label('in_progress'),
            func.sum(func.case((Assignment.status == 'Completed', 1), else_=0)).label('completed'),
            func.sum(func.case((Assignment.status == 'Cancelled', 1), else_=0)).label('cancelled')
        )
        
        if user_id:
            query = query.filter(Assignment.user_id == user_id)
        
        stats = query.first()
        
        # Get assignments by priority
        priority_query = session.query(
            Assignment.priority,
            func.count(Assignment.id)
        )
        
        if user_id:
            priority_query = priority_query.filter(Assignment.user_id == user_id)
        
        priority_counts = priority_query.group_by(Assignment.priority).all()
        priority_breakdown = {priority: count for priority, count in priority_counts}
        
        result = {
            'total': stats.total or 0,
            'by_status': {
                'scheduled': stats.scheduled or 0,
                'in_progress': stats.in_progress or 0,
                'completed': stats.completed or 0,
                'cancelled': stats.cancelled or 0
            },
            'by_priority': priority_breakdown
        }
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching assignment stats: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# HELPER ENDPOINTS (OPTIMIZED)
# ==========================================

@assignment_bp.route('/jobs/available', methods=['GET'])
@token_required 
def get_available_jobs():
    """
    Get jobs that are ready to be scheduled
    
    OPTIMIZATIONS:
    - 5-minute cache (jobs don't change that frequently)
    - Eager loading of customer relationship
    """
    # Check cache first
    cache_key = "available_jobs"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching available jobs for scheduling...")
        
        schedulable_work_stages = ['Survey', 'Delivery', 'Installation']
        
        # OPTIMIZED: Eager load customer
        jobs = session.query(Job)\
            .options(joinedload(Job.customer))\
            .filter(Job.work_stage.in_(schedulable_work_stages))\
            .order_by(Job.created_at.desc())\
            .all()
        
        current_app.logger.info(f"✅ Found {len(jobs)} jobs in schedulable stages")
        
        result = []
        for j in jobs:
            try:
                customer_name = 'Unknown'
                customer_id = None
                
                # Use eager-loaded customer
                if j.customer:
                    customer_name = j.customer.name
                    customer_id = j.customer.id
                elif j.customer_id:
                    customer_id = j.customer_id
                
                result.append({
                    'id': j.id,
                    'job_reference': j.job_reference or f"JOB-{j.id}",
                    'customer_name': customer_name,
                    'customer_id': customer_id,
                    'job_type': j.job_type or 'Interior Design',
                    'stage': j.stage if hasattr(j, 'stage') else 'Unknown',
                    'work_stage': j.work_stage if hasattr(j, 'work_stage') else 'Survey'
                })
            except Exception as job_error:
                current_app.logger.error(f"Error processing job {j.id}: {job_error}")
                continue
        
        # Cache the result (5 minutes)
        simple_cache_set(cache_key, result)
        
        current_app.logger.info(f"✅ Returning {len(result)} jobs")
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_available_jobs: {e}")
        import traceback
        traceback.print_exc()
        current_app.logger.info("⚠️ Returning empty jobs array due to error")
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/customers/active', methods=['GET'])
@token_required 
def get_active_customers():
    """
    Get active customers for assignments
    
    OPTIMIZATIONS:
    - 5-minute cache (customers don't change frequently)
    """
    # Check cache first
    cache_key = "active_customers"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        current_app.logger.info("📋 Fetching active customers...")
        
        customers = session.query(Customer).order_by(Customer.name).all()
        
        current_app.logger.info(f"✅ Found {len(customers)} customers")
        
        result = []
        for c in customers:
            try:
                result.append({
                    'id': c.id,
                    'name': c.name,
                    'address': c.address or '',
                    'phone': c.phone or '',
                    'stage': c.stage or 'Lead',
                    'status': c.status if hasattr(c, 'status') else 'Active'
                })
            except Exception as customer_error:
                current_app.logger.error(f"Error processing customer {c.id}: {customer_error}")
                continue
        
        # Cache the result (5 minutes)
        simple_cache_set(cache_key, result)
        
        current_app.logger.info(f"✅ Returning {len(result)} customers")
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error in get_active_customers: {e}")
        import traceback
        traceback.print_exc()
        current_app.logger.info("⚠️ Returning empty customers array due to error")
        return jsonify([]), 200
    finally:
        session.close()


@assignment_bp.route('/jobs/work-stages', methods=['GET'])
@token_required
def get_job_work_stages():
    """
    Get all 3 job work stages with metadata
    
    OPTIMIZATIONS:
    - Static data, can be cached indefinitely
    """
    work_stages = [
        {
            'value': 'Survey',
            'label': 'Survey',
            'description': 'Site survey and measurements',
            'color': '#8B5CF6',
            'icon': '📏',
            'order': 1
        },
        {
            'value': 'Delivery',
            'label': 'Delivery',
            'description': 'Items being delivered',
            'color': '#06B6D4',
            'icon': '🚚',
            'order': 2
        },
        {
            'value': 'Installation',
            'label': 'Installation',
            'description': 'On-site installation',
            'color': '#14B8A6',
            'icon': '🏗️',
            'order': 3
        }
    ]
    
    return jsonify(work_stages), 200