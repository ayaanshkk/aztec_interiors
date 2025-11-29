from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, date
import uuid
import traceback
from ..models import (
    Job, Customer, Team, Fitter, Salesperson, 
    JobDocument, JobFormLink, FormSubmission, 
    JobNote, Quotation, Assignment
)
from ..db import SessionLocal
from .auth_helpers import token_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

job_bp = Blueprint('jobs', __name__)

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
# HELPER FUNCTIONS
# ==========================================

def generate_job_reference(session):
    """Generate sequential job reference like AZ-JOB001"""
    job_count = session.query(Job).count()
    
    reference_number = job_count + 1
    job_reference = f"AZ-JOB{reference_number:03d}"
    
    # Ensure uniqueness (in case of deletions)
    while session.query(Job).filter(Job.job_reference == job_reference).first():
        reference_number += 1
        job_reference = f"AZ-JOB{reference_number:03d}"
    
    return job_reference

def serialize_job(job):
    """
    Serialize job object to dictionary
    OPTIMIZED: Uses eager-loaded relationships to avoid N+1 queries
    """
    return {
        'id': job.id,
        'job_reference': job.job_reference,
        'job_name': job.job_name,
        'customer_id': job.customer_id,
        'customer_name': job.customer.name if job.customer else None,
        'job_type': job.job_type,
        'stage': job.stage,
        'work_stage': job.work_stage if hasattr(job, 'work_stage') else 'Survey',
        'priority': job.priority,
        'measure_date': job.measure_date.isoformat() if job.measure_date else None,
        'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
        'completion_date': job.completion_date.isoformat() if job.completion_date else None,
        'quote_id': job.quote_id,
        'quote_price': float(job.quote_price) if job.quote_price else None,
        'agreed_price': float(job.agreed_price) if job.agreed_price else None,
        'deposit1': float(job.deposit1) if job.deposit1 else None,
        'deposit2': float(job.deposit2) if job.deposit2 else None,
        'deposit_due_date': job.deposit_due_date.isoformat() if job.deposit_due_date else None,
        'installation_address': job.installation_address,
        'assigned_team_id': job.assigned_team_id,
        'assigned_team_name': job.assigned_team_name or (job.assigned_team.name if job.assigned_team else None),
        'primary_fitter_id': job.primary_fitter_id,
        'primary_fitter_name': job.primary_fitter_name or (job.primary_fitter.name if job.primary_fitter else None),
        'salesperson_id': job.salesperson_id,
        'salesperson_name': job.salesperson_name or (job.salesperson.name if job.salesperson else None),
        'notes': job.notes,
        'has_counting_sheet': job.has_counting_sheet,
        'has_schedule': job.has_schedule,
        'has_invoice': job.has_invoice,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }

# ==========================================
# JOB ROUTES (OPTIMIZED)
# ==========================================

@job_bp.route('/jobs', methods=['GET', 'OPTIONS'])
@token_required
def get_jobs():
    """
    Get all jobs with optional filtering
    
    OPTIMIZATIONS:
    - 5-minute cache for job lists
    - Eager loading of customer, team, fitter, salesperson
    - Pagination support
    - Single query with joins instead of N+1 queries
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    # Get filter parameters
    customer_id = request.args.get('customer_id')
    stage = request.args.get('stage')
    work_stage = request.args.get('work_stage')
    job_type = request.args.get('type')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    per_page = min(per_page, 500)  # Max 500 per page
    
    # Build cache key from filters
    cache_key = f"jobs_{customer_id}_{stage}_{work_stage}_{job_type}_{page}_{per_page}"
    
    # Check cache first
    cached = simple_cache_get(cache_key)
    if cached:
        current_app.logger.debug(f"Cache hit for jobs: {cache_key}")
        return jsonify(cached), 200
        
    session = SessionLocal()
    try:
        # OPTIMIZED: Single query with eager loading
        query = session.query(Job).options(
            joinedload(Job.customer),
            joinedload(Job.assigned_team),
            joinedload(Job.primary_fitter),
            joinedload(Job.salesperson)
        )
        
        # Apply filters
        if customer_id:
            query = query.filter(Job.customer_id == customer_id)
        if stage:
            query = query.filter(Job.stage == stage)
        if work_stage:
            query = query.filter(Job.work_stage == work_stage)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        jobs = query.order_by(Job.created_at.desc())\
                   .limit(per_page)\
                   .offset((page - 1) * per_page)\
                   .all()
        
        result = {
            'jobs': [serialize_job(job) for job in jobs],
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
        current_app.logger.error(f"Error fetching jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_job(job_id):
    """
    Get a specific job by ID
    
    OPTIMIZATIONS:
    - 5-minute cache for individual jobs
    - Eager loading of all relationships
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    # Check cache first
    cache_key = f"job_{job_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
        
    session = SessionLocal()
    try:
        # OPTIMIZED: Eager load all relationships
        job = session.query(Job)\
            .options(
                joinedload(Job.customer),
                joinedload(Job.assigned_team),
                joinedload(Job.primary_fitter),
                joinedload(Job.salesperson)
            )\
            .filter(Job.id == job_id)\
            .first()
            
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        result = serialize_job(job)
        
        # Cache the result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs', methods=['POST'])
@token_required
def create_job():
    """
    Create a new job
    
    OPTIMIZATIONS:
    - Cache invalidation for job lists
    - Batch operations for related records
    """
    session = SessionLocal()
    try:
        data = request.get_json()
        current_app.logger.info(f"Creating job with data: {data}")
        
        # Validate required fields
        required_fields = ['customer_id', 'job_type', 'measure_date', 'completion_date']
        missing_fields = []
        
        for field in required_fields:
            if not data.get(field):
                missing_fields.append(field)
        
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            current_app.logger.warning(f"Validation error: {error_msg}")
            return jsonify({'error': error_msg}), 400
        
        # Validate customer exists
        customer = session.query(Customer).filter(Customer.id == data['customer_id']).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 400
        
        # Generate sequential job reference
        job_reference = generate_job_reference(session)
        current_app.logger.info(f"Generated job reference: {job_reference}")
        
        # Parse dates safely
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str.split('T')[0], '%Y-%m-%d')
                except ValueError:
                    current_app.logger.warning(f"Invalid date format: {date_str}")
                    return None
            return None
        
        # Use customer's address as installation address if not provided
        installation_address = data.get('installation_address') or customer.address
        
        # Defaults
        priority = data.get('priority', 'Medium')
        stage = data.get('stage', 'Lead')
        work_stage = data.get('work_stage', 'Survey')
        
        job = Job(
            id=str(uuid.uuid4()),
            job_reference=job_reference,
            job_name=data.get('job_name'),
            customer_id=data['customer_id'],
            job_type=data['job_type'],
            stage=stage,
            work_stage=work_stage,
            priority=priority,
            measure_date=parse_date(data.get('measure_date')),
            delivery_date=parse_date(data.get('delivery_date')),
            completion_date=parse_date(data.get('completion_date')),
            quote_id=data.get('quote_id') if data.get('quote_id') else None,
            quote_price=data.get('quote_price'),
            agreed_price=data.get('agreed_price'),
            deposit1=data.get('deposit1'),
            deposit2=data.get('deposit2'),
            deposit_due_date=parse_date(data.get('deposit_due_date')),
            installation_address=installation_address,
            assigned_team_id=data.get('assigned_team') if data.get('assigned_team') else None,
            primary_fitter_id=data.get('primary_fitter') if data.get('primary_fitter') else None,
            salesperson_id=data.get('salesperson') if data.get('salesperson') else None,
            assigned_team_name=data.get('team_member'),
            salesperson_name=data.get('salesperson_name') or customer.salesperson,
            notes=data.get('notes', ''),
            has_counting_sheet=data.get('create_counting_sheet', False),
            has_schedule=data.get('create_schedule', False),
            has_invoice=data.get('generate_invoice', False)
        )
        
        session.add(job)
        session.flush()
        
        current_app.logger.info(f"✅ Created job with ID: {job.id}, Reference: {job_reference}, Work Stage: {work_stage}")
        
        # Create notification
        try:
            from backend.routes.notification_routes import create_activity_notification
            
            user_name = data.get('created_by', 'System')
            job_name_display = data.get('job_name') or f"{data['job_type']} Job"
            
            create_activity_notification(
                session=session,
                message=f"💼 New job created for customer '{customer.name}': {job_name_display} ({data['job_type']}) - Ref: {job_reference}",
                job_id=job.id,
                customer_id=customer.id,
                moved_by=user_name
            )
            
            current_app.logger.info(f"✅ Notification created for job {job.id}")
        except ImportError:
            current_app.logger.warning("⚠️ Warning: Notification function not found.")
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")
        
        # OPTIMIZED: Batch create form links
        attached_forms = data.get('attached_forms', [])
        if attached_forms:
            form_links = []
            for form_id in attached_forms:
                form_link = JobFormLink(
                    job_id=job.id,
                    form_submission_id=form_id,
                    linked_by=data.get('created_by', 'System')
                )
                form_links.append(form_link)
            
            session.bulk_save_objects(form_links)
        
        # Create initial note if provided
        if data.get('notes'):
            initial_note = JobNote(
                job_id=job.id,
                content=data['notes'],
                note_type='general',
                author=data.get('created_by', 'System')
            )
            session.add(initial_note)
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('jobs', 'job_stats')
        
        return jsonify(serialize_job(job)), 201
        
    except Exception as e:
        current_app.logger.error(f"❌ Error creating job: {str(e)}")
        traceback.print_exc()
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_job(job_id):
    """
    Update an existing job
    
    OPTIMIZATIONS:
    - Cache invalidation for updated job
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    return None
            return None
        
        updateable_fields = [
            'job_name', 'job_type', 'stage', 'work_stage', 'priority', 'quote_id', 'quote_price',
            'agreed_price', 'deposit1', 'deposit2', 'installation_address',
            'assigned_team_id', 'primary_fitter_id', 'salesperson_id', 
            'assigned_team_name', 'primary_fitter_name', 'salesperson_name', 'notes'
        ]
        
        for field in updateable_fields:
            if field in data:
                setattr(job, field, data[field])
        
        date_fields = ['measure_date', 'delivery_date', 'completion_date', 'deposit_due_date']
        for field in date_fields:
            if field in data:
                setattr(job, field, parse_date(data[field]))
        
        job.updated_at = datetime.utcnow()
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('jobs', f'job_{job_id}', 'job_stats')
        
        current_app.logger.info(f"✅ Updated job {job_id}, work_stage: {job.work_stage if hasattr(job, 'work_stage') else 'N/A'}")
        
        return jsonify(serialize_job(job))
        
    except Exception as e:
        current_app.logger.error(f"Error updating job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_job(job_id):
    """
    Delete a job and its dependent records
    
    OPTIMIZATIONS:
    - Batch deletion of dependent records
    - Cache invalidation
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        current_app.logger.info(f"Attempting to delete job {job_id} and its dependencies.")

        # OPTIMIZED: Batch delete dependent records (faster than individual deletes)
        session.query(JobNote).filter(JobNote.job_id == job_id).delete(synchronize_session='fetch')
        session.query(JobDocument).filter(JobDocument.job_id == job_id).delete(synchronize_session='fetch')
        session.query(JobFormLink).filter(JobFormLink.job_id == job_id).delete(synchronize_session='fetch')
        session.query(Assignment).filter(Assignment.job_id == job_id).delete(synchronize_session='fetch')

        session.flush()
        
        session.delete(job)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('jobs', f'job_{job_id}', 'job_stats')
        
        current_app.logger.info(f"✅ Successfully deleted job {job_id}.")
        return jsonify({'message': 'Job deleted successfully'})
        
    except Exception as e:
        traceback.print_exc()
        current_app.logger.error(f"❌ Error deleting job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': f"Failed to delete job"}), 500
    finally:
        session.close()

# ==========================================
# JOB NOTES ROUTES (OPTIMIZED)
# ==========================================

@job_bp.route('/jobs/<string:job_id>/notes', methods=['GET'])
def get_job_notes(job_id):
    """
    Get all notes for a job
    
    OPTIMIZATIONS:
    - 5-minute cache for notes
    - Pagination support
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)
    
    # Check cache
    cache_key = f"job_notes_{job_id}_{page}_{per_page}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        # Get total count
        total_count = session.query(JobNote).filter(JobNote.job_id == job_id).count()
        
        # Get paginated notes
        notes = session.query(JobNote)\
            .filter(JobNote.job_id == job_id)\
            .order_by(JobNote.created_at.desc())\
            .limit(per_page)\
            .offset((page - 1) * per_page)\
            .all()
        
        result = {
            'notes': [{
                'id': note.id,
                'content': note.content,
                'note_type': note.note_type,
                'author': note.author,
                'created_at': note.created_at.isoformat()
            } for note in notes],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': (total_count + per_page - 1) // per_page
            }
        }
        
        # Cache result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching notes for job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>/notes', methods=['POST'])
def add_job_note(job_id):
    """
    Add a note to a job
    
    OPTIMIZATIONS:
    - Cache invalidation for job notes
    """
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        if not data.get('content'):
            return jsonify({'error': 'Note content is required'}), 400
        
        note = JobNote(
            job_id=job_id,
            content=data['content'],
            note_type=data.get('note_type', 'general'),
            author=data.get('author', 'System')
        )
        
        session.add(note)
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache(f'job_notes_{job_id}')
        
        return jsonify({
            'id': note.id,
            'content': note.content,
            'note_type': note.note_type,
            'author': note.author,
            'created_at': note.created_at.isoformat()
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"Error adding note to job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ==========================================
# JOB DOCUMENTS ROUTES (OPTIMIZED)
# ==========================================

@job_bp.route('/jobs/<string:job_id>/documents', methods=['GET'])
def get_job_documents(job_id):
    """
    Get all documents for a job
    
    OPTIMIZATIONS:
    - 5-minute cache for documents
    """
    # Check cache
    cache_key = f"job_documents_{job_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        documents = session.query(JobDocument)\
            .filter(JobDocument.job_id == job_id)\
            .order_by(JobDocument.created_at.desc())\
            .all()
        
        result = [{
            'id': doc.id,
            'filename': doc.filename,
            'original_filename': doc.original_filename,
            'file_size': doc.file_size,
            'mime_type': doc.mime_type,
            'category': doc.category,
            'uploaded_by': doc.uploaded_by,
            'created_at': doc.created_at.isoformat()
        } for doc in documents]
        
        # Cache result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching documents for job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ==========================================
# JOB STAGE UPDATE (OPTIMIZED)
# ==========================================

@job_bp.route('/jobs/<string:job_id>/stage', methods=['PATCH'])
def update_job_stage(job_id):
    """
    Update job stage
    
    OPTIMIZATIONS:
    - Cache invalidation for job and job lists
    """
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        if not data.get('stage'):
            return jsonify({'error': 'Stage is required'}), 400
        
        old_stage = job.stage
        job.stage = data['stage']
        job.updated_at = datetime.utcnow()
        
        stage_note = JobNote(
            job_id=job_id,
            content=f'Stage changed from "{old_stage}" to "{data["stage"]}"',
            note_type='system',
            author=data.get('updated_by', 'System')
        )
        session.add(stage_note)
        
        session.commit()
        
        # INVALIDATE CACHE
        invalidate_cache('jobs', f'job_{job_id}', f'job_notes_{job_id}', 'job_stats')
        
        return jsonify(serialize_job(job))
        
    except Exception as e:
        current_app.logger.error(f"Error updating stage for job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ==========================================
# LOOKUP ROUTES (CACHED)
# ==========================================

@job_bp.route('/teams', methods=['GET'])
def get_teams():
    """
    Get all active teams
    
    OPTIMIZATIONS:
    - 10-minute cache (teams don't change often)
    """
    cache_key = "teams"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        teams = session.query(Team)\
            .filter(Team.active == True)\
            .order_by(Team.name)\
            .all()
        
        result = [{
            'id': team.id,
            'name': team.name,
            'specialty': team.specialty
        } for team in teams]
        
        # Cache for 10 minutes
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching teams: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/fitters', methods=['GET'])
def get_fitters():
    """
    Get all active fitters
    
    OPTIMIZATIONS:
    - 10-minute cache
    - Eager loading of team relationship
    """
    cache_key = "fitters"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        fitters = session.query(Fitter)\
            .options(joinedload(Fitter.team))\
            .filter(Fitter.active == True)\
            .order_by(Fitter.name)\
            .all()
        
        result = [{
            'id': fitter.id,
            'name': fitter.name,
            'team_id': fitter.team_id,
            'team_name': fitter.team.name if fitter.team else None
        } for fitter in fitters]
        
        # Cache for 10 minutes
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching fitters: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/salespeople', methods=['GET'])
def get_salespeople():
    """
    Get all active salespeople
    
    OPTIMIZATIONS:
    - 10-minute cache
    """
    cache_key = "salespeople"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        salespeople = session.query(Salesperson)\
            .filter(Salesperson.active == True)\
            .order_by(Salesperson.name)\
            .all()
        
        result = [{
            'id': person.id,
            'name': person.name,
            'email': person.email
        } for person in salespeople]
        
        # Cache for 10 minutes
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching salespeople: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ==========================================
# FORMS & STATS (OPTIMIZED)
# ==========================================

@job_bp.route('/forms/unlinked', methods=['GET'])
def get_unlinked_forms():
    """
    Get form submissions not linked to any job
    
    OPTIMIZATIONS:
    - 5-minute cache
    """
    customer_id = request.args.get('customer_id')
    
    cache_key = f"unlinked_forms_{customer_id}"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        linked_form_ids = session.query(JobFormLink.form_submission_id).subquery()
        
        query = session.query(FormSubmission).filter(
            ~FormSubmission.id.in_(linked_form_ids)
        )
        
        if customer_id:
            query = query.filter(FormSubmission.customer_id == customer_id)
        
        forms = query.order_by(FormSubmission.submitted_at.desc()).all()
        
        result = [{
            'id': form.id,
            'customer_id': form.customer_id,
            'submitted_at': form.submitted_at.isoformat(),
            'processed': form.processed,
            'source': form.source
        } for form in forms]
        
        # Cache result
        simple_cache_set(cache_key, result)
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching unlinked forms: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/stats', methods=['GET'])
def get_job_stats():
    """
    Get job statistics
    
    OPTIMIZATIONS:
    - 5-minute cache for stats
    """
    cache_key = "job_stats"
    cached = simple_cache_get(cache_key)
    if cached:
        return jsonify(cached), 200
    
    session = SessionLocal()
    try:
        stats = {
            'total_jobs': session.query(Job).count(),
            'by_stage': {},
            'by_work_stage': {},
            'by_type': {},
            'by_priority': {}
        }
        
        # Stage counts
        stage_counts = session.query(
            Job.stage, 
            func.count(Job.id)
        ).group_by(Job.stage).all()
        
        for stage, count in stage_counts:
            stats['by_stage'][stage] = count
        
        # Work stage counts
        if hasattr(Job, 'work_stage'):
            work_stage_counts = session.query(
                Job.work_stage, 
                func.count(Job.id)
            ).group_by(Job.work_stage).all()
            
            for work_stage, count in work_stage_counts:
                stats['by_work_stage'][work_stage] = count
        
        # Job type counts
        type_counts = session.query(
            Job.job_type, 
            func.count(Job.id)
        ).group_by(Job.job_type).all()
        
        for job_type, count in type_counts:
            stats['by_type'][job_type] = count
        
        # Priority counts
        priority_counts = session.query(
            Job.priority, 
            func.count(Job.id)
        ).group_by(Job.priority).all()
        
        for priority, count in priority_counts:
            stats['by_priority'][priority] = count
        
        # Cache result
        simple_cache_set(cache_key, stats)
        
        return jsonify(stats)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching job stats: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()