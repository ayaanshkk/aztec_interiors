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
    - Clients with projects (shows project stage)
    - Clients with opportunities (shows opportunity stage)
    - Pure lead clients (no projects/opportunities)
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
                c.is_cleansed
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
                    start_date,
                    end_date,
                    status
                FROM "StreemLyne_MT"."Project_Details"
                WHERE client_id = :client_id
                ORDER BY created_at DESC
            """)
            
            projects = session.execute(projects_query, {
                'client_id': client.client_id
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
                    end_date
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
            
            # Create cards for each project
            for project in projects:
                total_projects += 1
                project_stage = project.status or 'Lead'
                
                pipeline_items.append({
                    'id': f'project-{project.project_id}',
                    'type': 'project',
                    'stage': project_stage,
                    'client': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email
                    },
                    'project': {
                        'id': project.project_id,
                        'title': project.project_title,
                        'description': project.project_description,
                        'start_date': project.start_date.isoformat() if project.start_date else None,
                        'end_date': project.end_date.isoformat() if project.end_date else None,
                        'status': project_stage
                    }
                })
            
            # Create cards for each opportunity
            for opp in opportunities:
                total_opportunities += 1
                opp_stage = opp.process_stage or 'Not Started'
                
                pipeline_items.append({
                    'id': f'opportunity-{opp.opportunity_id}',
                    'type': 'opportunity',
                    'stage': opp_stage,
                    'client': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email
                    },
                    'opportunity': {
                        'id': opp.opportunity_id,
                        'title': opp.opportunity_title,
                        'description': opp.opportunity_description,
                        'value': float(opp.opportunity_value) if opp.opportunity_value else None,
                        'start_date': opp.start_date.isoformat() if opp.start_date else None,
                        'end_date': opp.end_date.isoformat() if opp.end_date else None,
                        'stage': opp_stage
                    }
                })
            
            # Create card for pure lead (no projects or opportunities)
            if not has_projects and not has_opportunities:
                clients_without_either += 1
                client_stage = client.client_stage or 'Lead'
                
                pipeline_items.append({
                    'id': f'client-{client.client_id}',
                    'type': 'client',
                    'stage': client_stage,
                    'client': {
                        'id': client.client_id,
                        'name': client.client_company_name,
                        'contact_name': client.client_contact_name,
                        'phone': client.client_phone,
                        'email': client.client_email,
                        'is_allocated': bool(client.is_allocated),
                        'is_cleansed': bool(client.is_cleansed)
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