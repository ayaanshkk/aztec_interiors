from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

project_bp = Blueprint('projects', __name__)


def generate_project_reference(session, tenant_id):
    """Returns next integer display_id. DB column is INTEGER — no PRJ- string stored."""
    result = session.execute(
        text("""
            SELECT COALESCE(MAX(display_id), 0) as max_id
            FROM "StreemLyne_MT"."Project_Details"
            WHERE tenant_id = :tenant_id
        """),
        {'tenant_id': str(tenant_id)}
    ).fetchone()
    return int(result.max_id or 0) + 1


@project_bp.route('/projects/<int:project_id>', methods=['GET'])
@token_required
@require_tenant
def get_project(tenant_id, employee_id, project_id):
    """Get a specific project with all details including forms and documents"""
    session = SessionLocal()
    try:
        # ✅ UPDATED: Added project_type to SELECT
        query = text("""
            SELECT 
                p.project_id,
                p.display_id,
                p.project_title,
                p.project_type,                    -- ✅ ADDED
                p.project_description,
                p.status,
                p.stage_id,
                p.priority,
                p.start_date,
                p.end_date,
                p.date_of_measure,
                p.assigned_employee_id,
                p.notes,
                p.created_at,
                p.updated_at,
                p.client_id,
                c.client_company_name,
                c.client_contact_name,
                c.client_phone,
                c.client_email,
                c.post_code as client_postcode,
                c.address as client_address,
                s.stage_name,                      
                s.stage_description
            FROM "StreemLyne_MT"."Project_Details" p
            INNER JOIN "StreemLyne_MT"."Client_Master" c 
                ON p.client_id = c.client_id AND p.tenant_id = c.tenant_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master" s 
                ON p.stage_id = s.stage_id
            WHERE p.project_id = :project_id AND p.tenant_id = :tenant_id
        """)
        
        project = session.execute(query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # ✅ STEP 2: Get form submissions for THIS PROJECT ONLY
        forms_query = text("""
            SELECT 
                form_submission_id,
                form_type,
                form_name,
                submission_status,
                approval_status,
                submitted_at,
                form_data,
                token_used
            FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE project_id = :project_id 
              AND tenant_id = :tenant_id
              AND form_type != 'customer_checklist'
            ORDER BY submitted_at DESC
        """)
        
        forms = session.execute(forms_query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        # ✅ STEP 3: Get documents for THIS PROJECT ONLY
        docs_query = text("""
            SELECT 
                id,
                file_name,
                file_url,
                document_category,
                uploaded_at
            FROM "StreemLyne_MT"."Customer_Documents"
            WHERE project_id = :project_id
            ORDER BY uploaded_at DESC
        """)

        docs = session.execute(docs_query, {
            'project_id': project_id
        }).fetchall()
        
        # ✅ STEP 4: Build COMPLETE response with ALL fields
        result = {
            'id': project.project_id,
            'display_id': project.display_id,
            'project_name': project.project_title,
            'project_title': project.project_title,
            'project_type': project.project_type,  
            'project_description': project.project_description or '',
            'client_id': project.client_id,
            'status': project.status or 'Active',
            'stage_id': project.stage_id,
            'stage_name': project.stage_name,  
            'stage': project.stage_name,  
            'priority': project.priority or 'Medium',
            'start_date': project.start_date.isoformat() if project.start_date else None,
            'end_date': project.end_date.isoformat() if project.end_date else None,
            'date_of_measure': project.date_of_measure.isoformat() if project.date_of_measure else None,
            'assigned_employee_id': project.assigned_employee_id,
            'notes': project.notes or '',
            'created_at': project.created_at.isoformat() if project.created_at else None,
            'updated_at': project.updated_at.isoformat() if project.updated_at else None,
            
            # ✅ CUSTOMER OBJECT
            'customer': {
                'id': project.client_id,
                'name': project.client_company_name,
                'contact_name': project.client_contact_name or '',
                'phone': project.client_phone or '',
                'email': project.client_email or '',
                'address': project.client_address or '',  
                'postcode': project.client_postcode or ''
            },
            
            # ✅ Forms array
            'forms': [{
                'id': f.form_submission_id,
                'form_type': f.form_type,
                'form_name': f.form_name,
                'submission_status': f.submission_status,
                'approval_status': f.approval_status,
                'submitted_at': f.submitted_at.isoformat() if f.submitted_at else None,
                'form_data': f.form_data,
                'token_used': f.token_used,
                'project_id': project_id
            } for f in forms],
            
            # ✅ Drawings/Documents array
            'drawings': [{
                'id': str(d.id),
                'filename': d.file_name,
                'url': d.file_url,
                'type': d.document_category or 'other',
                'created_at': d.uploaded_at.isoformat() if d.uploaded_at else None,
                'project_id': project_id
            } for d in docs]
        }
        
        # ✅ DIAGNOSTIC: Log what we're sending
        current_app.logger.info(f"✅ Returning project {project_id} with type={result['project_type']}, stage={result['stage']}")
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching project {project_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@project_bp.route('/projects', methods=['POST'])
@token_required
@require_tenant
def create_project(tenant_id, employee_id):
    """Create a new project"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('client_id'):
            return jsonify({'error': 'client_id is required'}), 400
        
        if not data.get('project_title'):
            return jsonify({'error': 'project_title is required'}), 400
        
        # Verify client exists
        client_query = text("""
            SELECT client_id, client_company_name, address 
            FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': int(data['client_id']),
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Generate display ID
        display_id = generate_project_reference(session, tenant_id)
        
        # ✅ CHANGED: Don't default to stage_id 100, use what's provided or NULL
        stage_id = data.get('stage_id')  # Remove the default
        
        # ✅ ADDED: Validate stage_id if provided
        if stage_id:
            stage_row = session.execute(
                text("""
                    SELECT stage_id, stage_name
                    FROM "StreemLyne_MT"."Stage_Master"
                    WHERE stage_id = :stage_id
                """),
                {'stage_id': int(stage_id)}
            ).fetchone()
            if not stage_row:
                return jsonify({'error': f'Invalid stage_id: {stage_id}'}), 400
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Project_Details"
            (tenant_id, client_id, display_id, project_title, project_type, project_description,
             status, stage_id, priority, start_date, end_date,
             assigned_employee_id, employee_id, notes)
            VALUES (:tenant_id, :client_id, :display_id, :title, :project_type, :description,
                    :status, :stage_id, :priority, :start_date, :end_date,
                    :assigned_to, :employee_id, :notes)
            RETURNING project_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(data['client_id']),
            'display_id': display_id,
            'title': data['project_title'],
            'project_type': data.get('project_type'),  # ✅ ADDED: Accept project_type from request
            'description': data.get('project_description', ''),
            'status': data.get('status', 'Active'),
            'stage_id': stage_id,  # ✅ CHANGED: Can be NULL now
            'priority': data.get('priority', 'Medium'),
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'assigned_to': data.get('assigned_employee_id', employee_id),
            'employee_id': employee_id,
            'notes': data.get('notes', '')
        })
        
        project_id = result.fetchone().project_id
        session.commit()
        
        current_app.logger.info(f"✅ Project {display_id} created with stage_id={stage_id}, project_type={data.get('project_type')}")
        
        return jsonify({
            'success': True,
            'message': 'Project created successfully',
            'project': {
                'id': project_id,
                'display_id': display_id
            }
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating project: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@project_bp.route('/projects/<int:project_id>', methods=['PUT'])
@token_required
@require_tenant
def update_project(tenant_id, employee_id, project_id):
    """Update a project"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'project_id': project_id, 'tenant_id': str(tenant_id)}
        
        updatable = {
            'project_title': 'project_title',
            'project_description': 'project_description',
            'status': 'status',
            'stage_id': 'stage_id',
            'priority': 'priority',
            'start_date': 'start_date',
            'end_date': 'end_date',
            'assigned_employee_id': 'assigned_employee_id',
            'notes': 'notes'
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
            WHERE project_id = :project_id AND tenant_id = :tenant_id
            RETURNING status, stage_id
        """)
        
        result = session.execute(update_query, params)
        updated = result.fetchone()
        
        if not updated:
            return jsonify({'error': 'Project not found'}), 404
        
        session.commit()
        
        current_app.logger.info(f"✅ Project {project_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Project updated successfully',
            'status': updated.status,
            'stage_id': updated.stage_id
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating project: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@project_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_project(tenant_id, employee_id, project_id):
    """Delete a project"""
    session = SessionLocal()
    try:
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Project_Details"
            WHERE project_id = :project_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        })
        session.commit()
        
        current_app.logger.info(f"✅ Project {project_id} deleted")
        
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


@project_bp.route('/projects/<int:project_id>/stage', methods=['PATCH'])
@token_required
@require_tenant
def update_project_stage(tenant_id, employee_id, project_id):
    """Update project stage"""
    session = SessionLocal()
    try:
        data = request.get_json()
        new_stage_id = data.get('stage_id')
        
        if not new_stage_id:
            return jsonify({'error': 'stage_id is required'}), 400
        
        # Verify stage exists and is a project stage (stage_type = 4)
        stage_query = text("""
            SELECT stage_id, stage_name FROM "StreemLyne_MT"."Stage_Master"
            WHERE stage_id = :stage_id AND stage_type = 4
        """)
        stage = session.execute(stage_query, {'stage_id': int(new_stage_id)}).fetchone()
        
        if not stage:
            return jsonify({'error': 'Invalid stage_id. Must be a project stage (stage_type = 4)'}), 400
        
        update_query = text("""
            UPDATE "StreemLyne_MT"."Project_Details"
            SET stage_id = :stage_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = :project_id AND tenant_id = :tenant_id
            RETURNING stage_id
        """)
        
        result = session.execute(update_query, {
            'stage_id': int(new_stage_id),
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Project not found'}), 404
        
        session.commit()
        
        return jsonify({
            'success': True,
            'new_stage_id': new_stage_id,
            'new_stage_name': stage.stage_name
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating project stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@project_bp.route('/projects/stages', methods=['GET'])
@token_required
@require_tenant
def get_project_stages(tenant_id, employee_id):
    """Get all project stages (stage_type = 4)"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT stage_id, stage_name, stage_description, preceding_stage_id
            FROM "StreemLyne_MT"."Stage_Master"
            WHERE stage_type = 4
            ORDER BY stage_id
        """)
        
        stages = session.execute(query).fetchall()
        
        result = [{
            'stage_id': s.stage_id,
            'stage_name': s.stage_name,
            'stage_description': s.stage_description,
            'preceding_stage_id': s.preceding_stage_id
        } for s in stages]
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching stages: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()