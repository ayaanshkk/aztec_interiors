from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text, and_
from datetime import datetime, timedelta

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

materials_bp = Blueprint('materials', __name__)


# ==========================================
# PLATFORM ADMIN OR ASSIGNED EMPLOYEE CHECK
# ==========================================

def can_manage_materials(tenant_id, employee_id, session):
    """Check if user is Platform Admin (role_id = 1)"""
    role_query = text("""
        SELECT EXISTS (
            SELECT 1 FROM "StreemLyne_MT"."User_Master" u
            INNER JOIN "StreemLyne_MT"."User_Role_Mapping" urm ON u.user_id = urm.user_id
            WHERE u.employee_id = :employee_id 
                AND u.tenant_id = :tenant_id
                AND urm.role_id = 1
        ) as is_platform_admin
    """)
    
    result = session.execute(role_query, {
        'employee_id': employee_id,
        'tenant_id': str(tenant_id)
    }).fetchone()
    
    return result.is_platform_admin if result else False


# ==========================================
# GET ALL MATERIALS
# ==========================================

@materials_bp.route('/materials', methods=['GET'])
@token_required
@require_tenant
def get_all_materials(tenant_id, employee_id):
    """Get all material orders with optional filtering"""
    session = SessionLocal()
    try:
        # Build WHERE conditions
        where_conditions = ["m.tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        # Filter by client
        client_id = request.args.get('client_id')
        if client_id:
            where_conditions.append("m.client_id = :client_id")
            params['client_id'] = int(client_id)
        
        # Filter by status
        status = request.args.get('status')
        if status:
            where_conditions.append("m.status = :status")
            params['status'] = status
        
        # Filter by date range
        date_from = request.args.get('date_from')
        if date_from:
            where_conditions.append("m.order_date >= :date_from")
            params['date_from'] = date_from
        
        date_to = request.args.get('date_to')
        if date_to:
            where_conditions.append("m.order_date <= :date_to")
            params['date_to'] = date_to
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT 
                m.*,
                c.client_company_name
            FROM "StreemLyne_MT"."Material_Orders" m
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON m.client_id = c.client_id
            WHERE {where_clause}
            ORDER BY m.created_at DESC
        """)
        
        materials = session.execute(query, params).fetchall()
        
        result = []
        for m in materials:
            result.append({
                'material_id': m.material_id,
                'client_id': m.client_id,
                'client_name': m.client_company_name,
                'contract_id': m.contract_id,
                'material_description': m.material_description,
                'supplier_name': m.supplier_name,
                'supplier_reference': m.supplier_reference,
                'status': m.status,
                'order_date': m.order_date.isoformat() if m.order_date else None,
                'expected_delivery_date': m.expected_delivery_date.isoformat() if m.expected_delivery_date else None,
                'actual_delivery_date': m.actual_delivery_date.isoformat() if m.actual_delivery_date else None,
                'estimated_cost': float(m.estimated_cost) if m.estimated_cost else None,
                'actual_cost': float(m.actual_cost) if m.actual_cost else None,
                'notes': m.notes,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'updated_at': m.updated_at.isoformat() if m.updated_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching materials: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# GET SINGLE MATERIAL
# ==========================================

@materials_bp.route('/materials/<int:material_id>', methods=['GET'])
@token_required
@require_tenant
def get_material(material_id, tenant_id, employee_id):
    """Get single material order by ID"""
    session = SessionLocal()
    try:
        query = text("""
            SELECT 
                m.*,
                c.client_company_name,
                c.client_email,
                c.client_phone
            FROM "StreemLyne_MT"."Material_Orders" m
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON m.client_id = c.client_id
            WHERE m.material_id = :material_id AND m.tenant_id = :tenant_id
        """)
        
        material = session.execute(query, {
            'material_id': material_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not material:
            return jsonify({'error': 'Material order not found'}), 404
        
        result = {
            'material_id': material.material_id,
            'client_id': material.client_id,
            'client_name': material.client_company_name,
            'client_email': material.client_email,
            'client_phone': material.client_phone,
            'contract_id': material.contract_id,
            'material_description': material.material_description,
            'supplier_name': material.supplier_name,
            'supplier_reference': material.supplier_reference,
            'status': material.status,
            'order_date': material.order_date.isoformat() if material.order_date else None,
            'expected_delivery_date': material.expected_delivery_date.isoformat() if material.expected_delivery_date else None,
            'actual_delivery_date': material.actual_delivery_date.isoformat() if material.actual_delivery_date else None,
            'estimated_cost': float(material.estimated_cost) if material.estimated_cost else None,
            'actual_cost': float(material.actual_cost) if material.actual_cost else None,
            'notes': material.notes,
            'created_at': material.created_at.isoformat() if material.created_at else None,
            'updated_at': material.updated_at.isoformat() if material.updated_at else None
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching material: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# GET MATERIALS BY CLIENT
# ==========================================

@materials_bp.route('/materials/client/<int:client_id>', methods=['GET'])
@token_required
@require_tenant
def get_client_materials(client_id, tenant_id, employee_id):
    """Get all material orders for a specific client"""
    session = SessionLocal()
    try:
        # Verify client exists
        client_query = text("""
            SELECT client_id, client_company_name 
            FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': client_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Get all materials for this client
        materials_query = text("""
            SELECT * FROM "StreemLyne_MT"."Material_Orders"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
            ORDER BY created_at DESC
        """)
        
        materials = session.execute(materials_query, {
            'client_id': client_id,
            'tenant_id': str(tenant_id)
        }).fetchall()
        
        # Calculate summary
        any_ordered = any(m.status != 'not_ordered' for m in materials)
        all_delivered = all(m.status == 'delivered' for m in materials) if materials else False
        pending_deliveries = sum(1 for m in materials if m.status in ['ordered', 'in_transit'])
        
        return jsonify({
            'client_id': client_id,
            'client_name': client.client_company_name,
            'materials': [{
                'material_id': m.material_id,
                'material_description': m.material_description,
                'supplier_name': m.supplier_name,
                'status': m.status,
                'order_date': m.order_date.isoformat() if m.order_date else None,
                'expected_delivery_date': m.expected_delivery_date.isoformat() if m.expected_delivery_date else None,
                'estimated_cost': float(m.estimated_cost) if m.estimated_cost else None
            } for m in materials],
            'summary': {
                'total_orders': len(materials),
                'modifications_safe': not any_ordered,
                'all_delivered': all_delivered,
                'pending_deliveries': pending_deliveries
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching client materials: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# CREATE MATERIAL ORDER
# ==========================================

@materials_bp.route('/materials', methods=['POST'])
@token_required
@require_tenant
def create_material_order(tenant_id, employee_id):
    """Create a new material order"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('client_id'):
            return jsonify({'error': 'client_id is required'}), 400
        if not data.get('material_description'):
            return jsonify({'error': 'material_description is required'}), 400
        
        # Verify client exists
        client_query = text("""
            SELECT client_id FROM "StreemLyne_MT"."Client_Master"
            WHERE client_id = :client_id AND tenant_id = :tenant_id
        """)
        client = session.execute(client_query, {
            'client_id': int(data['client_id']),
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not client:
            return jsonify({'error': 'Client not found'}), 404
        
        # Parse dates
        order_date = data.get('order_date')
        if order_date:
            try:
                order_date = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
            except:
                order_date = None
        
        expected_delivery_date = data.get('expected_delivery_date')
        if expected_delivery_date:
            try:
                expected_delivery_date = datetime.fromisoformat(expected_delivery_date.replace('Z', '+00:00'))
            except:
                expected_delivery_date = None
        
        # Insert material order
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Material_Orders"
            (tenant_id, client_id, contract_id, ordered_by_employee_id,
             material_description, supplier_name, supplier_reference, status,
             order_date, expected_delivery_date, estimated_cost, notes)
            VALUES (:tenant_id, :client_id, :contract_id, :ordered_by,
                    :description, :supplier_name, :supplier_ref, :status,
                    :order_date, :expected_delivery, :estimated_cost, :notes)
            RETURNING material_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(data['client_id']),
            'contract_id': data.get('contract_id'),
            'ordered_by': employee_id,
            'description': data['material_description'],
            'supplier_name': data.get('supplier_name'),
            'supplier_ref': data.get('supplier_reference'),
            'status': data.get('status', 'not_ordered'),
            'order_date': order_date,
            'expected_delivery': expected_delivery_date,
            'estimated_cost': data.get('estimated_cost'),
            'notes': data.get('notes')
        })
        
        material_id = result.fetchone().material_id
        session.commit()
        
        current_app.logger.info(f"Material order {material_id} created for client {data['client_id']}")
        
        return jsonify({
            'success': True,
            'message': 'Material order created successfully',
            'material_id': material_id
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating material order: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# UPDATE MATERIAL ORDER
# ==========================================

@materials_bp.route('/materials/<int:material_id>', methods=['PATCH'])
@token_required
@require_tenant
def update_material_order(material_id, tenant_id, employee_id):
    """Update a material order"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        update_fields = []
        params = {'material_id': material_id, 'tenant_id': str(tenant_id)}
        
        updatable = {
            'material_description': 'material_description',
            'supplier_name': 'supplier_name',
            'supplier_reference': 'supplier_reference',
            'status': 'status',
            'order_date': 'order_date',
            'expected_delivery_date': 'expected_delivery_date',
            'actual_delivery_date': 'actual_delivery_date',
            'estimated_cost': 'estimated_cost',
            'actual_cost': 'actual_cost',
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
            UPDATE "StreemLyne_MT"."Material_Orders"
            SET {', '.join(update_fields)}
            WHERE material_id = :material_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_query, params)
        session.commit()
        
        current_app.logger.info(f"Material order {material_id} updated")
        
        return jsonify({
            'success': True,
            'message': 'Material order updated successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating material order: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# DELETE MATERIAL ORDER
# ==========================================

@materials_bp.route('/materials/<int:material_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_material_order(material_id, tenant_id, employee_id):
    """Delete a material order (Platform Admin only)"""
    session = SessionLocal()
    try:
        # Check if user is Platform Admin
        if not can_manage_materials(tenant_id, employee_id, session):
            return jsonify({'error': 'Unauthorized - Platform Admin access required'}), 403
        
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Material_Orders"
            WHERE material_id = :material_id AND tenant_id = :tenant_id
        """)
        
        session.execute(delete_query, {
            'material_id': material_id,
            'tenant_id': str(tenant_id)
        })
        session.commit()
        
        current_app.logger.info(f"Material order {material_id} deleted")
        
        return jsonify({
            'success': True,
            'message': 'Material order deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting material order: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ==========================================
# DASHBOARD OVERVIEW
# ==========================================

@materials_bp.route('/materials/dashboard/overview', methods=['GET'])
@token_required
@require_tenant
def materials_dashboard_overview(tenant_id, employee_id):
    """Get overview of all materials for dashboard"""
    session = SessionLocal()
    try:
        # Get counts by status
        status_query = text("""
            SELECT 
                status,
                COUNT(*) as count
            FROM "StreemLyne_MT"."Material_Orders"
            WHERE tenant_id = :tenant_id
            GROUP BY status
        """)
        
        status_counts = session.execute(status_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        # Get upcoming deliveries
        today = datetime.utcnow()
        week_end = today + timedelta(days=7)
        
        upcoming_query = text("""
            SELECT 
                m.material_id,
                m.material_description,
                m.expected_delivery_date,
                m.status,
                c.client_company_name
            FROM "StreemLyne_MT"."Material_Orders" m
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON m.client_id = c.client_id
            WHERE m.tenant_id = :tenant_id
                AND m.expected_delivery_date BETWEEN :today AND :week_end
                AND m.status IN ('ordered', 'in_transit')
            ORDER BY m.expected_delivery_date ASC
        """)
        
        upcoming = session.execute(upcoming_query, {
            'tenant_id': str(tenant_id),
            'today': today,
            'week_end': week_end
        }).fetchall()
        
        return jsonify({
            'status_counts': {row.status: row.count for row in status_counts},
            'deliveries': {
                'expected_this_week': len(upcoming),
                'upcoming_deliveries': [{
                    'material_id': u.material_id,
                    'description': u.material_description,
                    'client_name': u.client_company_name,
                    'expected_date': u.expected_delivery_date.isoformat() if u.expected_delivery_date else None
                } for u in upcoming]
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching dashboard: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()