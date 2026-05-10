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
    """Get all pipeline items (clients with their projects/opportunities)
    
    Returns pipeline cards for:
    - Clients with projects (shows project details + client stage)
    - Clients with opportunities (shows opportunity details + client stage)
    - Pure lead clients (no projects/opportunities, just client stage)
    """
    session = SessionLocal()
    try:
        current_app.logger.info(f"📊 Fetching pipeline data for tenant {tenant_id}...")
        
        # Get all clients with their projects and opportunities
        clients_query = text("""
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
                c.project_types
            FROM "StreemLyne_MT"."Client_Master" c
            WHERE c.tenant_id = :tenant_id AND c.is_deleted = false
            ORDER BY c.created_at DESC
        """)
        
        clients = session.execute(clients_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        pipeline_items = []
        clients_with_projects = 0
        clients_with_opportunities = 0
        clients_without_either = 0
        total_projects = 0
        total_opportunities = 0
        
        for client in clients:
            # Get projects for this client
            projects_query = text("""
                SELECT 
                    project_id,
                    project_title,
                    project_description,
                    project_type,
                    date_of_measure,
                    start_date,
                    end_date,
                    status,
                    notes,
                    created_at
                FROM "StreemLyne_MT"."Project_Details"
                WHERE client_id = :client_id AND tenant_id = :tenant_id
                ORDER BY created_at DESC
            """)
            
            projects = session.execute(projects_query, {
                'client_id': client.client_id,
                'tenant_id': str(tenant_id)
            }).fetchall()
            
            # Get opportunities for this client
            opportunities_query = text("""
                SELECT 
                    opportunity_id,
                    opportunity_title,
                    opportunity_description,
                    process_stage,
                    opportunity_value,
                    start_date,
                    end_date,
                    created_at
                FROM "StreemLyne_MT"."Opportunity_Details"
                WHERE client_id = :client_id 
                    AND tenant_id = :tenant_id
                    AND deleted_at IS NULL
                ORDER BY created_at DESC
            """)
            
            opportunities = session.execute(opportunities_query, {
                'client_id': client.client_id,
                'tenant_id': str(tenant_id)
            }).fetchall()
            
            has_projects = len(projects) > 0
            has_opportunities = len(opportunities) > 0
            
            # ✅ USE CLIENT STAGE FOR ALL ITEMS (not project status)
            client_stage = client.client_stage or 'Lead'
            
            # Create cards for each project
            for project in projects:
                total_projects += 1
                
                pipeline_items.append({
                    'id': f'project-{project.project_id}',
                    'type': 'project',
                    'stage': client_stage,  # ✅ Use client stage, not project status
                    'customer': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email,
                        'created_at': client.created_at.isoformat() if client.created_at else None
                    },
                    'project': {
                        'id': project.project_id,
                        'title': project.project_title,
                        'description': project.project_description,
                        'project_type': project.project_type,  # ✅ Include project type for colors
                        'date_of_measure': project.date_of_measure.isoformat() if project.date_of_measure else None,
                        'start_date': project.start_date.isoformat() if project.start_date else None,
                        'end_date': project.end_date.isoformat() if project.end_date else None,
                        'status': project.status,
                        'notes': project.notes
                    }
                })
            
            # Create cards for each opportunity
            for opp in opportunities:
                total_opportunities += 1
                
                pipeline_items.append({
                    'id': f'opportunity-{opp.opportunity_id}',
                    'type': 'opportunity',
                    'stage': client_stage,  # ✅ Use client stage
                    'customer': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email,
                        'created_at': client.created_at.isoformat() if client.created_at else None
                    },
                    'opportunity': {
                        'id': opp.opportunity_id,
                        'title': opp.opportunity_title,
                        'description': opp.opportunity_description,
                        'value': float(opp.opportunity_value) if opp.opportunity_value else None,
                        'start_date': opp.start_date.isoformat() if opp.start_date else None,
                        'end_date': opp.end_date.isoformat() if opp.end_date else None,
                        'stage': opp.process_stage
                    }
                })
            
            # Create card for pure lead (no projects or opportunities)
            if not has_projects and not has_opportunities:
                clients_without_either += 1
                
                pipeline_items.append({
                    'id': f'client-{client.client_id}',
                    'type': 'client',
                    'stage': client_stage,
                    'customer': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email,
                        'is_allocated': bool(client.is_allocated),
                        'is_cleansed': bool(client.is_cleansed),
                        'created_at': client.created_at.isoformat() if client.created_at else None,
                        'project_types': client.project_types if client.project_types else []  # ✅ Add this
                    }
                })
            else:
                if has_projects:
                    clients_with_projects += 1
                if has_opportunities:
                    clients_with_opportunities += 1
        
        # Log statistics
        current_app.logger.info(f"✅ Pipeline data fetched: {len(pipeline_items)} items")
        current_app.logger.info(
            f"   📊 Breakdown: {clients_with_projects} clients with {total_projects} projects, "
            f"{clients_with_opportunities} clients with {total_opportunities} opportunities, "
            f"{clients_without_either} pure leads"
        )
        
        # Log stage distribution
        stage_counts = {}
        for item in pipeline_items:
            stage = item.get('stage', 'Unknown')
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        current_app.logger.info(f"📊 Stage distribution: {stage_counts}")
        
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