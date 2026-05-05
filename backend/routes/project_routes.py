from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from datetime import datetime

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

project_bp = Blueprint('projects', __name__)


def generate_project_reference(session, tenant_id):
    """Generate sequential project reference like PRJ-001"""
    count_query = text("""
        SELECT COUNT(*) as count FROM "StreemLyne_MT"."Project_Details"
        WHERE tenant_id = :tenant_id
    """)
    
    result = session.execute(count_query, {'tenant_id': str(tenant_id)}).fetchone()
    project_count = result.count if result else 0
    
    reference_number = project_count + 1
    project_reference = f"PRJ-{reference_number:03d}"
    
    # Ensure uniqueness
    while True:
        check_query = text("""
            SELECT project_id FROM "StreemLyne_MT"."Project_Details"
            WHERE display_id = :ref AND tenant_id = :tenant_id
        """)
        exists = session.execute(check_query, {
            'ref': project_reference,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not exists:
            break
        reference_number += 1
        project_reference = f"PRJ-{reference_number:03d}"
    
    return project_reference


@project_bp.route('/projects', methods=['GET'])
@token_required
@require_tenant
def get_projects(tenant_id, employee_id):
    """Get all projects with optional filtering"""
    session = SessionLocal()
    try:
        client_id = request.args.get('client_id')
        status = request.args.get('status')
        stage_id = request.args.get('stage_id')
        
        # Build WHERE conditions
        where_conditions = ["p.tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        if client_id:
            where_conditions.append("p.client_id = :client_id")
            params['client_id'] = int(client_id)
        
        if status:
            where_conditions.append("p.status = :status")
            params['status'] = status
        
        if stage_id:
            where_conditions.append("p.stage_id = :stage_id")
            params['stage_id'] = int(stage_id)
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT 
                p.*,
                c.client_company_name,
                c.client_phone,
                c.client_email,
                c.address as client_address,
                s.stage_name,
                s.stage_description
            FROM "StreemLyne_MT"."Project_Details" p
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON p.client_id = c.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master" s ON p.stage_id = s.stage_id
            WHERE {where_clause}
            ORDER BY p.created_at DESC
        """)
        
        projects = session.execute(query, params).fetchall()
        
        result = []
        for p in projects:
            result.append({
                'id': p.project_id,
                'display_id': p.display_id,
                'project_title': p.project_title,
                'project_description': p.project_description,
                'client_id': p.client_id,
                'client_name': p.client_company_name,
                'status': p.status,
                'stage_id': p.stage_id,
                'stage_name': p.stage_name,
                'priority': p.priority if hasattr(p, 'priority') else None,
                'start_date': p.start_date.isoformat() if p.start_date else None,
                'end_date': p.end_date.isoformat() if p.end_date else None,
                'installation_address': p.client_address,  # Use client's address
                'assigned_employee_id': p.assigned_employee_id,
                'notes': p.notes if hasattr(p, 'notes') else None,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'updated_at': p.updated_at.isoformat() if p.updated_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching projects: {e}")
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
        
        # Default stage_id to 100 (Survey) if not provided
        stage_id = data.get('stage_id', 100)
        
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Project_Details"
            (tenant_id, client_id, display_id, project_title, project_description,
             status, stage_id, priority, start_date, end_date,
             assigned_employee_id, employee_id, notes)
            VALUES (:tenant_id, :client_id, :display_id, :title, :description,
                    :status, :stage_id, :priority, :start_date, :end_date,
                    :assigned_to, :employee_id, :notes)
            RETURNING project_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(data['client_id']),
            'display_id': display_id,
            'title': data['project_title'],
            'description': data.get('project_description', ''),
            'status': data.get('status', 'Active'),
            'stage_id': stage_id,
            'priority': data.get('priority', 'Medium'),
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'assigned_to': data.get('assigned_employee_id', employee_id),
            'employee_id': employee_id,
            'notes': data.get('notes', '')
        })
        
        project_id = result.fetchone().project_id
        session.commit()
        
        current_app.logger.info(f"Project {display_id} created by employee {employee_id}")
        
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
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@project_bp.route('/projects/<int:project_id>', methods=['PUT'])
@token_required
@require_tenant
def update_project(project_id, tenant_id, employee_id):  # ✅ CHANGED ORDER
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
def delete_project(project_id, tenant_id, employee_id):  # ✅ CHANGED ORDER
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
def update_project_stage(project_id, tenant_id, employee_id):  # ✅ CHANGED ORDER
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

@project_bp.route('/projects/<int:project_id>', methods=['GET'])
@token_required
@require_tenant
def get_project(project_id, tenant_id, employee_id):  # ✅ CHANGED ORDER
    """Get a specific project with all details"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.*,
                c.client_company_name,
                c.client_phone,
                c.client_email,
                c.address as client_address,
                s.stage_name,
                s.stage_description
            FROM "StreemLyne_MT"."Project_Details" p
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON p.client_id = c.client_id
            LEFT JOIN "StreemLyne_MT"."Stage_Master" s ON p.stage_id = s.stage_id
            WHERE p.project_id = :project_id AND p.tenant_id = :tenant_id
        """)
        
        project = session.execute(query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        result = {
            'id': project.project_id,
            'display_id': project.display_id,
            'project_title': project.project_title,
            'project_description': project.project_description,
            'client_id': project.client_id,
            'client_name': project.client_company_name,
            'client_phone': project.client_phone,
            'client_email': project.client_email,
            'status': project.status,
            'stage_id': project.stage_id,
            'stage_name': project.stage_name,
            'priority': project.priority if hasattr(project, 'priority') else None,
            'start_date': project.start_date.isoformat() if project.start_date else None,
            'end_date': project.end_date.isoformat() if project.end_date else None,
            'installation_address': project.client_address,
            'assigned_employee_id': project.assigned_employee_id,
            'notes': project.notes if hasattr(project, 'notes') else None,
            'created_at': project.created_at.isoformat() if project.created_at else None,
            'updated_at': project.updated_at.isoformat() if project.updated_at else None
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching project: {e}")
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