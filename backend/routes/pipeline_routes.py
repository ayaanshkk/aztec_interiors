from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.orm import selectinload
from datetime import datetime

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant
from sqlalchemy import text

pipeline_bp = Blueprint('pipeline', __name__)

# Pipeline stage order
PIPELINE_STAGE_ORDER = [
    "Lead", "Survey", "Design", "Quote",
    "Accepted", "Rejected", "Ordered",
    "Production", "Delivery", "Installation",
    "Complete", "Remedial", "Cancelled"
]

@pipeline_bp.route('/pipeline', methods=['GET'])
@token_required
@require_tenant
def get_pipeline_data(tenant_id, employee_id):
    session = SessionLocal()
    try:
        # Single query with JOINs
        pipeline_query = text("""
            WITH client_data AS (
                SELECT 
                    c.client_id,
                    c.client_company_name,
                    c.client_contact_name,
                    c.client_phone,
                    c.client_email,
                    c.stage as client_stage,
                    c.is_allocated,
                    c.is_cleansed,
                    c.created_at,
                    c.project_types,
                    -- Aggregate project data
                    json_agg(DISTINCT jsonb_build_object(
                        'project_id', p.project_id,
                        'project_title', p.project_title,
                        'project_description', p.project_description,
                        'project_type', p.project_type,
                        'date_of_measure', p.date_of_measure,
                        'start_date', p.start_date,
                        'end_date', p.end_date,
                        'status', p.status,
                        'notes', p.notes,
                        'created_at', p.created_at
                    )) FILTER (WHERE p.project_id IS NOT NULL) as projects,
                    -- Aggregate opportunity data
                    json_agg(DISTINCT jsonb_build_object(
                        'opportunity_id', o.opportunity_id,
                        'opportunity_title', o.opportunity_title,
                        'opportunity_description', o.opportunity_description,
                        'process_stage', o.process_stage,
                        'opportunity_value', o.opportunity_value,
                        'start_date', o.start_date,
                        'end_date', o.end_date,
                        'created_at', o.created_at
                    )) FILTER (WHERE o.opportunity_id IS NOT NULL) as opportunities
                FROM "StreemLyne_MT"."Client_Master" c
                LEFT JOIN "StreemLyne_MT"."Project_Details" p 
                    ON p.client_id = c.client_id AND p.tenant_id = :tenant_id
                LEFT JOIN "StreemLyne_MT"."Opportunity_Details" o 
                    ON o.client_id = c.client_id 
                    AND o.tenant_id = :tenant_id 
                    AND o.deleted_at IS NULL
                WHERE c.tenant_id = :tenant_id AND c.is_deleted = false
                GROUP BY c.client_id
                ORDER BY c.created_at DESC
            )
            SELECT * FROM client_data
        """)
        
        results = session.execute(pipeline_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        pipeline_items = []
        
        for row in results:
            # Parse JSON arrays
            projects = row.projects if row.projects else []
            opportunities = row.opportunities if row.opportunities else []
            
            client_stage = row.client_stage or 'Lead'
            
            # Create project items
            for project in projects:
                if project:  # Check not null
                    pipeline_items.append({
                        'id': f'project-{project["project_id"]}',
                        'type': 'project',
                        'stage': client_stage,
                        'customer': {
                            'id': row.client_id,
                            'name': row.client_company_name,
                            'contact_name': row.client_contact_name,
                            'phone': row.client_phone,
                            'email': row.client_email,
                            'created_at': row.created_at.isoformat() if row.created_at else None
                        },
                        'project': {
                            'id': project['project_id'],
                            'title': project['project_title'],
                            'description': project['project_description'],
                            'project_type': project['project_type'],
                            'date_of_measure': project['date_of_measure'],
                            'start_date': project['start_date'],
                            'end_date': project['end_date'],
                            'status': project['status'],
                            'notes': project['notes']
                        }
                    })
            
            # Create opportunity items
            for opp in opportunities:
                if opp:
                    pipeline_items.append({
                        'id': f'opportunity-{opp["opportunity_id"]}',
                        'type': 'opportunity',
                        'stage': client_stage,
                        'customer': {
                            'id': row.client_id,
                            'name': row.client_company_name,
                            'contact_name': row.client_contact_name,
                            'phone': row.client_phone,
                            'email': row.client_email,
                            'created_at': row.created_at.isoformat() if row.created_at else None
                        },
                        'opportunity': {
                            'id': opp['opportunity_id'],
                            'title': opp['opportunity_title'],
                            'description': opp['opportunity_description'],
                            'value': float(opp['opportunity_value']) if opp['opportunity_value'] else None,
                            'start_date': opp['start_date'],
                            'end_date': opp['end_date'],
                            'stage': opp['process_stage']
                        }
                    })
            
            # Pure lead clients
            if not projects and not opportunities:
                pipeline_items.append({
                    'id': f'client-{row.client_id}',
                    'type': 'client',
                    'stage': client_stage,
                    'customer': {
                        'id': row.client_id,
                        'name': row.client_company_name,
                        'contact_name': row.client_contact_name,
                        'phone': row.client_phone,
                        'email': row.client_email,
                        'is_allocated': bool(row.is_allocated),
                        'is_cleansed': bool(row.is_cleansed),
                        'created_at': row.created_at.isoformat() if row.created_at else None,
                        'project_types': row.project_types if row.project_types else []
                    }
                })
        
        return jsonify(pipeline_items), 200
        
    except Exception as e:
        current_app.logger.error(f"❌ Error fetching pipeline: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@pipeline_bp.route('/pipeline/stages', methods=['GET'])
@token_required
@require_tenant
def get_pipeline_stages(tenant_id, employee_id):
    """Get available pipeline stages"""
    return jsonify({
        'stages': PIPELINE_STAGE_ORDER
    }), 200


# ==========================================
# STAGE UPDATE ENDPOINTS
# ==========================================

@pipeline_bp.route('/clients/<int:client_id>/stage', methods=['PATCH'])
@token_required
@require_tenant
def update_client_stage(tenant_id, employee_id, client_id):
    """Update client stage"""
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
            'client_id': client_id,
            'tenant_id': str(tenant_id)
        })
        
        if not result.fetchone():
            return jsonify({'error': 'Client not found'}), 404
        
        session.commit()
        
        current_app.logger.info(f"✅ Client {client_id} stage updated to {new_stage}")
        
        return jsonify({
            'success': True,
            'new_stage': new_stage
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating client stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pipeline_bp.route('/projects/<int:project_id>/stage', methods=['PATCH'])
@token_required
@require_tenant
def update_project_stage(tenant_id, employee_id, project_id):
    """Update project's CLIENT stage (projects don't have their own stage)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400
        
        # Get the client_id for this project
        get_client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Project_Details"
            WHERE project_id = :project_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(get_client_query, {
            'project_id': project_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not result:
            return jsonify({'error': 'Project not found'}), 404
        
        client_id = result.client_id
        
        # Update the CLIENT's stage
        update_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET stage = :stage
            WHERE client_id = :client_id AND tenant_id = :tenant_id
            RETURNING stage
        """)
        
        session.execute(update_query, {
            'stage': new_stage,
            'client_id': client_id,
            'tenant_id': str(tenant_id)
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Project {project_id}'s client stage updated to {new_stage}")
        
        return jsonify({
            'success': True,
            'new_stage': new_stage
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating project stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@pipeline_bp.route('/opportunities/<int:opportunity_id>/stage', methods=['PATCH'])
@token_required
@require_tenant
def update_opportunity_stage(tenant_id, employee_id, opportunity_id):
    """Update opportunity's CLIENT stage"""
    session = SessionLocal()
    try:
        data = request.get_json()
        new_stage = data.get('stage')
        
        if not new_stage:
            return jsonify({'error': 'Stage is required'}), 400
        
        # Get the client_id for this opportunity
        get_client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE opportunity_id = :opportunity_id AND tenant_id = :tenant_id
        """)
        
        result = session.execute(get_client_query, {
            'opportunity_id': opportunity_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not result:
            return jsonify({'error': 'Opportunity not found'}), 404
        
        client_id = result.client_id
        
        # Update the CLIENT's stage
        update_query = text("""
            UPDATE "StreemLyne_MT"."Client_Master"
            SET stage = :stage
            WHERE client_id = :client_id AND tenant_id = :tenant_id
            RETURNING stage
        """)
        
        session.execute(update_query, {
            'stage': new_stage,
            'client_id': client_id,
            'tenant_id': str(tenant_id)
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Opportunity {opportunity_id}'s client stage updated to {new_stage}")
        
        return jsonify({
            'success': True,
            'new_stage': new_stage
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error updating opportunity stage: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()