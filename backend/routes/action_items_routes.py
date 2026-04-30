from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

action_items_bp = Blueprint('action_items', __name__)

@action_items_bp.route('/action-items', methods=['GET'])
@token_required
@require_tenant
def get_action_items(tenant_id, employee_id):
    """Get all pending action items for the tenant"""
    session = SessionLocal()
    try:
        # Query action items with client details
        query = text("""
            SELECT 
                ai.id,
                ai.client_id,
                ai.stage,
                ai.priority,
                ai.created_at,
                ai.completed,
                ai.completed_at,
                ai.notes,
                cm.client_company_name,
                cm.client_contact_name,
                cm.client_email,
                cm.client_phone
            FROM "StreemLyne_MT"."Action_Items" ai
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm 
                ON ai.client_id = cm.client_id 
                AND ai.tenant_id = cm.tenant_id
            WHERE ai.tenant_id = :tenant_id
                AND ai.completed = false
            ORDER BY 
                CASE ai.priority 
                    WHEN 'High' THEN 1 
                    WHEN 'Medium' THEN 2 
                    WHEN 'Low' THEN 3 
                END,
                ai.created_at DESC
        """)
        
        result = session.execute(query, {'tenant_id': str(tenant_id)})
        action_items = result.fetchall()
        
        return jsonify([{
            'id': str(item.id),
            'customer_name': item.client_company_name or 'Unknown',
            'customer_contact': item.client_contact_name,
            'customer_id': item.client_id,
            'customer_email': item.client_email,
            'customer_phone': item.client_phone,
            'stage': item.stage,
            'priority': item.priority,
            'notes': item.notes,
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'completed': item.completed,
            'completed_at': item.completed_at.isoformat() if item.completed_at else None
        } for item in action_items])
    except Exception as e:
        print(f"Error fetching action items: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items/<string:action_id>/complete', methods=['PATCH'])
@token_required
@require_tenant
def complete_action_item(action_id, tenant_id, employee_id):
    """Mark an action item as completed"""
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        completion_notes = data.get('notes', '')
        
        query = text("""
            UPDATE "StreemLyne_MT"."Action_Items"
            SET 
                completed = true,
                completed_at = :completed_at,
                completed_by_employee_id = :employee_id,
                notes = CASE 
                    WHEN :completion_notes != '' 
                    THEN COALESCE(notes || E'\n\n', '') || 'Completed: ' || :completion_notes
                    ELSE notes
                END
            WHERE id = :action_id
                AND tenant_id = :tenant_id
            RETURNING id
        """)
        
        result = session.execute(query, {
            'action_id': action_id,
            'tenant_id': str(tenant_id),
            'completed_at': datetime.utcnow(),
            'employee_id': employee_id,
            'completion_notes': completion_notes
        })
        
        updated = result.fetchone()
        
        if not updated:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.commit()
        
        return jsonify({'message': 'Action item marked as completed'})
    except Exception as e:
        print(f"Error completing action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items', methods=['POST'])
@token_required
@require_tenant
def create_action_item(tenant_id, employee_id):
    """Create a new action item"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('client_id'):
            return jsonify({'error': 'client_id is required'}), 400
        
        # Check if client exists and belongs to this tenant
        client_check = text("""
            SELECT client_id 
            FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id 
                AND tenant_id = :tenant_id
                AND is_deleted = false
        """)
        
        client = session.execute(client_check, {
            'client_id': data['client_id'],
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Check if action item already exists for this client and stage
        stage = data.get('stage', 'Accepted')
        existing_check = text("""
            SELECT id 
            FROM "StreemLyne_MT"."Action_Items"
            WHERE client_id = :client_id
                AND tenant_id = :tenant_id
                AND stage = :stage
                AND completed = false
        """)
        
        existing = session.execute(existing_check, {
            'client_id': data['client_id'],
            'tenant_id': str(tenant_id),
            'stage': stage
        }).fetchone()
        
        if existing:
            return jsonify({
                'message': 'Action item already exists',
                'id': str(existing.id)
            }), 200
        
        # Create new action item
        action_id = str(uuid.uuid4())
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Action_Items" (
                id, 
                tenant_id, 
                client_id, 
                stage, 
                priority, 
                completed,
                created_by_employee_id,
                notes
            ) VALUES (
                :id,
                :tenant_id,
                :client_id,
                :stage,
                :priority,
                false,
                :employee_id,
                :notes
            )
        """)
        
        session.execute(insert_query, {
            'id': action_id,
            'tenant_id': str(tenant_id),
            'client_id': data['client_id'],
            'stage': stage,
            'priority': data.get('priority', 'High'),
            'employee_id': employee_id,
            'notes': data.get('notes', '')
        })
        
        session.commit()
        
        return jsonify({
            'message': 'Action item created successfully',
            'id': action_id
        }), 201
    except Exception as e:
        print(f"Error creating action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items/<string:action_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_action_item(action_id, tenant_id, employee_id):
    """Delete an action item"""
    session = SessionLocal()
    try:
        query = text("""
            DELETE FROM "StreemLyne_MT"."Action_Items"
            WHERE id = :action_id
                AND tenant_id = :tenant_id
            RETURNING id
        """)
        
        result = session.execute(query, {
            'action_id': action_id,
            'tenant_id': str(tenant_id)
        })
        
        deleted = result.fetchone()
        
        if not deleted:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.commit()
        
        return jsonify({'message': 'Action item deleted successfully'})
    except Exception as e:
        print(f"Error deleting action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items/<string:action_id>', methods=['PATCH'])
@token_required
@require_tenant
def update_action_item(action_id, tenant_id, employee_id):
    """Update an action item's details"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Build dynamic update query
        update_fields = []
        params = {
            'action_id': action_id,
            'tenant_id': str(tenant_id)
        }
        
        if 'priority' in data:
            update_fields.append("priority = :priority")
            params['priority'] = data['priority']
        
        if 'notes' in data:
            update_fields.append("notes = :notes")
            params['notes'] = data['notes']
        
        if 'stage' in data:
            update_fields.append("stage = :stage")
            params['stage'] = data['stage']
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        query = text(f"""
            UPDATE "StreemLyne_MT"."Action_Items"
            SET {', '.join(update_fields)}
            WHERE id = :action_id
                AND tenant_id = :tenant_id
            RETURNING id
        """)
        
        result = session.execute(query, params)
        updated = result.fetchone()
        
        if not updated:
            return jsonify({'error': 'Action item not found'}), 404
        
        session.commit()
        
        return jsonify({'message': 'Action item updated successfully'})
    except Exception as e:
        print(f"Error updating action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()