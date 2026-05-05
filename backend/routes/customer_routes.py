from flask import Blueprint, request, jsonify, current_app, g
from sqlalchemy import text
from datetime import datetime
import json
import uuid

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

customer_bp = Blueprint('customers', __name__)

# Define stage hierarchy
STAGE_HIERARCHY = {
    "Lead": 0,
    "Quote": 1,
    "Consultation": 2,
    "Survey": 3,
    "Measure": 4,
    "Design": 5,
    "Quoted": 6,
    "Accepted": 7,
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
    valid_stages = [s for s in stages if s and s in STAGE_HIERARCHY]
    if not valid_stages:
        return "Lead"
    return max(valid_stages, key=lambda s: STAGE_HIERARCHY.get(s, 0))


def get_client_ip():
    """Get client IP address"""
    if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
        return request.environ['REMOTE_ADDR']
    else:
        return request.environ['HTTP_X_FORWARDED_FOR']


# ==========================================
# CLIENT/CUSTOMER ENDPOINTS
# ==========================================

@customer_bp.route('/customers', methods=['GET'])
@token_required
@require_tenant
def get_customers(tenant_id, employee_id):
    """Get all clients with their project counts and document counts"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                c.client_id,
                c.client_company_name as client_name,
                c.client_contact_name,
                c.client_phone as phone,
                c.client_email as email,
                c.address,
                c.post_code as postcode,
                c.stage,
                c.assigned_employee_id,
                c.is_allocated,
                c.is_cleansed,
                c.created_at,
                c.is_deleted,
                c.is_archived,
                e.employee_name as salesperson_name,
                COUNT(DISTINCT p.project_id) as project_count,
                COUNT(DISTINCT doc.id) as document_count,
                COUNT(DISTINCT f.form_submission_id) as form_count,
                c.project_types
            FROM "StreemLyne_MT"."Client_Master" c
            LEFT JOIN "StreemLyne_MT"."Employee_Master" e
                ON c.assigned_employee_id = e.employee_id AND e.tenant_id = c.tenant_id
            LEFT JOIN "StreemLyne_MT"."Project_Details" p 
                ON c.client_id = p.client_id AND p.tenant_id = c.tenant_id
            LEFT JOIN "StreemLyne_MT"."Customer_Documents" doc
                ON c.client_id = doc.client_id
            LEFT JOIN "StreemLyne_MT"."Customer_Form_Submissions" f
                ON c.client_id = f.client_id AND f.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tenant_id AND c.is_deleted = false
            GROUP BY c.client_id, c.client_company_name, c.client_contact_name,
                     c.client_phone, c.client_email, c.address, c.post_code, 
                     c.stage, c.assigned_employee_id, c.is_allocated, c.is_cleansed,
                     c.created_at, c.is_deleted, c.is_archived, e.employee_name
            ORDER BY c.created_at DESC
        """)
        
        clients = session.execute(query, {'tenant_id': str(tenant_id)}).fetchall()
        
        result = []
        for client in clients:
            result.append({
                'id': client.client_id,
                'name': client.client_name,
                'contact_name': client.client_contact_name or '',
                'phone': client.phone or '',
                'email': client.email or '',
                'address': client.address or '',
                'postcode': client.postcode or '',
                'stage': client.stage or 'Lead',
                'assigned_employee_id': client.assigned_employee_id,
                'salesperson': client.salesperson_name or '',
                'project_types': client.project_types if client.project_types else [],
                'is_allocated': bool(client.is_allocated),
                'is_cleansed': bool(client.is_cleansed),
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'project_count': client.project_count or 0,
                'document_count': client.document_count or 0,
                'form_count': client.form_count or 0,
                'has_documents': (client.document_count or 0) > 0,
                'has_forms': (client.form_count or 0) > 0
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching customers: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers', methods=['POST'])
@token_required
@require_tenant
def create_customer(tenant_id, employee_id):
    """Create a new client"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Client_Master"
            (tenant_id, client_company_name, client_contact_name, client_phone, 
             client_email, address, post_code, assigned_employee_id, stage,
             is_allocated, is_cleansed, is_deleted, is_archived)
            VALUES (:tenant_id, :name, :contact_name, :phone, :email, :address, 
                    :postcode, :assigned_to, 'Lead', false, false, false, false)
            RETURNING client_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'name': data['name'],
            'contact_name': data.get('contact_name', ''),
            'phone': data['phone'],
            'email': data.get('email', ''),
            'address': data.get('address', ''),
            'postcode': data.get('postcode', ''),
            'assigned_to': data.get('assigned_employee_id', employee_id)
        })
        
        client_id = result.fetchone().client_id
        session.commit()
        
        current_app.logger.info(f"Client {client_id} created by employee {employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer created successfully',
            'customer': {'id': client_id}
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/customers/<int:customer_id>', methods=['GET'])
@token_required
@require_tenant
def get_customer(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Get a single client by ID with all their projects"""
    session = SessionLocal()
    try:
        # Get client
        client_query = text("""
            SELECT * FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id AND is_deleted = false
        """)
        
        client = session.execute(client_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get projects with form counts (excluding customer_checklist)
        projects_query = text("""
            SELECT 
                pd.project_id,
                pd.project_title,
                pd.project_type,
                pd.stage,
                pd.date_of_measure,
                pd.project_description,
                pd.start_date,
                pd.end_date,
                pd.status,
                pd.notes,
                pd.created_at,
                (
                    SELECT COUNT(*) 
                    FROM "StreemLyne_MT"."Customer_Form_Submissions" cfs
                    WHERE cfs.project_id = pd.project_id
                      AND cfs.form_type != 'customer_checklist'
                ) as form_count
            FROM "StreemLyne_MT"."Project_Details" pd
            WHERE pd.client_id = :client_id AND pd.tenant_id = :tenant_id
            ORDER BY pd.created_at DESC
        """)
        
        projects = session.execute(projects_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        # Get form submissions (exclude customer_checklist - it's just metadata)
        forms_query = text("""
            SELECT 
                form_submission_id,
                form_type,
                form_name,
                submission_status,
                approval_status,
                submitted_at,
                project_id,
                opportunity_id
            FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE client_id = :client_id 
              AND tenant_id = :tenant_id
              AND form_type != 'customer_checklist'
            ORDER BY submitted_at DESC
        """)
        
        forms = session.execute(forms_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        result = {
            'id': client.client_id,
            'name': client.client_company_name,
            'contact_name': client.client_contact_name,
            'phone': client.client_phone,
            'email': client.client_email,
            'address': client.address,
            'postcode': client.post_code,
            'stage': client.stage or 'Lead',
            'assigned_employee_id': client.assigned_employee_id,
            'is_allocated': bool(client.is_allocated),
            'is_cleansed': bool(client.is_cleansed),
            'created_at': client.created_at.isoformat() if client.created_at else None,
            'projects': [{
                'id': p.project_id,
                'project_name': p.project_title,  # ✅ Frontend expects this
                'project_title': p.project_title,
                'project_type': p.project_type,
                'stage': p.stage,
                'date_of_measure': p.date_of_measure.isoformat() if p.date_of_measure else None,
                'project_description': p.project_description,
                'start_date': p.start_date.isoformat() if p.start_date else None,
                'end_date': p.end_date.isoformat() if p.end_date else None,
                'status': p.status,
                'notes': p.notes,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'form_count': p.form_count or 0
            } for p in projects],
            'forms': [{
                'id': f.form_submission_id,
                'form_type': f.form_type,
                'form_name': f.form_name,
                'submission_status': f.submission_status,
                'approval_status': f.approval_status,
                'submitted_at': f.submitted_at.isoformat() if f.submitted_at else None,
                'project_id': f.project_id,
                'opportunity_id': f.opportunity_id
            } for f in forms]
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<int:customer_id>', methods=['PUT'])
@token_required
@require_tenant
def update_customer(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Update a client"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'client_id': customer_id, 'tenant_id': str(tenant_id)}
        
        updatable = {
            'name': 'client_company_name',
            'contact_name': 'client_contact_name',
            'phone': 'client_phone',
            'email': 'client_email',
            'address': 'address',
            'postcode': 'post_code',
            'stage': 'stage',
            'assigned_employee_id': 'assigned_employee_id',
            'is_allocated': 'is_allocated',
            'is_cleansed': 'is_cleansed'
        }
        
        for key, col in updatable.items():
            if key in data:
                update_fields.append(f"{col} = :{key}")
                params[key] = data[key]
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET {', '.join(update_fields)}
            WHERE client_id = :client_id AND tenant_id = :tenant_id AND is_deleted = false
        """)
        
        session.execute(update_query, params)
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Customer updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<int:customer_id>/stage', methods=['PATCH'])
@token_required
@require_tenant
def update_customer_stage(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Update customer stage directly"""
    session = SessionLocal()
    try:
        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET stage = :stage
            WHERE client_id = :client_id AND tenant_id = :tenant_id AND is_deleted = false
            RETURNING stage
        """)
        
        result = session.execute(update_query, {
            'stage': new_stage,
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Customer not found'}), 404
        
        session.commit()
        
        # Create notification for stage change
        try:
            notification_query = text("""
                INSERT INTO "StreemLyne_MT"."Notification_Master"
                (tenant_id, client_id, notification_type, priority, message, read, dismissed)
                VALUES (:tenant_id, :client_id, 'stage_change', 'medium', :message, false, false)
            """)
            
            session.execute(notification_query, {
                'tenant_id': str(tenant_id),
                'client_id': customer_id,
                'message': f"Customer stage updated to {new_stage}"
            })
            session.commit()
        except Exception as notif_error:
            current_app.logger.warning(f"Failed to create notification: {notif_error}")
        
        return jsonify({
            'success': True,
            'new_stage': new_stage
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating customer stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<int:customer_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_customer(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Delete a client (soft delete)"""
    session = SessionLocal()
    try:
        # Check if client has projects
        check_query = text("""
            SELECT COUNT(*) as count FROM "StreemLyne_MT"."Project_Details"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(check_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if result.count > 0:
            return jsonify({
                'error': f'Cannot delete customer with {result.count} project(s). Delete projects first.'
            }), 400
        
        # Soft delete
        delete_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET is_deleted = true,
                deleted_at = CURRENT_TIMESTAMP
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        })
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Customer deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

# ==========================================
# PROJECT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/projects', methods=['GET'])
@token_required
@require_tenant
def get_customer_projects(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Get all projects for a specific customer"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.*,
                c.client_company_name as client_name
            FROM "StreemLyne_MT"."Project_Details" p
            INNER JOIN "StreemLyne_MT"."Client_Master" c 
                ON p.client_id = c.client_id
            WHERE p.client_id = :client_id AND p.tenant_id = :tenant_id
            ORDER BY p.created_at DESC
        """)
        
        projects = session.execute(query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        result = {
            'customer': {
                'id': customer_id,
                'name': projects[0].client_name if projects else None
            },
            'projects': [{
                'id': p.project_id,
                'project_title': p.project_title,
                'project_description': p.project_description,
                'start_date': p.start_date.isoformat() if p.start_date else None,
                'end_date': p.end_date.isoformat() if p.end_date else None,
                'status': p.status,
                'assigned_employee_id': p.assigned_employee_id,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'updated_at': p.updated_at.isoformat() if p.updated_at else None
            } for p in projects]
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching customer projects: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/customers/<int:customer_id>/projects', methods=['POST'])
@token_required
@require_tenant
def create_project(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Create a new project for a customer"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        if not data.get('project_title'):
            return jsonify({'error': 'Project title is required'}), 400
        if not data.get('start_date'):
            return jsonify({'error': 'Start date is required'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Project_Details"
            (tenant_id, client_id, project_title, project_description, start_date, end_date, 
             employee_id, assigned_employee_id, status)
            VALUES (:tenant_id, :client_id, :title, :description, :start_date, :end_date, 
                    :employee_id, :assigned_to, :status)
            RETURNING project_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': customer_id,
            'title': data['project_title'],
            'description': data.get('project_description', ''),
            'start_date': data['start_date'],
            'end_date': data.get('end_date'),
            'employee_id': employee_id,
            'assigned_to': data.get('assigned_employee_id', employee_id),
            'status': data.get('status', 'active')
        })
        
        project_id = result.fetchone().project_id
        session.commit()
        
        current_app.logger.info(f"Project {project_id} created for client {customer_id}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': {'id': project_id}
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating project: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/projects/<int:project_id>', methods=['GET'])
@token_required
@require_tenant
def get_project(project_id, tenant_id, employee_id):
    """Get a specific project with all its details"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.*,
                c.client_company_name as client_name,
                c.client_phone,
                c.client_email
            FROM "StreemLyne_MT"."Project_Details" p
            INNER JOIN "StreemLyne_MT"."Client_Master" c 
                ON p.client_id = c.client_id
            WHERE p.project_id = :project_id
        """)
        
        project = session.execute(query, {
            'project_id': project_id
        }).fetchone()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # Get form submissions for this project
        forms_query = text("""
            SELECT 
                form_submission_id,
                form_type,
                form_name,
                submission_status,
                approval_status,
                submitted_at
            FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE project_id = :project_id AND tenant_id = :tenant_id
            ORDER BY submitted_at DESC
        """)
        
        forms = session.execute(forms_query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        result = {
            'id': project.project_id,
            'project_title': project.project_title,
            'project_description': project.project_description,
            'start_date': project.start_date.isoformat() if project.start_date else None,
            'end_date': project.end_date.isoformat() if project.end_date else None,
            'status': project.status,
            'assigned_employee_id': project.assigned_employee_id,
            'created_at': project.created_at.isoformat() if project.created_at else None,
            'updated_at': project.updated_at.isoformat() if project.updated_at else None,
            'customer': {
                'id': project.client_id,
                'name': project.client_name,
                'phone': project.client_phone,
                'email': project.client_email
            },
            'forms': [{
                'id': f.form_submission_id,
                'form_type': f.form_type,
                'form_name': f.form_name,
                'submission_status': f.submission_status,
                'approval_status': f.approval_status,
                'submitted_at': f.submitted_at.isoformat() if f.submitted_at else None
            } for f in forms]
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching project: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<int:project_id>', methods=['PUT'])
@token_required
@require_tenant
def update_project(project_id, tenant_id, employee_id):
    """Update a project"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'project_id': project_id}
        
        updatable = {
            'project_title': 'project_title',
            'project_description': 'project_description',
            'start_date': 'start_date',
            'end_date': 'end_date',
            'status': 'status',
            'assigned_employee_id': 'assigned_employee_id'
        }
        
        for key, col in updatable.items():
            if key in data:
                update_fields.append(f"{col} = :{key}")
                params[key] = data[key]
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Project_Details"
            SET {', '.join(update_fields)}
            WHERE project_id = :project_id
        """)
        
        session.execute(update_query, params)
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating project: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_project(project_id, tenant_id, employee_id):
    """Delete a project"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Project_Details"
            WHERE project_id = :project_id
        """)
        
        session.execute(delete_query, {
            'project_id': project_id
        })
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Project deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting project: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# FORM SUBMISSION ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/forms', methods=['GET'])
@token_required
@require_tenant
def get_customer_forms(tenant_id, employee_id, customer_id):
    """Get all form submissions for a customer"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                form_submission_id,
                form_type,
                form_name,
                form_data,
                submission_status,
                approval_status,
                submitted_by,
                submitted_at,
                project_id,
                opportunity_id,
                reviewed_by_employee_id,
                reviewed_at,
                review_notes
            FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE client_id = :client_id 
              AND tenant_id = :tenant_id
              AND form_type != 'customer_checklist'  -- ✅ EXCLUDE customer_checklist
            ORDER BY submitted_at DESC
        """)
        
        forms = session.execute(query, {
            'client_id': customer_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        result = []
        for form in forms:
            result.append({
                'id': form.form_submission_id,
                'form_type': form.form_type,
                'form_name': form.form_name,
                'form_data': form.form_data,
                'submission_status': form.submission_status,
                'approval_status': form.approval_status,
                'submitted_by': form.submitted_by,
                'submitted_at': form.submitted_at.isoformat() if form.submitted_at else None,
                'project_id': form.project_id,
                'opportunity_id': form.opportunity_id,
                'reviewed_by_employee_id': form.reviewed_by_employee_id,
                'reviewed_at': form.reviewed_at.isoformat() if form.reviewed_at else None,
                'review_notes': form.review_notes
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching customer forms: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/forms/submit', methods=['POST'])
def submit_form():
    """Submit a form (public endpoint - no auth required)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        token = data.get('token')
        client_id = data.get('client_id')
        tenant_id = data.get('tenant_id')
        project_id = data.get('project_id')
        opportunity_id = data.get('opportunity_id')
        form_type = data.get('form_type', 'general')
        form_data = data.get('form_data', {})
        
        if not client_id or not tenant_id:
            return jsonify({'error': 'Client ID and Tenant ID are required'}), 400
        
        if not form_data:
            return jsonify({'error': 'Form data is required'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
            (tenant_id, client_id, project_id, opportunity_id, form_type, form_data,
             submitted_by, token_used, ip_address, submission_status, approval_status)
            VALUES (:tenant_id, :client_id, :project_id, :opportunity_id, :form_type, 
                    :form_data, :submitted_by, :token, :ip_address, 'submitted', 'pending')
            RETURNING form_submission_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': client_id,
            'project_id': project_id,
            'opportunity_id': opportunity_id,
            'form_type': form_type,
            'form_data': json.dumps(form_data),
            'submitted_by': data.get('submitted_by', 'Anonymous'),
            'token': token,
            'ip_address': get_client_ip()
        })
        
        form_id = result.fetchone().form_submission_id
        session.commit()
        
        current_app.logger.info(f"Form submitted: {form_id} for client {client_id}")
        
        return jsonify({
            'success': True,
            'message': 'Form submitted successfully',
            'form_id': form_id
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error submitting form: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/forms/<int:form_id>', methods=['GET'])
@token_required
@require_tenant
def get_form_submission(form_id, tenant_id, employee_id):
    """Get a specific form submission"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
        """)
        
        form = session.execute(query, {
            'form_id': form_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not form:
            return jsonify({'error': 'Form submission not found'}), 404
        
        result = {
            'id': form.form_submission_id,
            'client_id': form.client_id,
            'project_id': form.project_id,
            'opportunity_id': form.opportunity_id,
            'form_type': form.form_type,
            'form_name': form.form_name,
            'form_data': form.form_data,
            'submission_status': form.submission_status,
            'approval_status': form.approval_status,
            'submitted_by': form.submitted_by,
            'submitted_at': form.submitted_at.isoformat() if form.submitted_at else None,
            'reviewed_by_employee_id': form.reviewed_by_employee_id,
            'reviewed_at': form.reviewed_at.isoformat() if form.reviewed_at else None,
            'review_notes': form.review_notes
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching form: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@customer_bp.route('/forms/<int:form_id>/review', methods=['POST'])
@token_required
@require_tenant
def review_form_submission(form_id, tenant_id, employee_id):
    """Approve or reject a form submission"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        approval_status = data.get('approval_status')
        if approval_status not in ['approved', 'rejected']:
            return jsonify({'error': 'Invalid approval status'}), 400
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Customer_Form_Submissions"
            SET approval_status = :approval_status,
                reviewed_by_employee_id = :employee_id,
                reviewed_at = CURRENT_TIMESTAMP,
                review_notes = :notes
            WHERE form_submission_id = :form_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, {
            'approval_status': approval_status,
            'employee_id': employee_id,
            'notes': data.get('review_notes', ''),
            'form_id': form_id,
            'tenant_id': str(tenant_id)
        })
        session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Form {approval_status} successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error reviewing form: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# DOCUMENT ENDPOINTS
# ==========================================

@customer_bp.route('/customers/<int:customer_id>/documents', methods=['GET'])
@token_required
@require_tenant
def get_customer_documents(tenant_id, employee_id, customer_id):  # ✅ FIXED parameter order
    """Get all documents for a customer"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Documents"
            WHERE client_id = :client_id
            ORDER BY uploaded_at DESC
        """)
        
        documents = session.execute(query, {
            'client_id': customer_id
        }).fetchall()
        
        result = []
        for doc in documents:
            result.append({
                'id': doc.id,
                'file_name': doc.file_name,
                'file_url': doc.file_url,
                'document_category': doc.document_category,
                'opportunity_id': doc.opportunity_id,
                'property_id': doc.property_id,
                'uploaded_at': doc.uploaded_at.isoformat() if doc.uploaded_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching documents: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/documents/<int:document_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_document(document_id, tenant_id, employee_id):
    """Delete a document"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Customer_Documents"
            WHERE id = :document_id
        """)
        
        session.execute(delete_query, {
            'document_id': document_id
        })
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Document deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting document: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@customer_bp.route('/api/customers', methods=['GET'])
@token_required
@require_tenant
def get_customers_list(tenant_id, employee_id):
    """Get all customers for the current tenant"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                client_id as id,
                client_company_name as name,
                client_address as address,
                client_phone as phone,
                client_email as email,
                client_postcode as postcode
            FROM "StreemLyne_MT"."Client_Master"
            WHERE tenant_id = :tenant_id
            ORDER BY client_company_name ASC
        """)
        
        customers = session.execute(query, {
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        customers_list = []
        for customer in customers:
            customers_list.append({
                'id': str(customer.id),
                'name': customer.name or 'N/A',
                'address': customer.address or '',
                'phone': customer.phone or '',
                'email': customer.email or '',
                'postcode': customer.postcode or ''
            })
        
        return jsonify(customers_list), 200

    except Exception as e:
        current_app.logger.exception(f"Failed to fetch customers: {e}")
        return jsonify({'error': f'Failed to fetch customers: {str(e)}'}), 500
    finally:
        session.close()