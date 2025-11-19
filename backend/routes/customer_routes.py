from flask import Blueprint, request, jsonify
from ..models import Customer, Project, CustomerFormData, User, Job, DrawingDocument, FormDocument, ProductionNotification
from functools import wraps
from flask import current_app
import uuid
from datetime import datetime
import json

# 👈 NEW IMPORT: Required for all database write operations
from ..db import SessionLocal 
from .notification_routes import create_activity_notification  # ✅ ADD THIS IMPORT


customer_bp = Blueprint('customers', __name__)

# Define stage hierarchy for determining "most advanced" stage
STAGE_HIERARCHY = {
    "Lead": 0,
    "Quote": 1,
    "Consultation": 2,
    "Survey": 3,
    "Measure": 4,
    "Design": 5,
    "Quoted": 6,
    "Accepted": 7,  # ✅ MAKE SURE THIS EXISTS
    "Rejected": 8,
    "Ordered": 9,
    "Production": 10,
    "Delivery": 11,
    "Installation": 12,
    "Complete": 13,
    "Remedial": 14,
    "Cancelled": 15
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


# Token authentication decorator
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
    """Get all customers with their project counts, form counts, drawing counts, and MOST ADVANCED PROJECT STAGE.
    
    ✅ NOTE: Stages are only defined by Projects, not Jobs.
    Jobs are created when projects reach Accepted/Production stage.
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customers = session.query(Customer).all()
        
        current_app.logger.info(f"📊 Fetching data for {len(customers)} customers")
        
        result = []
        for customer in customers:
            form_count = session.query(CustomerFormData).filter_by(customer_id=customer.id).count()
            drawing_count = session.query(DrawingDocument).filter_by(customer_id=customer.id).count()
            form_doc_count = session.query(FormDocument).filter_by(customer_id=customer.id).count()
            
            # Get all linked projects (Jobs don't have stages)
            customer_projects = session.query(Project).filter_by(customer_id=customer.id).all()
            
            total_project_count = len(customer_projects)
            
            # ✅ FIXED: Collect stages ONLY from projects, not jobs
            all_stages = [customer.stage] if customer.stage else []
            all_stages.extend([project.stage for project in customer_projects if project.stage])
            
            # Get the most advanced stage from projects only
            display_stage = get_most_advanced_stage(all_stages)
            
            # ✅ CRITICAL FIX: Ensure stage is always a string, never None
            if not display_stage or display_stage == 'None':
                display_stage = 'Lead'
                current_app.logger.warning(f"⚠️ Customer {customer.id} ({customer.name}) had no valid stage, defaulting to Lead")
            
            # ✅ OPTIMIZATION: Calculate total document count IN BACKEND
            total_documents = int(drawing_count) + int(form_count) + int(form_doc_count)
            
            customer_data = {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'email': customer.email or '',
                'address': customer.address or '',
                'postcode': customer.postcode or '',
                'salesperson': customer.salesperson or '',
                'contact_made': customer.contact_made or 'Unknown',
                'preferred_contact_method': customer.preferred_contact_method or 'Phone',
                'marketing_opt_in': bool(customer.marketing_opt_in),
                'notes': customer.notes or '',
                'status': customer.status or 'Active',
                'date_of_measure': customer.date_of_measure.isoformat() if customer.date_of_measure else None,
                'created_at': customer.created_at.isoformat() if customer.created_at else None,
                'updated_at': customer.updated_at.isoformat() if customer.updated_at else None,
                'created_by': customer.created_by,
                'updated_by': customer.updated_by,
                'stage': display_stage,  # ✅ Most advanced PROJECT stage
                'project_count': total_project_count,
                'form_count': int(form_count),
                'drawing_count': int(drawing_count),
                'form_document_count': int(form_doc_count),
                'total_documents': total_documents,
                'has_documents': total_documents > 0,
                'has_drawings': drawing_count > 0,
                'has_forms': form_count > 0 or form_doc_count > 0,
            }
            
            # Handle project_types
            project_types_value = customer.project_types
            if project_types_value is None:
                project_types_value = []
            elif isinstance(project_types_value, str):
                import json
                try:
                    project_types_value = json.loads(project_types_value)
                except:
                    project_types_value = []
            elif not isinstance(project_types_value, list):
                project_types_value = []
            
            customer_data['project_types'] = project_types_value
            result.append(customer_data)

        # ✅ LOG SUMMARY
        accepted_count = len([c for c in result if c['stage'] == 'Accepted'])
        customers_without_docs = len([c for c in result if c['total_documents'] == 0])
        
        current_app.logger.info(f"📊 Total customers: {len(result)}, Accepted: {accepted_count}, Without documents: {customers_without_docs}")
        
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customers: {e}")
        return jsonify({'error': 'Failed to fetch customers'}), 500
    finally:
        session.close()


@customer_bp.route('/customers', methods=['POST', 'OPTIONS'])
@token_required
def create_customer():
    """Create a new customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
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
            created_by=str(request.current_user.id)
        )
        
        session.add(new_customer)
        session.commit()
        
        current_app.logger.info(f"Customer {new_customer.id} created by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer created successfully',
            'customer': new_customer.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_customer(customer_id):
    """Get a single customer by ID with all their projects"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check access permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        elif request.current_user.role == 'Staff':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this customer'}), 403
        
        # Return customer with all projects
        return jsonify(customer.to_dict(include_projects=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_customer(customer_id):
    """Update a customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role == 'Sales':
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
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
        
        customer.updated_by = str(request.current_user.id)
        customer.updated_at = datetime.utcnow()
        
        session.commit()
        
        customer_dict = customer.to_dict(include_projects=True)
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully',
            'customer': customer_dict
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating customer {customer_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<string:customer_id>/stage', methods=['PATCH', 'OPTIONS'])
@token_required
def update_customer_stage_direct(customer_id):
    """Update customer stage directly - FIXED VERSION"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400

        current_app.logger.info(f"🔄 Updating customer {customer_id} stage to {new_stage}")
        
        old_stage = customer.stage
        customer.stage = new_stage
        customer.updated_by = str(request.current_user.id)
        customer.updated_at = datetime.utcnow()
        
        # ✅ CRITICAL: Commit immediately
        session.commit()
        session.refresh(customer)
        
        current_app.logger.info(f"✅ Customer stage updated: {old_stage} → {new_stage}")
        
        return jsonify({
            'success': True,
            'customer_id': customer.id,
            'old_stage': old_stage,
            'new_stage': customer.stage,
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/by-stage/<string:stage>', methods=['GET', 'OPTIONS'])
@token_required
def get_customers_by_stage(stage):
    """Get customers who have at least one PROJECT in the specified stage
    
    Note: Only projects have stages. Jobs are created when projects reach Accepted/Production.
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Validate stage
        if stage not in STAGE_HIERARCHY:
            return jsonify({'error': f'Invalid stage: {stage}'}), 400
        
        # Find all customers with projects in this stage
        customers_with_projects = session.query(Customer).join(Project).filter(
            Project.stage == stage
        ).distinct().all()
        
        # Prepare response
        result = []
        for customer in customers_with_projects:
            # Count projects at this specific stage
            projects_at_stage = session.query(Project).filter(
                Project.customer_id == customer.id,
                Project.stage == stage
            ).all()
            
            # Get total project count for this customer
            total_projects = session.query(Project).filter_by(customer_id=customer.id).count()
            
            result.append({
                'id': customer.id,
                'name': customer.name,
                'email': customer.email,
                'phone': customer.phone,
                'address': customer.address,
                'stage': stage,  # The stage we're filtering by
                'projects_at_stage': len(projects_at_stage),
                'project_details': [
                    {
                        'id': p.id,
                        'name': p.project_name,
                        'type': p.project_type
                    } for p in projects_at_stage
                ],
                'total_projects': total_projects
            })
        
        current_app.logger.info(f"✅ Found {len(result)} customers with projects in '{stage}' stage")
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching customers by stage: {e}")
        return jsonify({'error': f'Failed to fetch customers in {stage} stage'}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_customer(customer_id):
    """Delete a customer (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
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
        session.commit()
        
        current_app.logger.info(f"Customer {customer_id} deleted by user {request.current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting customer {customer_id}: {e}")
        return jsonify({'error': 'Failed to delete customer'}), 500
    finally:
        session.close()


# ==========================================
# PROJECT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<string:customer_id>/projects', methods=['GET', 'OPTIONS'])
@token_required
def get_customer_projects(customer_id):
    """Get all projects for a specific customer with full details."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get all projects for this customer
        projects = session.query(Project).filter_by(customer_id=customer_id).all()
        
        projects_list = []
        for project in projects:
            project_data = {
                'id': project.id,
                'project_name': project.project_name,
                'project_type': project.project_type,
                'stage': project.stage,
                'date_of_measure': project.date_of_measure.isoformat() if project.date_of_measure else None,
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
        current_app.logger.exception(f"Error fetching customer projects: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<string:customer_id>/projects', methods=['POST', 'OPTIONS'])
@token_required
def create_project(customer_id):
    """Create a new project for a customer."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions - Manager, HR, and Sales can create projects for any customer
        allowed_roles = ['Manager', 'HR', 'Sales']
        
        if request.current_user.role not in allowed_roles:
            return jsonify({
                'error': f'You do not have permission to create projects. Only {", ".join(allowed_roles)} can create projects.'
            }), 403
        
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
            created_by=str(request.current_user.id)
        )
        
        session.add(new_project)
        
        # ✅ ENHANCED NOTIFICATION: Create notification for project creation
        try:
            user_name = request.current_user.full_name if hasattr(request.current_user, 'full_name') else request.current_user.email
            
            create_activity_notification(
                session=session,
                message=f"➕ New {data.get('project_type', 'project')} created for customer '{customer.name}' - {data.get('project_name')}",
                customer_id=customer_id,
                moved_by=user_name
            )
        except Exception as notif_error:
            current_app.logger.warning(f"⚠️ Failed to create notification: {notif_error}")
        
        # Update customer stage if this is the first project
        existing_project_count = session.query(Project).filter_by(customer_id=customer_id).count()
        existing_job_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        if existing_project_count == 1 and existing_job_count == 0 and new_project.stage:
            old_customer_stage = customer.stage
            customer.stage = new_project.stage
            
            # ✅ ENHANCED: Create notification for ANY important stage change, not just Production
            important_stages = ['Accepted', 'Production', 'Delivery', 'Installation', 'Complete']
            
            if new_project.stage in important_stages and old_customer_stage != new_project.stage:
                try:
                    stage_emoji = {
                        'Accepted': '✅',
                        'Production': '🏭',
                        'Delivery': '🚚',
                        'Installation': '🔧',
                        'Complete': '🎉'
                    }
                    emoji = stage_emoji.get(new_project.stage, '🔄')
                    
                    create_activity_notification(
                        session=session,
                        message=f"{emoji} Customer '{customer.name}' moved from {old_customer_stage} to {new_project.stage} stage",
                        customer_id=customer_id,
                        moved_by=user_name
                    )
                except Exception as notif_error:
                    current_app.logger.warning(f"⚠️ Failed to create stage notification: {notif_error}")
        
        session.commit()
        
        current_app.logger.info(f"Project {new_project.id} created for customer {customer_id}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': new_project.to_dict()
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error creating project: {e}")
        return jsonify({'error': f'Failed to create project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_project(project_id):
    """Get a specific project with all its details"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view this project'}), 403
        
        return jsonify(project.to_dict(include_forms=True)), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching project {project_id}: {e}")
        return jsonify({'error': 'Failed to fetch project'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_project(project_id):
    """Update a project."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to edit this project'}), 403
        
        data = request.get_json()
        
        old_stage = project.stage
        
        # Update fields
        if 'project_name' in data:
            project.project_name = data['project_name']
        if 'project_type' in data:
            project.project_type = data['project_type']
        if 'stage' in data:
            project.stage = data['stage']
        if 'date_of_measure' in data:
            project.date_of_measure = datetime.fromisoformat(data['date_of_measure']) if data['date_of_measure'] else None
        if 'notes' in data:
            project.notes = data['notes']
        
        project.updated_by = str(request.current_user.id)
        project.updated_at = datetime.utcnow()
        
        # Count existing linked entities
        total_other_linked_entities = session.query(Project).filter(Project.customer_id==customer.id, Project.id != project_id).count() + \
                                      session.query(Job).filter_by(customer_id=customer.id).count()
        
        if 'stage' in data and project.stage != old_stage and total_other_linked_entities == 0:
            old_customer_stage = customer.stage
            customer.stage = project.stage
            
            if project.stage == 'Production' and old_customer_stage != 'Production':
                notification = ProductionNotification(
                    id=str(uuid.uuid4()),
                    customer_id=customer.id,
                    message=f"Customer '{customer.name}' moved to Production stage",
                    created_at=datetime.utcnow(),
                    moved_by=request.current_user.email,
                    read=False
                )
                session.add(notification)
        
        session.commit()
        
        current_app.logger.info(f"Project {project_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully',
            'project': project.to_dict(include_forms=True)
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error updating project: {e}")
        return jsonify({'error': f'Failed to update project: {str(e)}'}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<string:project_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_project(project_id):
    """Delete a project (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete projects'}), 403
        
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        customer_id = project.customer_id
        
        session.delete(project)
        session.commit()
        
        # Check if customer has remaining projects or jobs
        remaining_projects_count = session.query(Project).filter_by(customer_id=customer_id).count()
        remaining_jobs_count = session.query(Job).filter_by(customer_id=customer_id).count()
        
        if remaining_projects_count == 0 and remaining_jobs_count == 0:
             customer = session.get(Customer, customer_id)
             if customer:
                 customer.stage = 'Lead' 
                 session.commit()

        current_app.logger.info(f"Project {project_id} deleted")
        
        return jsonify({
            'success': True,
            'message': 'Project deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting project: {e}")
        return jsonify({'error': 'Failed to delete project'}), 500
    finally:
        session.close()


# ==========================================
# PROJECT FORMS ENDPOINTS
# ==========================================

@customer_bp.route('/projects/<string:project_id>/forms', methods=['GET', 'OPTIONS'])
@token_required
def get_project_forms(project_id):
    """Get all forms for a specific project"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
            
        customer = project.customer
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view forms for this project'}), 403
        
        forms = session.query(CustomerFormData).filter_by(project_id=project_id).order_by(CustomerFormData.submitted_at.desc()).all()
        
        return jsonify([form.to_dict() for form in forms]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching forms: {e}")
        return jsonify({'error': 'Failed to fetch forms'}), 500
    finally:
        session.close()

    
# ==========================================
# DRAWING DOCUMENTS ENDPOINTS
# ==========================================

@customer_bp.route('/drawings', methods=['GET', 'OPTIONS'])
@token_required
def get_drawing_documents():
    """Get all drawing documents for a specific customer"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        customer_id = request.args.get('customer_id')
        if not customer_id:
            return jsonify({'error': 'Customer ID is required'}), 400
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Check permissions
        if request.current_user.role in ['Sales', 'Staff']:
            if customer.created_by != str(request.current_user.id) and customer.salesperson != request.current_user.full_name:
                return jsonify({'error': 'You do not have permission to view documents for this customer'}), 403
        
        drawings = session.query(DrawingDocument).filter_by(customer_id=customer_id).order_by(DrawingDocument.created_at.desc()).all()
        
        return jsonify([drawing.to_dict() for drawing in drawings]), 200
        
    except Exception as e:
        current_app.logger.exception(f"Error fetching drawings: {e}")
        return jsonify({'error': 'Failed to fetch drawing documents'}), 500
    finally:
        session.close()


@customer_bp.route('/drawings/<string:drawing_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_drawing_document(drawing_id):
    """Delete a drawing document (Manager/HR only)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        if request.current_user.role not in ['Manager', 'HR']:
            return jsonify({'error': 'You do not have permission to delete documents'}), 403
        
        drawing = session.get(DrawingDocument, drawing_id)
        if not drawing:
            return jsonify({'error': 'Document not found'}), 404
        
        session.delete(drawing)
        session.commit()
        
        current_app.logger.info(f"Drawing document {drawing_id} deleted")
        
        return jsonify({
            'success': True,
            'message': 'Drawing document deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting drawing: {e}")
        return jsonify({'error': 'Failed to delete drawing document'}), 500
    finally:
        session.close()


# ==========================================
# FORM SUBMISSION ENDPOINT
# ==========================================

@customer_bp.route('/forms/submit', methods=['POST', 'OPTIONS'])
def submit_form():
    """Submit a form linked to a project (public endpoint - no auth required)"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
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
        
        customer = session.get(Customer, customer_id)
        if not customer:
            return jsonify({'error': 'Customer not found'}), 404
        
        project = session.get(Project, project_id)
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        if project.customer_id != customer_id:
            return jsonify({'error': 'Project does not belong to this customer'}), 400
        
        form_submission = CustomerFormData(
            customer_id=customer_id,
            project_id=project_id,
            token_used=token,
            form_data=json.dumps(data.get('form_data', {})),
            submitted_at=datetime.utcnow()
        )
        
        session.add(form_submission)
        session.commit()
        
        current_app.logger.info(f"Form submitted for project {project_id}")
        
        return jsonify({
            'success': True,
            'message': 'Form submitted successfully',
            'form_id': form_submission.id
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error submitting form: {e}")
        return jsonify({'error': f'Failed to submit form: {str(e)}'}), 500
    finally:
        session.close()

@customer_bp.route('/customers/debug-accepted', methods=['GET', 'OPTIONS'])
# @token_required
def debug_accepted_customers():
    """Debug endpoint to see what's going on with Accepted stage"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        # Get all customers in Accepted stage
        customers_in_accepted = session.query(Customer).filter(
            Customer.stage == 'Accepted'
        ).all()
        
        debug_info = []
        
        for customer in customers_in_accepted:
            # Get all projects for this customer
            projects = session.query(Project).filter_by(customer_id=customer.id).all()
            
            project_info = []
            for project in projects:
                project_info.append({
                    'id': project.id,
                    'name': project.project_name,
                    'type': project.project_type,
                    'stage': project.stage
                })
            
            debug_info.append({
                'customer_id': customer.id,
                'customer_name': customer.name,
                'customer_stage': customer.stage,
                'projects': project_info,
                'projects_in_accepted': len([p for p in projects if p.stage == 'Accepted'])
            })
        
        current_app.logger.info(f"🔍 Debug: Found {len(customers_in_accepted)} customers with stage='Accepted'")
        
        return jsonify({
            'total_customers_in_accepted': len(customers_in_accepted),
            'details': debug_info
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Debug error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()