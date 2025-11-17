import os
from typing import Optional
from flask import Blueprint, request, jsonify, current_app
import json
from datetime import datetime, date # Import date separately for explicit use
from ..db import SessionLocal, Base, engine
from ..models import (
    User, Assignment, Customer, CustomerFormData, Fitter, Job,
    ProductionNotification, Quotation, QuotationItem, Project
)
from .auth_helpers import token_required
from sqlalchemy.exc import OperationalError
from sqlalchemy import func
from sqlalchemy.orm import selectinload

db_bp = Blueprint('database', __name__)

# Helper function to get current user's email safely
def get_current_user_email(data=None):
    if hasattr(request, 'current_user') and hasattr(request.current_user, 'email'):
        return request.current_user.email
    # Fallback to 'System' or data.get('created_by') from post body if needed
    return data.get('created_by', 'System') if isinstance(data, dict) else 'System'


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
            return jsonify({'id': user.id, 'message': 'User created successfully'}), 201
        
        # FIXED: Uses session.query
        users = session.query(User).all()
        return jsonify([u.to_dict() for u in users])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling users: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ------------------ CUSTOMERS ------------------

@db_bp.route('/customers', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            customer = Customer(
                name=data.get('name', ''),
                # Ensure date parsing works correctly
                date_of_measure=datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date() if data.get('date_of_measure') else None,
                address=data.get('address', ''),
                phone=data.get('phone', ''),
                email=data.get('email', ''),
                contact_made=data.get('contact_made', 'Unknown'),
                preferred_contact_method=data.get('preferred_contact_method'),
                marketing_opt_in=data.get('marketing_opt_in', False),
                notes=data.get('notes', ''),
                stage=data.get('stage', 'Lead'),
                created_by=get_current_user_email(data),
                status=data.get('status', 'Active'),
                project_types=data.get('project_types', []),
                salesperson=data.get('salesperson'),
            )
            session.add(customer)
            session.commit()
            return jsonify({'id': customer.id, 'message': 'Customer created successfully'}), 201

        # GET all customers (FIXED: Uses session.query)
        customers = session.query(Customer).order_by(Customer.created_at.desc()).all()
        
        # FIX: Explicitly include 'postcode' in the customer list serialization
        customer_list = []
        for c in customers:
            customer_dict = c.to_dict(include_projects=False)
            # Assuming the postcode property exists on the Customer model instance
            customer_dict['postcode'] = getattr(c, 'postcode', None) or getattr(c, 'post_code', None) or None
            customer_list.append(customer_dict)

        return jsonify(customer_list)

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /customers: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/customers/<string:customer_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_customer(customer_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        # FIXED: Uses session.query
        customer = session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        if request.method == 'GET':
            # FIXED: Uses session.query for CustomerFormData
            form_entries = session.query(CustomerFormData).filter_by(customer_id=customer.id).order_by(CustomerFormData.submitted_at.desc()).all()
            form_submissions = []
            for f in form_entries:
                try:
                    # Robust handling of form data and dates
                    parsed_data = json.loads(f.form_data) if getattr(f, 'form_data', None) else {}
                    form_submissions.append({
                        "id": f.id,
                        "token_used": f.token_used,
                        "submitted_at": f.submitted_at.isoformat() if f.submitted_at else None,
                        "form_data": parsed_data,
                        "project_id": getattr(f, 'project_id', None),
                        "approval_status": getattr(f, 'approval_status', 'pending'),
                        "approved_by": f.approved_by,
                        "approval_date": f.approval_date.isoformat() if f.approval_date else None
                    })
                except Exception as inner_e:
                    current_app.logger.error(f"Error processing form submission {getattr(f, 'id', 'unknown')}: {inner_e}")
            
            customer_data = customer.to_dict(include_projects=True)
            customer_data['form_submissions'] = form_submissions
            return jsonify(customer_data)

        elif request.method == 'PUT':
            data = request.json
            # ... (Update logic for customer attributes) ...
            customer.name = data.get('name', customer.name)
            customer.address = data.get('address', customer.address)
            customer.phone = data.get('phone', customer.phone)
            customer.email = data.get('email', customer.email)
            customer.contact_made = data.get('contact_made', customer.contact_made)
            customer.preferred_contact_method = data.get('preferred_contact_method', customer.preferred_contact_method)
            customer.marketing_opt_in = data.get('marketing_opt_in', customer.marketing_opt_in)
            customer.notes = data.get('notes', customer.notes)
            customer.updated_by = get_current_user_email(data)
            customer.salesperson = data.get('salesperson', customer.salesperson)
            customer.project_types = data.get('project_types', customer.project_types)
            if data.get('date_of_measure'):
                customer.date_of_measure = datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date()
            if 'stage' in data:
                customer.stage = data.get('stage', customer.stage)
            
            # Assuming this method exists on the model
            if 'address' in data:
                customer.postcode = customer.extract_postcode_from_address()
                
            session.commit()
            return jsonify({'message': 'Customer updated successfully'})

        elif request.method == 'DELETE':
            session.delete(customer)
            session.commit()
            return jsonify({'message': 'Customer deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling customer {customer_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ------------------ CUSTOMER STAGE ------------------

PIPELINE_STAGE_ORDER = [
    "Lead", "Survey", "Design", "Quote",
    "Accepted", "OnHold", "Ordered",
    "Production", "Delivery", "Installation",
    "Complete", "Remedial", "Cancelled"
]


def _extract_stage_from_payload(data: dict) -> Optional[str]:
    """Best-effort extraction of the intended pipeline stage from the request payload.

    Historically the frontend sent a simple string field called ``stage`` but
    some UI changes started providing additional metadata (for example
    ``targetStage`` or destination column indexes).  When the UI bug reported in
    the pipeline manifested, the backend was only reading the original ``stage``
    field which, due to an indexing issue on the client, contained the stage of
    the previous column (e.g. ``Design`` instead of ``Quote``).  By inspecting the
    extended payload we can recover the actual intended target stage and keep the
    server as the source of truth.

    The helper considers a number of common shapes:

    * Plain string values (``"Quote"``).
    * Objects produced by select components (``{"label": "Quote", "value": "Quote"}``).
    * Alternative keys such as ``targetStage``/``newStage``/``destinationStage``.
    * Column indexes where the client only provides the destination column id.

    The first recognised stage that matches the canonical ``PIPELINE_STAGE_ORDER``
    list is returned.
    """

    if not isinstance(data, dict):
        return None

    candidates = []

    def _add_candidate(value):
        if value is None:
            return
        if isinstance(value, dict):
            # Select inputs frequently send {label, value}
            for key in ("value", "label", "stage"):
                inner = value.get(key)
                if isinstance(inner, str):
                    candidates.append(inner.strip())
        elif isinstance(value, (list, tuple)):
            for item in value:
                _add_candidate(item)
        elif isinstance(value, str):
            candidates.append(value.strip())
        elif isinstance(value, (int, float)):
            idx = int(value)
            if 0 <= idx < len(PIPELINE_STAGE_ORDER):
                candidates.append(PIPELINE_STAGE_ORDER[idx])

    # Primary field used historically
    _add_candidate(data.get('stage'))

    # Alternative explicit keys the frontend may send
    for key in (
        'target_stage', 'targetStage',
        'new_stage', 'newStage',
        'destination_stage', 'destinationStage',
        'pipeline_stage', 'pipelineStage',
        'column_stage', 'columnStage'
    ):
        _add_candidate(data.get(key))

    # Numeric column / index hints
    for key in (
        'stage_index', 'stageIndex',
        'target_index', 'targetIndex',
        'destination_index', 'destinationIndex',
        'column_index', 'columnIndex'
    ):
        _add_candidate(data.get(key))

    # Return the first recognised stage
    seen = set()
    for value in candidates:
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate in PIPELINE_STAGE_ORDER:
            return candidate

    return None

@db_bp.route('/customers/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage(customer_id):
    """Update customer stage - ENHANCED VERSION with all important stage notifications"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Get the customer
        customer = session.query(Customer).filter_by(id=customer_id).first()
        if not customer:
            current_app.logger.error(f"❌ Customer {customer_id} not found")
            return jsonify({'error': 'Customer not found'}), 404

        # Extract data
        data = request.json
        updated_by_user = get_current_user_email(data)
        new_stage = _extract_stage_from_payload(data)
        reason = data.get('reason', 'Stage updated via drag and drop')
        
        current_app.logger.info(f"🔄 Stage update request for customer {customer_id}: {customer.stage} → {new_stage}")
        
        # Validate stage
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': f'Invalid stage: {new_stage}'}), 400

        old_stage = customer.stage
        
        # If stage hasn't changed, return early
        if old_stage == new_stage:
            current_app.logger.info(f"ℹ️ Customer {customer_id} already in stage {new_stage}")
            return jsonify({
                'message': 'Stage not changed', 
                'stage_updated': False,
                'customer_id': customer.id,
                'new_stage': new_stage,
                'old_stage': old_stage
            }), 200

        # Update customer stage
        customer.stage = new_stage
        customer.updated_by = updated_by_user
        customer.updated_at = datetime.utcnow()
        
        # Add audit note
        note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage}. Reason: {reason}"
        customer.notes = (customer.notes or '') + note_entry
        
        # ✅ ENHANCED: Create notifications for multiple important stages
        notification_created = False
        
        try:
            from backend.routes.notification_routes import create_activity_notification
            
            linked_job = session.query(Job).filter_by(customer_id=customer.id).first()
            
            # Define stage-specific notification messages
            stage_notifications = {
                'Accepted': {
                    'emoji': '✅',
                    'message': f"Customer '{customer.name}' accepted the quote and moved to Accepted stage",
                    'create': True
                },
                'Production': {
                    'emoji': '🏭',
                    'message': f"Customer '{customer.name}' is now in Production - Manufacturing started",
                    'create': True
                },
                'Delivery': {
                    'emoji': '🚚',
                    'message': f"🚚 Customer '{customer.name}' is ready for delivery! Project completed and awaiting delivery",
                    'create': True
                },
                'Installation': {
                    'emoji': '🔧',
                    'message': f"Installation scheduled for customer '{customer.name}'",
                    'create': True
                },
                'Complete': {
                    'emoji': '🎉',
                    'message': f"🎉 Project COMPLETED for customer '{customer.name}'! Job finished successfully",
                    'create': True
                }
            }
            
            # Create notification if it's an important stage
            if new_stage in stage_notifications:
                stage_config = stage_notifications[new_stage]
                
                create_activity_notification(
                    session=session,
                    job_id=linked_job.id if linked_job else None,
                    customer_id=customer.id,
                    message=stage_config['message'],
                    moved_by=updated_by_user
                )
                notification_created = True
                current_app.logger.info(f"📢 Created {new_stage} notification for customer {customer_id}")
                
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")
        
        # Commit the transaction
        session.commit()
        
        current_app.logger.info(f"✅ Customer {customer.id} stage updated from {old_stage} to {new_stage}")
        
        return jsonify({
            'message': 'Stage updated successfully',
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': new_stage,
            'stage_updated': True,
            'notification_sent': notification_created
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer {customer_id} stage: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ------------------ JOBS ------------------

@db_bp.route('/jobs', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_jobs():
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
                primary_fitter_name=data.get('primary_fitter_name')
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
            
            return jsonify({'id': job.id, 'message': 'Job created successfully'}), 201
        
        # GET all jobs (FIXED: Uses session.query)
        jobs = session.query(Job).order_by(Job.created_at.desc()).all()
        return jsonify([
            {
                'id': j.id,
                'customer_id': j.customer_id,
                'job_reference': j.job_reference,
                'job_name': j.job_name,
                'job_type': j.job_type,
                'stage': j.stage,
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
            for j in jobs
        ])
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling jobs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/jobs/<string:job_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_job(job_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # FIXED: Uses session.query
        job = session.query(Job).filter_by(id=job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        if request.method == 'GET':
            return jsonify({
                'id': job.id,
                'customer_id': job.customer_id,
                'job_reference': job.job_reference,
                'job_name': job.job_name,
                'job_type': job.job_type,
                'stage': job.stage,
                'priority': job.priority,
                'quote_price': float(job.quote_price) if job.quote_price else None,
                'agreed_price': float(job.agreed_price) if job.agreed_price else None,
                'sold_amount': float(job.sold_amount) if job.sold_amount else None,
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
            
            return jsonify({'message': 'Job updated successfully'})
        
        elif request.method == 'DELETE':
            customer_id = job.customer_id
            session.delete(job)
            session.commit()
            
            # Re-fetch customer to update stage after job deletion (FIXED: Uses session.query)
            customer = session.query(Customer).filter_by(id=customer_id).first()
            if customer:
                # Update customer stage based on remaining jobs/projects if model supports it
                pass 
            
            return jsonify({'message': 'Job deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling single job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/jobs/<string:job_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_job_stage(job_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    session = SessionLocal()
    try:
        job = session.query(Job).filter_by(id=job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        data = request.json
        updated_by_user = get_current_user_email(data)
        new_stage = _extract_stage_from_payload(data)
        reason = data.get('reason', 'Stage updated via drag and drop')
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
            return jsonify({'error': 'Invalid stage'}), 400

        old_stage = job.stage
        if old_stage == new_stage:
            return jsonify({
                'message': 'Stage not changed',
                'job_id': job.id,
                'new_stage': new_stage
            }), 200

        # Update job stage
        job.stage = new_stage
        job.updated_at = datetime.utcnow()
        note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage} by {updated_by_user}. Reason: {reason}"
        job.notes = (job.notes or '') + note_entry

        # Add notification if moving to Accepted
        if new_stage == 'Accepted':
            notification = ProductionNotification(
                job_id=job.id,
                customer_id=job.customer_id,
                message=f"Job '{job.job_name or job.job_reference or job.id}' moved to Accepted",
                moved_by=updated_by_user
            )
            session.add(notification)

        # Simplified customer sync logic
        customer = session.query(Customer).filter_by(id=job.customer_id).first()
        if customer:
            job_count = session.query(Job).filter_by(customer_id=job.customer_id).count()
            project_count = session.query(Project).filter_by(customer_id=job.customer_id).count()
            total_linked = job_count + project_count
            
            if total_linked <= 1 and customer.stage != new_stage:
                customer.stage = new_stage
                customer.updated_at = datetime.utcnow()

        # 🔑 CRITICAL FIX: Flush, commit, then refresh
        session.flush()
        session.commit()
        session.refresh(job)

        current_app.logger.info(f"✅ Job {job.id} stage updated from {old_stage} to {new_stage}")

        return jsonify({
            'message': 'Stage updated successfully',
            'job_id': job.id,
            'old_stage': old_stage,
            'new_stage': new_stage
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating job stage: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ------------------ PIPELINE ------------------

@db_bp.route('/pipeline', methods=['GET', 'OPTIONS'])
@token_required
def get_pipeline_data():
    """Get all pipeline items - FIXED VERSION"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # 🔑 REMOVED: session.expire_all() - This was causing stale data issues
        
        # Eagerly load relationships to avoid lazy loading issues
        customers = session.query(Customer).options(
            selectinload(Customer.jobs),
            selectinload(Customer.projects)
        ).all()

        pipeline_items = []

        for customer in customers:
            # Relationships are now eagerly loaded
            customer_jobs = customer.jobs 
            customer_projects = customer.projects 
            has_linked_entity = bool(customer_jobs or customer_projects)

            # 1. Generate a card for *every* Job
            for job in customer_jobs:
                pipeline_items.append({
                    'id': f'job-{job.id}',
                    'type': 'job',
                    'customer': customer.to_dict(include_projects=False),
                    'stage': job.stage,  # Job's stage takes precedence
                    'job': {
                        'id': job.id,
                        'customer_id': job.customer_id,
                        'job_reference': job.job_reference,
                        'job_name': job.job_name,
                        'job_type': job.job_type,
                        'stage': job.stage,
                        'priority': job.priority,
                        'quote_price': float(job.quote_price) if job.quote_price else None,
                        'agreed_price': float(job.agreed_price) if job.agreed_price else None,
                        'sold_amount': float(job.sold_amount) if job.sold_amount else None,
                        'deposit1': float(job.deposit1) if job.deposit1 else None,
                        'deposit2': float(job.deposit2) if job.deposit2 else None,
                        'deposit1_paid': False,
                        'deposit2_paid': False,
                        'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
                        'measure_date': job.measure_date.isoformat() if job.measure_date else None,
                        'completion_date': job.completion_date.isoformat() if job.completion_date else None,
                        'installation_address': job.installation_address,
                        'salesperson_name': job.salesperson_name,
                        'assigned_team_name': job.assigned_team_name,
                        'primary_fitter_name': job.primary_fitter_name,
                        'created_at': job.created_at.isoformat() if job.created_at else None,
                        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
                    }
                })

            # 2. Generate a card for *every* Project
            for project in customer_projects:
                pipeline_items.append({
                    'id': f'project-{project.id}',
                    'type': 'project',
                    'customer': customer.to_dict(include_projects=False),
                    'stage': project.stage,  # Project's stage takes precedence
                    'job': {
                        'id': project.id,
                        'customer_id': customer.id,
                        'job_reference': f"PROJ-{getattr(project, 'project_name', 'N/A')}", 
                        'job_name': getattr(project, 'project_name', 'N/A'), 
                        'job_type': getattr(project, 'project_type', 'Unknown'), 
                        'stage': project.stage,
                        'priority': 'Medium',
                        'quote_price': None,
                        'agreed_price': None,
                        'sold_amount': None,
                        'deposit1': None,
                        'deposit2': None,
                        'deposit1_paid': False,
                        'deposit2_paid': False,
                        'delivery_date': None,
                        'measure_date': getattr(project, 'date_of_measure', None).isoformat() if getattr(project, 'date_of_measure', None) else None,
                        'installation_address': customer.address,
                        'salesperson_name': customer.salesperson,
                        'created_at': project.created_at.isoformat() if project.created_at else None,
                        'updated_at': project.updated_at.isoformat() if project.updated_at else None,
                    }
                })

            # 3. Case: Customer is a pure Lead (no jobs or projects)
            if not has_linked_entity:
                pipeline_items.append({
                    'id': f'customer-{customer.id}',
                    'type': 'customer',
                    'stage': customer.stage,  # Customer's stage
                    'customer': customer.to_dict(include_projects=False)
                })
        
        current_app.logger.info(f"📊 Pipeline data fetched: {len(pipeline_items)} items")
        return jsonify(pipeline_items)
        
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching pipeline: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ------------------ PROJECTS ROUTES (New/Updated) ------------------

@db_bp.route('/projects/<string:project_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@token_required
def handle_single_project(project_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        if request.method == 'GET':
            return jsonify(project.to_dict())

        elif request.method == 'PUT':
            data = request.json
            old_stage = project.stage

            # Update attributes (ensuring 'stage' is included for drag-and-drop fix)
            project.project_name = data.get('project_name', project.project_name)
            project.project_type = data.get('project_type', project.project_type)
            project.stage = data.get('stage', project.stage) # CRITICAL: Update stage here
            project.notes = data.get('notes', project.notes)
            project.updated_by = get_current_user_email(data)
            project.updated_at = datetime.utcnow()

            if 'date_of_measure' in data and data['date_of_measure']:
                if isinstance(data['date_of_measure'], str):
                    project.date_of_measure = datetime.strptime(data['date_of_measure'], '%Y-%m-%d').date()
                elif isinstance(data['date_of_measure'], date):
                    project.date_of_measure = data['date_of_measure']
            
            # Optionally sync customer stage if this is the only linked entity
            customer = project.customer
            new_stage = project.stage
            if customer:
                # Check for other jobs/projects linked to the customer
                job_count = session.query(Job).filter_by(customer_id=customer.id).count()
                # Exclude the current project from the count of linked projects
                total_linked = job_count + len([p for p in customer.projects if p.id != project.id])
                
                if total_linked == 0 and customer.stage != new_stage:
                    customer.stage = new_stage
                    customer.updated_at = datetime.utcnow()
                    note_entry_cust = f"\n[{datetime.utcnow().isoformat()}] Stage synced from {old_stage} to {new_stage} by {project.updated_by}. Reason: Linked project moved."
                    customer.notes = (customer.notes or '') + note_entry_cust
                    session.add(customer)

            # ✅ FIX: Commit BEFORE refresh (Ensures persistence)
            session.commit()
            
            # 🔑 FIX: Refresh the object to ensure the latest state is captured 
            session.refresh(project)
            
            return jsonify({'message': 'Project updated successfully', 'id': project.id, 'new_stage': project.stage}) # 🔑 FIX: Use project.stage (refreshed value)

        elif request.method == 'DELETE':
            session.delete(project)
            session.commit()
            return jsonify({'message': 'Project deleted successfully'})

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling single project {project_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@db_bp.route('/projects/<string:project_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_project_stage(project_id):
    """Update project stage - ENHANCED VERSION with all important stage notifications"""
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
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        if new_stage not in PIPELINE_STAGE_ORDER:
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
        note_entry = f"\n[{datetime.utcnow().isoformat()}] Stage changed from {old_stage} to {new_stage} by {updated_by_user}. Reason: {reason}"
        project.notes = (project.notes or '') + note_entry

        # ✅ ENHANCED: Create notifications for all important stages
        try:
            from backend.routes.notification_routes import create_activity_notification
            
            project_display_name = project.project_name or f"Project #{project.id[:8]}"
            customer_name = project.customer.name if project.customer else "Unknown Customer"
            
            # Define stage-specific notification messages for projects
            stage_notifications = {
                'Accepted': {
                    'emoji': '✅',
                    'message': f"Project '{project_display_name}' for {customer_name} has been accepted",
                },
                'Production': {
                    'emoji': '🏭',
                    'message': f"Project '{project_display_name}' for {customer_name} is now in Production",
                },
                'Delivery': {
                    'emoji': '🚚',
                    'message': f"🚚 Project '{project_display_name}' for {customer_name} is ready for delivery!",
                },
                'Installation': {
                    'emoji': '🔧',
                    'message': f"Installation started for project '{project_display_name}' - {customer_name}",
                },
                'Complete': {
                    'emoji': '🎉',
                    'message': f"🎉 Project '{project_display_name}' for {customer_name} has been COMPLETED!",
                }
            }
            
            # Create notification if it's an important stage
            if new_stage in stage_notifications:
                stage_config = stage_notifications[new_stage]
                
                create_activity_notification(
                    session=session,
                    customer_id=project.customer_id,
                    message=stage_config['message'],
                    moved_by=updated_by_user
                )
                current_app.logger.info(f"📢 Created {new_stage} notification for project {project.id}")
                
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")

        session.flush()
        session.commit()
        session.refresh(project)

        # Simplified customer sync
        customer = project.customer
        if customer:
            job_count = session.query(Job).filter_by(customer_id=customer.id).count()
            other_projects = [p for p in customer.projects if p.id != project.id]
            total_linked = job_count + len(other_projects)

            if total_linked == 0 and customer.stage != new_stage:
                customer.stage = new_stage
                customer.updated_at = datetime.utcnow()

        session.commit()

        return jsonify({
            'message': 'Stage updated successfully',
            'project_id': project.id,
            'old_stage': old_stage,
            'new_stage': new_stage
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating project stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ------------------ ASSIGNMENTS ------------------

@db_bp.route('/assignments', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_assignments():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            assignment = Assignment(
                title=data.get('title', ''),
                description=data.get('description', ''),
                assigned_to=data.get('assigned_to'),
                due_date=datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get('due_date') else None,
                created_by=get_current_user_email(data)
            )
            session.add(assignment)
            session.commit()
            return jsonify({'id': assignment.id, 'message': 'Assignment created successfully'}), 201

        # FIXED: Uses session.query
        assignments = session.query(Assignment).order_by(Assignment.created_at.desc()).all()
        return jsonify([a.to_dict() for a in assignments])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /assignments: {e}")
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