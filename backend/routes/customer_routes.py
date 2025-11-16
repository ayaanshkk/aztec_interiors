from flask import Blueprint, request, jsonify
from ..models import Customer, Project, CustomerFormData, User, Job, DrawingDocument, FormDocument, ProductionNotification
from functools import wraps
from flask import current_app
import uuid
from datetime import datetime
import json

# 👈 NEW IMPORT: Required for all database write operations
from ..db import SessionLocal 


customer_bp = Blueprint('customers', __name__)

# Define stage hierarchy for determining "most advanced" stage
STAGE_HIERARCHY = {
    "Lead": 0,
    "Survey": 1,
    "Design": 2,
    "Quote": 3,
    "Accepted": 4,
    "OnHold": 5,
    "Ordered": 6,
    "Production": 7,
    "Delivery": 8,
    "Installation": 9,
    "Complete": 10,
    "Remedial": 11,
    "Cancelled": 12
}

def get_most_advanced_stage(stages):
    """Given a list of stage strings, return the most advanced one"""
    if not stages:
        return "Lead"
    
    # Filter out None values and get hierarchy values
    valid_stages = [s for s in stages if s and s in STAGE_HIERARCHY]
    if not valid_stages:
        return "Lead"
    
    # Return the stage with highest hierarchy value
    return max(valid_stages, key=lambda s: STAGE_HIERARCHY.get(s, 0))


# Token authentication decorator (left unchanged as it relies on User.verify_jwt_token)
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)
        
        token = None
        
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            current_user = User.verify_jwt_token(token, current_app.config['SECRET_KEY'])
            if not current_user:
                return jsonify({'error': 'Token is invalid or expired'}), 401
            
            request.current_user = current_user
            
        except Exception as e:
            return jsonify({'error': 'Token verification failed'}), 401
        
        return f(*args, **kwargs)
    
    return decorated


# ==========================================
# CUSTOMER ENDPOINTS
# ==========================================

@customer_bp.route('/customers', methods=['GET', 'OPTIONS'])
@token_required
def get_customers():
    """Get all customers with their project counts, form counts, drawing counts, and MOST ADVANCED STAGE."""
    
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        # Define stage order (higher number = more advanced)
        stage_order = {
            'Lead': 1,
            'Qualified': 2,
            'Quote Sent': 3,
            'Negotiation': 4,
            'Accepted': 5,
            'Deposit Paid': 6,
            'In Production': 7,
            'Ready for Delivery': 8,
            'Delivered': 9,
            'Installed': 10,
            'Completed': 11,
            'Lost': 0  # Lost is not really a progression, so we keep it at 0
        }
        
        # Create a SQL CASE statement for stage ordering
        stage_order_case = case(
            *[(Project.stage == stage, order) for stage, order in stage_order.items()],
            else_=0
        )
        
        # Get all customers with aggregated data
        customers_query = db.session.query(
            Customer,
            func.count(func.distinct(Project.id)).label('project_count'),
            func.count(func.distinct(CustomerFormData.id)).label('form_count'),
            func.count(func.distinct(DrawingDocument.id)).label('drawing_count'),
            func.count(func.distinct(FormDocument.id)).label('form_document_count'),
            func.max(stage_order_case).label('max_stage_order')
        ).outerjoin(
            Project, Customer.id == Project.customer_id
        ).outerjoin(
            CustomerFormData, Customer.id == CustomerFormData.customer_id
        ).outerjoin(
            DrawingDocument, Customer.id == DrawingDocument.customer_id
        ).outerjoin(
            FormDocument, Customer.id == FormDocument.customer_id
        ).group_by(Customer.id).all()
        
        # Reverse lookup for stage order
        order_to_stage = {v: k for k, v in stage_order.items()}
        
        customers_list = []
        for customer, project_count, form_count, drawing_count, form_document_count, max_stage_order in customers_query:
            # Determine the most advanced stage
            if project_count > 0:
                # Customer has projects, use the most advanced stage
                most_advanced_stage = order_to_stage.get(max_stage_order, 'Lead')
            else:
                # No projects, customer is in Lead stage
                most_advanced_stage = 'Lead'
            
            customer_data = {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'email': customer.email,
                'address': customer.address,
                'city': customer.city,
                'postcode': customer.postcode,
                'source': customer.source,
                'stage': most_advanced_stage,  # Most advanced stage across all projects
                'project_count': project_count,  # Total number of projects
                'form_count': form_count,
                'drawing_count': drawing_count,
                'form_document_count': form_document_count,
                'notes': customer.notes,
                'created_at': customer.created_at.isoformat() if customer.created_at else None,
                'updated_at': customer.updated_at.isoformat() if customer.updated_at else None
            }
            
            customers_list.append(customer_data)
        
        # Sort by most recently updated
        customers_list.sort(key=lambda x: x['updated_at'] if x['updated_at'] else '', reverse=True)
        
        return jsonify(customers_list), 200
        
    except Exception as e:
        print(f"Error fetching customers: {str(e)}")
        return jsonify({'error': str(e)}), 500


@customer_bp.route('/customers', methods=['POST', 'OPTIONS'])
@token_required
def create_customer():
    """Create a new customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        if not data.get('address'):
            return jsonify({'error': 'Address is required'}), 400
        
        # Create new customer
        new_customer = Customer(
            id=str(uuid.uuid4()),
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email', ''),
            address=data.get('address'),
            postcode=data.get('postcode', ''),
            salesperson=data.get('salesperson', ''),
            marketing_opt_in=data.get('marketing_opt_in', False),
            notes=data.get('notes', ''),
            contact_made='No',
            preferred_contact_method='Phone',
            created_at=datetime.utcnow(),
            created_by=request.current_user.id
        )
        
        session.add(new_customer)
        session.commit() # 👈 Commit transaction
        
        current_app.logger.info(f"Customer {new_customer.id} created by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer created successfully',
            'customer': new_customer.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error creating customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session


@customer_bp.route('/customers/<string:customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(customer_id):
    """Get a single customer by ID with all their projects"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        customer = Customer.query.get_or_404(customer_id)
        
        # Check access permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != request.current_user.id and customer.salesperson != request.current_user.get_full_name():
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        elif request.current_user.role == 'Staff':
            if customer.created_by != request.current_user.id and customer.salesperson != request.current_user.get_full_name():
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        
        # Return customer with all projects
        return jsonify(customer.to_dict(include_projects=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500


@customer_bp.route('/customers/<string:customer_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(customer_id):
    """Update a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        # Use session.get() to attach object to the transaction
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != session.get(User, request.current_user.id).id and customer.salesperson != session.get(User, request.current_user.id).full_name:
                return jsonify({'error': 'You do not have permission to edit this customer'}), 403
        
        data = request.get_json()
        
        # Update customer fields
        if 'name' in data:
            customer.name = data['name']
        if 'phone' in data:
            customer.phone = data['phone']
        if 'email' in data:
            customer.email = data['email']
        if 'address' in data:
            customer.address = data['address']
        if 'postcode' in data:
            customer.postcode = data['postcode']
        if 'contact_made' in data:
            customer.contact_made = data['contact_made']
        if 'preferred_contact_method' in data:
            customer.preferred_contact_method = data['preferred_contact_method']
        if 'marketing_opt_in' in data:
            customer.marketing_opt_in = data['marketing_opt_in']
        if 'notes' in data:
            customer.notes = data['notes']
        if 'salesperson' in data:
            customer.salesperson = data['salesperson']
        
        customer.updated_by = request.current_user.id
        customer.updated_at = datetime.utcnow()
        
        session.commit() # 👈 Commit transaction
        
        # Re-fetch the dictionary representation after commit
        customer_dict = customer.to_dict(include_projects=True)
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully',
            'customer': customer_dict
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error updating customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session


@customer_bp.route('/customers/<string:customer_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(customer_id):
    """Delete a customer (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        # Only Manager and HR can delete
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete customers'}), 403
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check if customer has projects - warn if they do
        if customer.projects:
            return jsonify({
                'error': f'Cannot delete customer with {len(customer.projects)} project(s). Delete projects first.'
            }), 400
        
        session.delete(customer)
        session.commit() # 👈 Commit deletion
        
        current_app.logger.info(f"Customer {customer_id} deleted by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error deleting customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to delete customer'}), 500
    finally:
        session.close() # 👈 Close session


# ==========================================
# PROJECT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/projects', methods=['GET'])
@token_required
def get_customer_projects(customer_id):
    """Get all projects for a specific customer with full details."""
    
    try:
        customer = Customer.query.get(customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all projects for this customer
        projects = Project.query.filter_by(customer_id=customer_id).all()
        
        projects_list = []
        for project in projects:
            project_data = {
                'id': project.id,
                'project_name': project.project_name,
                'stage': project.stage,
                'quote_price': float(project.quote_price) if project.quote_price else None,
                'deposit_amount': float(project.deposit_amount) if project.deposit_amount else None,
                'balance_due': float(project.balance_due) if project.balance_due else None,
                'expected_delivery_date': project.expected_delivery_date.isoformat() if project.expected_delivery_date else None,
                'actual_delivery_date': project.actual_delivery_date.isoformat() if project.actual_delivery_date else None,
                'notes': project.notes,
                'created_at': project.created_at.isoformat() if project.created_at else None,
                'updated_at': project.updated_at.isoformat() if project.updated_at else None
            }
            projects_list.append(project_data)
        
        return jsonify({
            'customer': {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'email': customer.email
            },
            'projects': projects_list
        }), 200
        
    except Exception as e:
        print(f"Error fetching customer projects: {str(e)}")
        return jsonify({'error': str(e)}), 500

@customer_bp.route('/customers/<string:customer_id>/projects', methods=['POST', 'OPTIONS'])
@token_required
def create_project(customer_id):
    """Create a new project for a customer."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != session.get(User, request.current_user.id).id and customer.salesperson != session.get(User, request.current_user.id).full_name:
                return jsonify({'error': 'You do not have permission to create projects for this customer'}), 403
        
        data = request.get_json()
        
        # Validate required fields
        if not data.get('project_name'):
            return jsonify({'error': 'Project name is required'}), 400
        if not data.get('project_type'):
            return jsonify({'error': 'Project type is required'}), 400
        
        # Create new project
        new_project = Project(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            project_name=data.get('project_name'),
            project_type=data.get('project_type'),
            stage=data.get('stage', 'Lead'),
            date_of_measure=datetime.fromisoformat(data['date_of_measure']) if data.get('date_of_measure') else None,
            notes=data.get('notes', ''),
            created_at=datetime.utcnow(),
            created_by=request.current_user.id
        )
        
        session.add(new_project)
        session.commit() # 👈 Commit the new project first
        
        # --- CRITICAL FIX 1: SIMPLIFY STAGE SYNC ON CREATION ---
        existing_project_count = session.query(Project).filter_by(customer_id=customer_id).count()
        existing_job_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        # If the combined count is 1 (meaning only the new project exists), sync customer stage.
        if existing_project_count == 1 and existing_job_count == 0 and new_project.stage:
            old_customer_stage = customer.stage
            customer.stage = new_project.stage
            
            # 🔔 CREATE NOTIFICATION IF MOVED TO PRODUCTION
            if new_project.stage == 'Production' and old_customer_stage != 'Production':
                notification = ProductionNotification(
                    id=str(uuid.uuid4()),
                    customer_id=customer_id,
                    message=f"New customer '{customer.name}' moved to Production stage",
                    created_at=datetime.utcnow(),
                    moved_by=request.current_user.username if hasattr(request.current_user, 'username') else request.current_user.email,
                    read=False
                )
                session.add(notification)
                current_app.logger.info(f"📢 Production notification created for customer {customer_id}")
            
            session.commit() # Commit customer stage change and notification
        
        current_app.logger.info(f"Project {new_project.id} created for customer {customer_id} by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': new_project.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error creating project for customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to create project: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session


@customer_bp.route('/projects/<string:project_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_project(project_id):
    """Get a specific project with all its details"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        project = Project.query.get_or_404(project_id)
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != request.current_user.id and customer.salesperson != request.current_user.get_full_name():
                return jsonify({'error': 'You do not have permission to view this project'}), 403
        
        return jsonify(project.to_dict(include_forms=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching project {project_id}: {e}")
        return jsonify({'error': 'Failed to fetch project'}), 500


@customer_bp.route('/projects/<string:project_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_project(project_id):
    """Update a project."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        # Get project and customer using the active session
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != session.get(User, request.current_user.id).id and customer.salesperson != session.get(User, request.current_user.id).full_name:
                return jsonify({'error': 'You do not have permission to edit this project'}), 403
        
        data = request.get_json()
        
        old_stage = project.stage # Capture old stage for comparison/sync logic
        
        # Update fields
        if 'project_name' in data:
            project.project_name = data['project_name']
        if 'project_type' in data:
            project.project_type = data['project_type']
        if 'stage' in data:
            project.stage = data['stage'] # Update the Project's specific stage
        if 'date_of_measure' in data:
            project.date_of_measure = datetime.fromisoformat(data['date_of_measure']) if data['date_of_measure'] else None
        if 'notes' in data:
            project.notes = data['notes']
        
        project.updated_by = request.current_user.id
        project.updated_at = datetime.utcnow()
        
        # Count existing linked entities (Projects + Jobs)
        total_other_linked_entities = session.query(Project).filter(Project.customer_id==customer.id, Project.id != project_id).count() + \
                                      session.query(Job).filter_by(customer_id=customer.id).count()
        
        # If the stage changed AND there are NO other entities, sync the customer's overall stage.
        if 'stage' in data and project.stage != old_stage and total_other_linked_entities == 0:
            old_customer_stage = customer.stage
            customer.stage = project.stage
            
            # 🔔 CREATE NOTIFICATION IF MOVED TO PRODUCTION
            if project.stage == 'Production' and old_customer_stage != 'Production':
                notification = ProductionNotification(
                    id=str(uuid.uuid4()),
                    customer_id=customer.id,
                    message=f"Customer '{customer.name}' moved to Production stage",
                    created_at=datetime.utcnow(),
                    moved_by=request.current_user.username if hasattr(request.current_user, 'username') else request.current_user.email,
                    read=False
                )
                session.add(notification)
                current_app.logger.info(f"📢 Production notification created for customer {customer.id}")
        
        session.commit() # 👈 Commit transaction
        
        current_app.logger.info(f"Project {project_id} updated by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully',
            'project': project.to_dict(include_forms=True)
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error updating project {project_id}: {e}")
        return jsonify({'error': f'Failed to update project: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session


@customer_bp.route('/projects/<string:project_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_project(project_id):
    """Delete a project (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        # Only Manager and HR can delete
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete projects'}), 403
        
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # Determine if this is the last project/job for the customer before deleting
        customer_id = project.customer_id
        
        session.delete(project)
        session.commit() # 👈 Commit deletion
        
        # After deletion, check if the customer has any remaining projects or jobs.
        remaining_projects_count = session.query(Project).filter_by(customer_id=customer_id).count()
        remaining_jobs_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        if remaining_projects_count == 0 and remaining_jobs_count == 0:
             customer = session.get(Customer, customer_id)
             if customer:
                 customer.stage = 'Lead' 
                 session.commit()

        current_app.logger.info(f"Project {project_id} deleted by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Project deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error deleting project {project_id}: {e}")
        return jsonify({'error': 'Failed to delete project'}), 500
    finally:
        session.close() # 👈 Close session


# ==========================================
# PROJECT FORMS ENDPOINTS
# ==========================================

@customer_bp.route('/projects/<string:project_id>/forms', methods=['GET', 'OPTIONS'])
@token_required
def get_project_forms(project_id):
    """Get all forms for a specific project"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        project = Project.query.get_or_404(project_id)
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != request.current_user.id and customer.salesperson != request.current_user.get_full_name():
                return jsonify({'error': 'You do not have permission to view forms for this project'}), 403
        
        forms = CustomerFormData.query.filter_by(project_id=project_id).order_by(CustomerFormData.submitted_at.desc()).all()
        
        return jsonify([form.to_dict() for form in forms]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching forms for project {project_id}: {e}")
        return jsonify({'error': 'Failed to fetch forms'}), 500
    
# ==========================================
# DRAWING DOCUMENTS ENDPOINTS (NEW)
# ==========================================

@customer_bp.route('/drawings', methods=['GET', 'OPTIONS'])
@token_required
def get_drawing_documents():
    """Get all drawing documents for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'error': 'Customer ID is required'}), 400
        
        customer = Customer.query.get_or_404(customer_id)
        
        # Check permissions (same as customer/project access)
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != request.current_user.id and customer.salesperson != request.current_user.get_full_name():
                return jsonify({'error': 'You do not have permission to view documents for this customer'}), 403
        
        # Fetch all drawing documents for the customer
        drawings = DrawingDocument.query.filter_by(customer_id=customer_id).order_by(DrawingDocument.created_at.desc()).all()
        
        return jsonify([drawing.to_dict() for drawing in drawings]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching drawing documents: {e}")
        return jsonify({'error': 'Failed to fetch drawing documents'}), 500

@customer_bp.route('/drawings/<string:drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_drawing_document(drawing_id):
    """Delete a drawing document (Manager/HR/Creator only - simplified to Manager/HR for now)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        # Permission check
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete documents'}), 403
        
        drawing = session.get(DrawingDocument, drawing_id)
        if not drawing:
            return jsonify({'error': 'Document not found'}), 404
        
        # NOTE: In a real app, you must **delete the actual file** from S3/disk here
        
        session.delete(drawing)
        session.commit() # 👈 Commit deletion
        
        current_app.logger.info(f"Drawing document {drawing_id} deleted by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Drawing document deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error deleting drawing document {drawing_id}: {e}")
        return jsonify({'error': 'Failed to delete drawing document'}), 500
    finally:
        session.close() # 👈 Close session


# ==========================================
# FORM SUBMISSION ENDPOINT (Updated)
# ==========================================

@customer_bp.route('/forms/submit', methods=['POST', 'OPTIONS'])
def submit_form():
    """Submit a form linked to a project (public endpoint - no auth required)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal() # 👈 Start session
    try:
        data = request.get_json()
        token = data.get('token')
        customer_id = data.get('customer_id')
        project_id = data.get('project_id') 
        
        if not token:
            return jsonify({'error': 'Token is required'}), 400
        if not customer_id:
            return jsonify({'error': 'Customer ID is required'}), 400
        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400
        
        # Validate customer exists
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Validate project exists and belongs to customer
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        if project.customer_id != customer_id:
            return jsonify({'error': 'Project does not belong to this customer'}), 400
        
        # Create form submission
        form_submission = CustomerFormData(
            customer_id=customer_id,
            project_id=project_id,
            token_used=token,
            form_data=json.dumps(data.get('form_data', {})),
            submitted_at=datetime.utcnow()
        )
        
        session.add(form_submission)
        session.commit() # 👈 Commit transaction
        
        current_app.logger.info(f"Form submitted for project {project_id}")
        
        return jsonify({
            'success': True,
            'message': 'Form submitted successfully',
            'form_id': form_submission.id
        }), 201
        
    except Exception as e:
        session.rollback() # 👈 Rollback on error
        current_app.logger.exception(f"Error submitting form: {e}")
        return jsonify({'error': f'Failed to submit form: {str(e)}'}), 500
    finally:
        session.close() # 👈 Close session

@customer_bp.route('/pipeline', methods=['GET'])
@token_required
def get_pipeline():
    """Get pipeline data showing customers by their most advanced stage."""
    
    try:
        # Define stage order
        stage_order = {
            'Lead': 1,
            'Qualified': 2,
            'Quote Sent': 3,
            'Negotiation': 4,
            'Accepted': 5,
            'Deposit Paid': 6,
            'In Production': 7,
            'Ready for Delivery': 8,
            'Delivered': 9,
            'Installed': 10,
            'Completed': 11,
            'Lost': 0
        }
        
        stage_order_case = case(
            *[(Project.stage == stage, order) for stage, order in stage_order.items()],
            else_=0
        )
        
        # Get customers with their most advanced stage
        customers_query = db.session.query(
            Customer,
            func.count(func.distinct(Project.id)).label('project_count'),
            func.max(stage_order_case).label('max_stage_order')
        ).outerjoin(
            Project, Customer.id == Project.customer_id
        ).group_by(Customer.id).all()
        
        order_to_stage = {v: k for k, v in stage_order.items()}
        
        # Organize customers by stage
        pipeline_data = {stage: [] for stage in stage_order.keys()}
        
        for customer, project_count, max_stage_order in customers_query:
            if project_count > 0:
                most_advanced_stage = order_to_stage.get(max_stage_order, 'Lead')
            else:
                most_advanced_stage = 'Lead'
            
            customer_data = {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone,
                'email': customer.email,
                'project_count': project_count,
                'stage': most_advanced_stage,
                'created_at': customer.created_at.isoformat() if customer.created_at else None
            }
            
            pipeline_data[most_advanced_stage].append(customer_data)
        
        return jsonify(pipeline_data), 200
        
    except Exception as e:
        print(f"Error fetching pipeline data: {str(e)}")
        return jsonify({'error': str(e)}), 500