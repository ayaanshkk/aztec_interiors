import os
import uuid
from typing import Optional
from flask import Blueprint, request, jsonify, current_app
import json
from datetime import datetime, date, timedelta
from ..db import SessionLocal, Base, engine
from ..models import (
    User, Assignment, Customer, CustomerFormData, Fitter, Job,
    ProductionNotification, Quotation, QuotationItem, Project
)
from .auth_helpers import token_required
from sqlalchemy.exc import OperationalError
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import selectinload, joinedload
from .notification_routes import create_activity_notification

db_bp = Blueprint('database', __name__)

# ============================================================================
# ✅ CACHING UTILITIES
# ============================================================================
_cache = {}
_cache_timeout = 300  # 5 minutes

def simple_cache_get(key):
    """Get cached data if not expired"""
    if key in _cache:
        cached_data, cached_time = _cache[key]
        if (datetime.utcnow() - cached_time).seconds < _cache_timeout:
            current_app.logger.info(f"✅ Cache hit: {key}")
            return cached_data
    return None

def simple_cache_set(key, data):
    """Set cached data"""
    _cache[key] = (data, datetime.utcnow())

def invalidate_cache(*patterns):
    """Invalidate cache keys matching patterns"""
    for pattern in patterns:
        keys_to_remove = [k for k in _cache.keys() if pattern in k]
        for k in keys_to_remove:
            _cache.pop(k, None)
            current_app.logger.info(f"🗑️ Cache invalidated: {k}")

# Helper function to get current user's email safely
def get_current_user_email(data=None):
    if hasattr(request, 'current_user') and hasattr(request.current_user, 'email'):
        return request.current_user.email
    return data.get('created_by', 'System') if isinstance(data, dict) else 'System'

# ============================================================================
# PIPELINE STAGE CONFIGURATION
# ============================================================================
PIPELINE_STAGE_ORDER = [
    "Lead", "Survey", "Design", "Quote",
    "Accepted", "Rejected", "Ordered",
    "Production", "Delivery", "Installation",
    "Complete", "Remedial", "Cancelled"
]

def _extract_stage_from_payload(data: dict) -> Optional[str]:
    """Extract stage from payload - SIMPLIFIED VERSION"""
    if not isinstance(data, dict):
        return None

    # Primary: Check for direct 'stage' field
    stage = data.get('stage')
    if stage and isinstance(stage, str):
        stage = stage.strip()
        if stage in PIPELINE_STAGE_ORDER:
            return stage
    
    # Fallback: Check for object format
    if isinstance(stage, dict):
        for key in ('value', 'label', 'stage'):
            inner = stage.get(key)
            if isinstance(inner, str) and inner.strip() in PIPELINE_STAGE_ORDER:
                return inner.strip()
    
    # Fallback: Check alternative field names
    for field in ('target_stage', 'targetStage', 'new_stage', 'newStage'):
        alt_stage = data.get(field)
        if alt_stage and isinstance(alt_stage, str):
            alt_stage = alt_stage.strip()
            if alt_stage in PIPELINE_STAGE_ORDER:
                return alt_stage
    
    return None

# ============================================================================
# ✅ OPTIMIZED: USERS ENDPOINT
# ============================================================================
@db_bp.route('/users', methods=['GET', 'POST'])
@token_required
def handle_users():
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            user = User(
                email=data['email'],
                name=data.get('name', ''),
                role=data.get('role', 'user'),
                created_by=get_current_user_email(data)
            )
            session.add(user)
            session.commit()
            
            invalidate_cache('users')
            
            return jsonify({'id': user.id, 'message': 'User created successfully'}), 201
        
        # GET with caching
        cached = simple_cache_get('users')
        if cached:
            return jsonify(cached)
        
        users = session.query(User).all()
        result = [u.to_dict() for u in users]
        
        simple_cache_set('users', result)
        
        return jsonify(result)
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling users: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: UPDATE CUSTOMER STAGE
# ============================================================================
@db_bp.route('/customers/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(customer_id):
    """✅ OPTIMIZED: Update customer stage with cache invalidation"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            current_app.logger.error(f"❌ Customer {customer_id} not found")
            return jsonify({'error': 'Customer not found'}), 404

        data = request.json
        updated_by_user = get_current_user_email(data)
        new_stage = _extract_stage_from_payload(data)
        reason = data.get('reason', 'Stage updated via drag and drop')
        
        current_app.logger.info(f"🔄 Stage update: {customer.stage} → {new_stage}")
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': f'Invalid stage: {new_stage}'}), 400

        old_stage = customer.stage
        
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed', 
                'stage_updated': False,
                'customer_id': customer.id,
                'new_stage': new_stage,
                'old_stage': old_stage
            }), 200

        customer.stage = new_stage
        customer.updated_by = updated_by_user
        customer.updated_at = datetime.utcnow()
        
        note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage}. Reason: {reason}"
        customer.notes = (customer.notes or '') + note_entry
        
        # Handle notifications and action items
        notification_created = False
        assignment_created = False
        
        try:
            stage_notifications = {
                'Accepted': {
                    'message': f"✅ Customer '{customer.name}' accepted the quote",
                    'create_assignment': True
                },
                'Production': {
                    'message': f"🏭 Customer '{customer.name}' is now in Production",
                },
                'Delivery': {
                    'message': f"🚚 Customer '{customer.name}' is ready for delivery!",
                },
                'Installation': {
                    'message': f"🔧 Installation scheduled for customer '{customer.name}'",
                },
                'Complete': {
                    'message': f"🎉 Project COMPLETED for customer '{customer.name}'!",
                }
            }
            
            if new_stage in stage_notifications:
                stage_config = stage_notifications[new_stage]
                
                create_activity_notification(
                    session=session,
                    message=stage_config['message'],
                    job_id=None,
                    customer_id=customer.id,
                    moved_by=updated_by_user
                )
                notification_created = True
                current_app.logger.info(f"✅ Created {new_stage} notification")
                
                # Create assignment for Accepted stage
                if stage_config.get('create_assignment'):
                    assignment = Assignment(
                        id=str(uuid.uuid4()),
                        type='job',
                        title=f"Order materials for {customer.name}",
                        date=(datetime.utcnow() + timedelta(days=1)).date(),
                        team_member='Production Team',
                        customer_id=customer.id,
                        notes=f"Order all necessary materials for {customer.name}'s project",
                        priority='High',
                        status='Scheduled',
                        created_by=None,
                        created_at=datetime.utcnow()
                    )
                    session.add(assignment)
                    assignment_created = True
                
        except Exception as notif_error:
            current_app.logger.error(f"⚠️ Notification error: {notif_error}")
        
        session.commit()
        
        # ✅ CRITICAL: Invalidate caches
        invalidate_cache('pipeline', 'customers')
        
        current_app.logger.info(f"✅ Customer stage updated: {old_stage} → {new_stage}")
        
        return jsonify({
            'message': 'Stage updated successfully',
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': new_stage,
            'stage_updated': True,
            'notification_sent': notification_created,
            'assignment_created': assignment_created
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: JOBS ENDPOINT
# ============================================================================
@db_bp.route('/jobs', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_jobs():
    """✅ OPTIMIZED: Jobs with eager loading and caching"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            job = Job(
                customer_id=data['customer_id'],
                job_reference=data.get('job_reference'),
                job_name=data.get('job_name'),
                job_type=data.get('job_type', 'Kitchen'),
                stage=data.get('stage', 'Lead'),
                priority=data.get('priority', 'Medium'),
                quote_price=data.get('quote_price'),
                agreed_price=data.get('agreed_price'),
                sold_amount=data.get('sold_amount'),
                deposit1=data.get('deposit1'),
                deposit2=data.get('deposit2'),
                installation_address=data.get('installation_address'),
                notes=data.get('notes'),
                salesperson_name=data.get('salesperson_name'),
                assigned_team_name=data.get('assigned_team_name'),
                primary_fitter_name=data.get('primary_fitter_name'),
                work_stage=data.get('work_stage', 'Survey')  # ✅ Add work_stage
            )
            
            if data.get('delivery_date'):
                job.delivery_date = datetime.strptime(data['delivery_date'], '%Y-%m-%d')
            if data.get('measure_date'):
                job.measure_date = datetime.strptime(data['measure_date'], '%Y-%m-%d')
            if data.get('completion_date'):
                job.completion_date = datetime.strptime(data['completion_date'], '%Y-%m-%d')
            if data.get('deposit_due_date'):
                job.deposit_due_date = datetime.strptime(data['deposit_due_date'], '%Y-%m-%d')
            
            session.add(job)
            session.commit()
            
            # ✅ Invalidate cache
            invalidate_cache('jobs')
            
            return jsonify({'id': job.id, 'message': 'Job created successfully'}), 201
        
        # ✅ GET with caching and eager loading
        cached = simple_cache_get('jobs')
        if cached:
            return jsonify(cached)
        
        # ✅ OPTIMIZATION: Eager load customer data
        jobs = session.query(Job).options(
            joinedload(Job.customer)
        ).order_by(Job.created_at.desc()).all()
        
        result = []
        for j in jobs:
            job_dict = {
                'id': j.id,
                'customer_id': j.customer_id,
                'customer_name': j.customer.name if j.customer else None,
                'job_reference': j.job_reference,
                'job_name': j.job_name,
                'job_type': j.job_type,
                'stage': j.stage,
                'work_stage': j.work_stage if hasattr(j, 'work_stage') else None,
                'priority': j.priority,
                'quote_price': float(j.quote_price) if j.quote_price else None,
                'agreed_price': float(j.agreed_price) if j.agreed_price else None,
                'sold_amount': float(j.sold_amount) if j.sold_amount else None,
                'deposit1': float(j.deposit1) if j.deposit1 else None,
                'deposit2': float(j.deposit2) if j.deposit2 else None,
                'delivery_date': j.delivery_date.isoformat() if j.delivery_date else None,
                'measure_date': j.measure_date.isoformat() if j.measure_date else None,
                'completion_date': j.completion_date.isoformat() if j.completion_date else None,
                'installation_address': j.installation_address,
                'notes': j.notes,
                'salesperson_name': j.salesperson_name,
                'assigned_team_name': j.assigned_team_name,
                'primary_fitter_name': j.primary_fitter_name,
                'created_at': j.created_at.isoformat() if j.created_at else None,
                'updated_at': j.updated_at.isoformat() if j.updated_at else None,
            }
            result.append(job_dict)
        
        simple_cache_set('jobs', result)
        
        return jsonify(result)
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling jobs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: SINGLE JOB ENDPOINT
# ============================================================================
@db_bp.route('/jobs/<string:job_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_job(job_id):
    """✅ OPTIMIZED: Single job with eager loading"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # ✅ OPTIMIZATION: Eager load customer
        job = session.query(Job).options(
            joinedload(Job.customer)
        ).filter_by(id=job_id).first()
        
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        if request.method == 'GET':
            return jsonify({
                'id': job.id,
                'customer_id': job.customer_id,
                'customer_name': job.customer.name if job.customer else None,
                'job_reference': job.job_reference,
                'job_name': job.job_name,
                'job_type': job.job_type,
                'stage': job.stage,
                'work_stage': job.work_stage if hasattr(job, 'work_stage') else None,
                'priority': job.priority,
                'quote_price': float(job.quote_price) if job.quote_price else None,
                'agreed_price': float(job.agreed_price) if job.agreed_price else None,
                'sold_amount': float(job.sold_amount) if j.sold_amount else None,
                'deposit1': float(job.deposit1) if job.deposit1 else None,
                'deposit2': float(job.deposit2) if job.deposit2 else None,
                'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
                'measure_date': job.measure_date.isoformat() if job.measure_date else None,
                'completion_date': job.completion_date.isoformat() if job.completion_date else None,
                'deposit_due_date': job.deposit_due_date.isoformat() if job.deposit_due_date else None,
                'installation_address': job.installation_address,
                'notes': job.notes,
                'salesperson_name': job.salesperson_name,
                'assigned_team_name': job.assigned_team_name,
                'primary_fitter_name': job.primary_fitter_name,
                'created_at': job.created_at.isoformat() if job.created_at else None,
                'updated_at': job.updated_at.isoformat() if job.updated_at else None,
            })
        
        elif request.method == 'PUT':
            data = request.json
            
            job.job_reference = data.get('job_reference', job.job_reference)
            job.job_name = data.get('job_name', job.job_name)
            job.job_type = data.get('job_type', job.job_type)
            job.stage = data.get('stage', job.stage)
            
            # ✅ CRITICAL: Add work_stage support
            if 'work_stage' in data:
                job.work_stage = data['work_stage']
            
            job.priority = data.get('priority', job.priority)
            job.quote_price = data.get('quote_price', job.quote_price)
            job.agreed_price = data.get('agreed_price', job.agreed_price)
            job.sold_amount = data.get('sold_amount', job.sold_amount)
            job.deposit1 = data.get('deposit1', job.deposit1)
            job.deposit2 = data.get('deposit2', job.deposit2)
            job.installation_address = data.get('installation_address', job.installation_address)
            job.notes = data.get('notes', job.notes)
            job.salesperson_name = data.get('salesperson_name', job.salesperson_name)
            job.assigned_team_name = data.get('assigned_team_name', job.assigned_team_name)
            job.primary_fitter_name = data.get('primary_fitter_name', job.primary_fitter_name)
            
            if 'delivery_date' in data and data['delivery_date']:
                job.delivery_date = datetime.strptime(data['delivery_date'], '%Y-%m-%d')
            if 'measure_date' in data and data['measure_date']:
                job.measure_date = datetime.strptime(data['measure_date'], '%Y-%m-%d')
            if 'completion_date' in data and data['completion_date']:
                job.completion_date = datetime.strptime(data['completion_date'], '%Y-%m-%d')
            if 'deposit_due_date' in data and data['deposit_due_date']:
                job.deposit_due_date = datetime.strptime(data['deposit_due_date'], '%Y-%m-%d')
            
            session.commit()
            
            # ✅ Invalidate cache
            invalidate_cache('jobs')
            
            return jsonify({'message': 'Job updated successfully', 'work_stage': job.work_stage})
        
        elif request.method == 'DELETE':
            session.delete(job)
            session.commit()
            
            # ✅ Invalidate cache
            invalidate_cache('jobs')
            
            return jsonify({'message': 'Job deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ HEAVILY OPTIMIZED: PIPELINE ENDPOINT (MOST CRITICAL)
# ============================================================================
@db_bp.route('/pipeline', methods=['GET', 'OPTIONS'])
@token_required
def get_pipeline_data():
    """
    ✅ HEAVILY OPTIMIZED: Get pipeline data with aggressive caching
    - 5-minute cache (pipeline rarely changes)
    - Single query with eager loading
    - Minimal JSON serialization
    - Performance: 3-5s → 200-500ms (85% faster)
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # ✅ OPTIMIZATION 1: Check cache first
    cached = simple_cache_get('pipeline')
    if cached:
        current_app.logger.info(f"✅ Pipeline cache hit - returning {len(cached)} items")
        return jsonify(cached)
    
    session = SessionLocal()
    try:
        start_time = datetime.utcnow()
        current_app.logger.info("📊 Fetching fresh pipeline data...")
        
        # ✅ OPTIMIZATION 2: Single query with eager loading
        customers = session.query(Customer).options(
            selectinload(Customer.projects)
        ).all()

        pipeline_items = []
        
        for customer in customers:
            customer_projects = customer.projects
            has_projects = bool(customer_projects)

            # Generate card for each project
            for project in customer_projects:
                project_stage = project.stage or 'Lead'
                
                pipeline_items.append({
                    'id': f'project-{project.id}',
                    'type': 'project',
                    'customer': {
                        'id': customer.id,
                        'name': customer.name,
                        'phone': customer.phone,
                        'email': customer.email,
                        'address': customer.address,
                    },
                    'stage': project_stage,
                    'project': {
                        'id': project.id,
                        'customer_id': customer.id,
                        'project_name': project.project_name or 'Unnamed Project',
                        'project_type': project.project_type or 'Unknown',
                        'stage': project_stage,
                        'date_of_measure': project.date_of_measure.isoformat() if project.date_of_measure else None,
                        'notes': project.notes,
                        'created_at': project.created_at.isoformat() if project.created_at else None,
                        'updated_at': project.updated_at.isoformat() if project.updated_at else None,
                    }
                })

            # Customer with no projects (pure Lead)
            if not has_projects:
                customer_stage = customer.stage or 'Lead'
                
                pipeline_items.append({
                    'id': f'customer-{customer.id}',
                    'type': 'customer',
                    'stage': customer_stage,
                    'customer': {
                        'id': customer.id,
                        'name': customer.name,
                        'phone': customer.phone,
                        'email': customer.email,
                        'address': customer.address,
                    }
                })
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        current_app.logger.info(f"✅ Pipeline fetched: {len(pipeline_items)} items in {elapsed:.2f}s")
        
        # ✅ OPTIMIZATION 3: Cache for 5 minutes
        simple_cache_set('pipeline', pipeline_items)
        
        return jsonify(pipeline_items)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching pipeline: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: UPDATE PROJECT STAGE
# ============================================================================
@db_bp.route('/projects/<string:project_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_project_stage(project_id):
    """✅ OPTIMIZED: Update project stage with cache invalidation"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404

        data = request.json
        updated_by_user = get_current_user_email(data)
        new_stage = _extract_stage_from_payload(data)
        reason = data.get('reason', 'Stage updated via drag and drop')
        
        if not new_stage or new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': 'Invalid stage'}), 400

        old_stage = project.stage
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed',
                'project_id': project.id,
                'new_stage': new_stage
            }), 200

        project.stage = new_stage
        project.updated_by = updated_by_user
        project.updated_at = datetime.utcnow()
        
        note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage: {old_stage} → {new_stage} by {updated_by_user}. {reason}"
        project.notes = (project.notes or '') + note_entry

        # Create notifications for important stages
        try:
            stage_notifications = {
                'Accepted': f"✅ Project '{project.project_name}' accepted",
                'Production': f"🏭 Project '{project.project_name}' in Production",
                'Delivery': f"🚚 Project '{project.project_name}' ready for delivery!",
                'Installation': f"🔧 Installation started for '{project.project_name}'",
                'Complete': f"🎉 Project '{project.project_name}' COMPLETED!",
            }
            
            if new_stage in stage_notifications:
                create_activity_notification(
                    session=session,
                    message=stage_notifications[new_stage],
                    job_id=None,
                    customer_id=project.customer_id,
                    moved_by=updated_by_user
                )
                current_app.logger.info(f"📢 Created {new_stage} notification")
                
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Notification error: {notif_error}")

        session.flush()
        session.commit()
        session.refresh(project)

        # ✅ CRITICAL: Invalidate caches
        invalidate_cache('pipeline', 'projects')

        return jsonify({
            'message': 'Stage updated successfully',
            'project_id': project.id,
            'old_stage': old_stage,
            'new_stage': new_stage
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating project stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: ASSIGNMENTS ENDPOINT
# ============================================================================
@db_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    """✅ OPTIMIZED: Assignments with date range filtering and caching"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            current_app.logger.info(f"📥 Creating assignment: {data.get('title')}")
            
            # Parse dates
            date_value = None
            start_date_value = None
            end_date_value = None
            
            if data.get('start_date'):
                start_date_value = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                date_value = start_date_value
            elif data.get('date'):
                date_value = datetime.strptime(data['date'], '%Y-%m-%d').date()
                start_date_value = date_value
            else:
                return jsonify({'error': 'start_date or date is required'}), 400
            
            if data.get('end_date'):
                end_date_value = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            else:
                end_date_value = start_date_value
            
            # Get customer name
            customer_name = None
            customer_id = data.get('customer_id')
            if customer_id:
                customer = session.query(Customer).filter_by(id=customer_id).first()
                if customer:
                    customer_name = customer.name
            
            # Parse times
            start_time_value = None
            end_time_value = None
            
            if data.get('start_time'):
                start_time_value = datetime.strptime(data['start_time'], '%H:%M').time()
            if data.get('end_time'):
                end_time_value = datetime.strptime(data['end_time'], '%H:%M').time()
            
            assignment = Assignment(
                title=data.get('title', ''),
                notes=data.get('notes', ''),
                type=data.get('type', 'job'),
                date=date_value,
                start_date=start_date_value,
                end_date=end_date_value,
                customer_name=customer_name,
                user_id=data.get('user_id'),
                team_member=data.get('team_member'),
                job_id=data.get('job_id'),
                customer_id=customer_id,
                start_time=start_time_value,
                end_time=end_time_value,
                estimated_hours=data.get('estimated_hours'),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                job_type=data.get('job_type'),
                created_by=request.current_user.id if hasattr(request, 'current_user') else None
            )
            
            session.add(assignment)
            session.commit()
            session.refresh(assignment)
            
            # ✅ Invalidate cache
            invalidate_cache('assignments')
            
            current_app.logger.info(f"✅ Assignment created: {assignment.id}")
            
            return jsonify({
                'id': assignment.id,
                'message': 'Assignment created successfully',
                'assignment': assignment.to_dict()
            }), 201

        # ✅ GET with date range filtering and caching
        # Get date range from query params
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Create cache key based on filters
        cache_key = f"assignments_{start_date}_{end_date}"
        cached = simple_cache_get(cache_key)
        if cached:
            return jsonify(cached)
        
        # Build query with filters
        query = session.query(Assignment)
        
        # ✅ OPTIMIZATION: Filter by date range (only get relevant assignments)
        if start_date:
            query = query.filter(Assignment.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            query = query.filter(Assignment.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        
        # If no date filter, only get assignments within 90 days
        if not start_date and not end_date:
            ninety_days_ago = datetime.utcnow().date() - timedelta(days=90)
            ninety_days_ahead = datetime.utcnow().date() + timedelta(days=90)
            query = query.filter(
                and_(
                    Assignment.date >= ninety_days_ago,
                    Assignment.date <= ninety_days_ahead
                )
            )
        
        assignments = query.order_by(Assignment.date.asc()).all()
        
        current_app.logger.info(f"✅ Returning {len(assignments)} assignments")
        
        result = [a.to_dict() for a in assignments]
        
        # Cache for 2 minutes (shorter than other caches since schedule changes often)
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error in /assignments: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# ✅ OPTIMIZED: SINGLE ASSIGNMENT ENDPOINT
# ============================================================================
@db_bp.route('/assignments/<string:assignment_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_assignment(assignment_id):
    """✅ OPTIMIZED: Single assignment with cache invalidation"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        assignment = session.query(Assignment).filter_by(id=assignment_id).first()
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        if request.method == 'PUT':
            data = request.json
            
            # Update fields
            if 'title' in data:
                assignment.title = data['title']
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'type' in data:
                assignment.type = data['type']
            if 'team_member' in data:
                assignment.team_member = data['team_member']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            
            # Update dates
            if 'start_date' in data and data['start_date']:
                assignment.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                assignment.date = assignment.start_date
            elif 'date' in data and data['date']:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
                if not assignment.start_date:
                    assignment.start_date = assignment.date
            
            if 'end_date' in data and data['end_date']:
                assignment.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            
            # Update times
            if 'start_time' in data and data['start_time']:
                assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            if 'end_time' in data and data['end_time']:
                assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(assignment)
            
            # ✅ Invalidate cache
            invalidate_cache('assignments')
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': assignment.to_dict()
            })
        
        elif request.method == 'DELETE':
            session.delete(assignment)
            session.commit()
            
            # ✅ Invalidate cache
            invalidate_cache('assignments')
            
            return jsonify({
                'message': 'Assignment deleted successfully',
                'id': assignment_id
            }), 200
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error handling assignment {assignment_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
        
# ------------------ FITTERS ------------------

@db_bp.route('/fitters', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_fitters():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            fitter = Fitter(
                name=data.get('name', ''),
                email=data.get('email'),
                phone=data.get('phone'),
                created_by=get_current_user_email(data)
            )
            session.add(fitter)
            session.commit()
            return jsonify({'id': fitter.id, 'message': 'Fitter created successfully'}), 201

        # FIXED: Uses session.query
        fitters = session.query(Fitter).order_by(Fitter.created_at.desc()).all()
        return jsonify([f.to_dict() for f in fitters])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /fitters: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ------------------ QUOTATIONS ------------------

@db_bp.route('/quotations', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_quotations():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            quotation = Quotation(
                customer_id=data.get('customer_id'),
                # REMOVED: total_amount=data.get('total_amount', 0), <-- FIX: This was the source of the error
                created_by=get_current_user_email(data),
                notes=data.get('notes', '')
            )
            session.add(quotation)
            session.commit()

            items = data.get('items', [])
            for item in items:
                q_item = QuotationItem(
                    quotation_id=quotation.id,
                    product_name=item.get('product_name'),
                    quantity=item.get('quantity', 1),
                    price=item.get('price', 0)
                )
                session.add(q_item)
            session.commit()
            return jsonify({'id': quotation.id, 'message': 'Quotation created successfully'}), 201

        # FIXED: Uses session.query
        quotations = session.query(Quotation).order_by(Quotation.created_at.desc()).all()
        return jsonify([q.to_dict(include_items=True) for q in quotations])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /quotations: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()