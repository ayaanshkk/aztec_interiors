from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
import json

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant

quotation_bp = Blueprint('quotations', __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_quotation_total(session, quotation_id):
    """Calculate total from quotation items"""
    query = text("""
        SELECT COALESCE(SUM(amount * quantity), 0) as total
        FROM "StreemLyne_MT"."Quotation_Items"
        WHERE quotation_id = :quotation_id
    """)
    
    result = session.execute(query, {'quotation_id': quotation_id}).fetchone()
    return float(result.total) if result else 0.0


def find_price_for_item(session, tenant_id, item_name, category='bedroom', color=None):
    """
    Find matching price from PriceList_Master
    Returns (price, pricelist_id, dimension_formula, needs_manual_pricing)
    """
    try:
        current_app.logger.info(f"🔍 Searching for '{item_name}' in category '{category}'")
        
        # Name mappings for common items
        name_mappings = {
            'door': ['Door', 'Wardrobe Door'],
            'bedside': ['Bedside', 'Bedside Cabinet'],
            'dresser': ['Dresser'],
            'mirror': ['Mirror'],
            'panel': ['Panel', 'End Panel'],
            'plinth': ['Plinth'],
            'handle': ['Handle'],
            'worktop': ['Worktop'],
            'sink': ['Sink'],
            'tap': ['Tap']
        }
        
        item_lower = item_name.lower().strip()
        search_terms = name_mappings.get(item_lower, [item_name])
        
        # Search for matching items
        for term in search_terms:
            query = text("""
                SELECT pricelist_id, item_name, base_price, dimension_formula
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND category = :category
                    AND LOWER(item_name) LIKE LOWER(:search_term)
                ORDER BY base_price ASC
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'category': category,
                'search_term': f'%{term}%'
            }).fetchone()
            
            if result:
                current_app.logger.info(f"✅ Found: {result.item_name} - £{result.base_price}")
                return (
                    float(result.base_price),
                    result.pricelist_id,
                    result.dimension_formula,
                    False  # Has price
                )
        
        # No match
        current_app.logger.warning(f"⚠️ No price found for: {item_name}")
        return (0.0, None, None, True)  # Needs manual pricing
        
    except Exception as e:
        current_app.logger.error(f"❌ Error finding price: {e}")
        return (0.0, None, None, True)


# ============================================================================
# GET/CREATE QUOTATIONS
# ============================================================================

@quotation_bp.route('/quotations', methods=['GET'])
@token_required
@require_tenant
def get_quotations(tenant_id, employee_id):
    """Get all quotations with optional filters"""
    session = SessionLocal()
    try:
        # Build WHERE clause
        where_conditions = ["q.tenant_id = :tenant_id"]
        params = {'tenant_id': str(tenant_id)}
        
        # Filter by client
        client_id = request.args.get('client_id')
        if client_id:
            where_conditions.append("q.client_id = :client_id")
            params['client_id'] = int(client_id)
        
        # Filter by project
        project_id = request.args.get('project_id')
        if project_id:
            where_conditions.append("q.project_id = :project_id")
            params['project_id'] = int(project_id)
        
        where_clause = " AND ".join(where_conditions)
        
        query = text(f"""
            SELECT 
                q.*,
                c.client_company_name,
                (SELECT COUNT(*) FROM "StreemLyne_MT"."Quotation_Items" 
                 WHERE quotation_id = q.quotation_id) as items_count
            FROM "StreemLyne_MT"."Quotations" q
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
            WHERE {where_clause}
            ORDER BY q.created_at DESC
        """)
        
        quotations = session.execute(query, params).fetchall()
        
        result = []
        for q in quotations:
            result.append({
                'quotation_id': q.quotation_id,
                'reference_number': q.reference_number,
                'client_id': q.client_id,
                'client_name': q.client_company_name,
                'project_id': q.project_id,
                'total': float(q.total) if q.total else 0.0,
                'status': q.status,
                'notes': q.notes,
                'items_count': q.items_count or 0,
                'created_at': q.created_at.isoformat() if q.created_at else None,
                'updated_at': q.updated_at.isoformat() if q.updated_at else None
            })
        
        return jsonify(result), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching quotations: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@quotation_bp.route('/quotations', methods=['POST'])
@token_required
@require_tenant
def create_quotation(tenant_id, employee_id):
    """Create a new quotation"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Validate
        if not data.get('client_id'):
            return jsonify({'error': 'client_id is required'}), 400
        
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
        
        # Generate reference number
        count_query = text("""
            SELECT COUNT(*) as count FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tenant_id
        """)
        count = session.execute(count_query, {'tenant_id': str(tenant_id)}).fetchone().count
        ref_num = f"Q-{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:03d}"
        
        # Calculate total from items
        items_data = data.get('items', [])
        total = sum(
            float(item.get('amount', 0)) * int(item.get('quantity', 1))
            for item in items_data
        )
        
        # Create quotation
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Quotations"
            (tenant_id, client_id, project_id, reference_number, total, status, notes, employee_id)
            VALUES (:tenant_id, :client_id, :project_id, :reference_number, :total, :status, :notes, :employee_id)
            RETURNING quotation_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': int(data['client_id']),
            'project_id': data.get('project_id'),
            'reference_number': ref_num,
            'total': total,
            'status': data.get('status', 'Draft'),
            'notes': data.get('notes', ''),
            'employee_id': employee_id
        })
        
        quotation_id = result.fetchone().quotation_id
        
        # Add items
        for item in items_data:
            item_insert = text("""
                INSERT INTO "StreemLyne_MT"."Quotation_Items"
                (quotation_id, item_name, description, color, quantity, amount,
                 width, height, depth, needs_manual_pricing, pricelist_id)
                VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                        :width, :height, :depth, :needs_manual, :pricelist_id)
            """)
            
            session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item.get('item', ''),
                'description': item.get('description', ''),
                'color': item.get('color'),
                'quantity': item.get('quantity', 1),
                'amount': item.get('amount', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('price_list_item_id')
            })
        
        session.commit()
        
        current_app.logger.info(f"Quotation {ref_num} created")
        
        return jsonify({
            'quotation_id': quotation_id,
            'reference_number': ref_num,
            'message': 'Quotation created successfully'
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error creating quotation: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# GENERATE FROM CHECKLIST
# ============================================================================

@quotation_bp.route('/quotations/generate-from-checklist/<int:form_submission_id>', methods=['POST'])
@token_required
@require_tenant  
def generate_from_checklist(form_submission_id, tenant_id, employee_id):
    """Generate quotation from checklist form submission"""
    session = SessionLocal()
    try:
        current_app.logger.info(f"📋 Generating quote from submission {form_submission_id}")
        
        # Get form submission
        form_query = text("""
            SELECT * FROM "StreemLyne_MT"."Customer_Form_Submissions"
            WHERE submission_id = :submission_id AND tenant_id = :tenant_id
        """)
        
        form = session.execute(form_query, {
            'submission_id': form_submission_id,
            'tenant_id': str(tenant_id)
        }).fetchone()
        
        if not form:
            return jsonify({'error': 'Form submission not found'}), 404
        
        # Check if quote already exists
        existing_query = text("""
            SELECT quotation_id, reference_number, total
            FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tenant_id
                AND reference_number LIKE :pattern
        """)
        
        existing = session.execute(existing_query, {
            'tenant_id': str(tenant_id),
            'pattern': f'%{form_submission_id}%'
        }).fetchone()
        
        if existing:
            return jsonify({
                'success': True,
                'quotation_id': existing.quotation_id,
                'reference_number': existing.reference_number,
                'total': float(existing.total) if existing.total else 0,
                'message': 'Quote already exists for this checklist'
            }), 200
        
        # Parse form data
        form_data = json.loads(form.form_data) if isinstance(form.form_data, str) else form.form_data
        form_type = form_data.get('form_type', '').lower()
        checklist_type = 'kitchen' if 'kitchen' in form_type else 'bedroom'
        
        # Generate reference
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        ref_num = f"Q-{timestamp}-{form_submission_id}"
        
        # Create quotation
        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Quotations"
            (tenant_id, client_id, reference_number, total, status, notes, employee_id)
            VALUES (:tenant_id, :client_id, :reference_number, 0, 'Draft', :notes, :employee_id)
            RETURNING quotation_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': form.client_id,
            'reference_number': ref_num,
            'notes': f"Auto-generated from {checklist_type} checklist",
            'employee_id': employee_id
        })
        
        quotation_id = result.fetchone().quotation_id
        
        # Extract and add items
        extracted_items = extract_checklist_items(form_data, checklist_type, session, tenant_id)
        
        total = 0.0
        matched_count = 0
        manual_count = 0
        
        item_insert = text("""
            INSERT INTO "StreemLyne_MT"."Quotation_Items"
            (quotation_id, item_name, description, color, quantity, amount,
             width, height, depth, needs_manual_pricing, pricelist_id)
            VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                    :width, :height, :depth, :needs_manual, :pricelist_id)
        """)
        
        for item in extracted_items:
            session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item['item_name'],
                'description': item['description'],
                'color': item.get('color'),
                'quantity': item.get('quantity', 1),
                'amount': item.get('price', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('pricelist_id')
            })
            
            total += item.get('price', 0) * item.get('quantity', 1)
            
            if item.get('needs_manual_pricing'):
                manual_count += 1
            else:
                matched_count += 1
        
        # Update total
        update_total = text("""
            UPDATE "StreemLyne_MT"."Quotations"
            SET total = :total
            WHERE quotation_id = :quotation_id
        """)
        
        session.execute(update_total, {
            'total': total,
            'quotation_id': quotation_id
        })
        
        session.commit()
        
        current_app.logger.info(f"✅ Quote {ref_num}: {matched_count} auto-priced, {manual_count} manual")
        
        return jsonify({
            'success': True,
            'quotation_id': quotation_id,
            'reference_number': ref_num,
            'items_count': len(extracted_items),
            'matched_items': matched_count,
            'manual_items': manual_count,
            'total': total,
            'checklist_type': checklist_type,
            'message': f'Quote generated: {matched_count} auto-priced, {manual_count} need manual pricing'
        }), 201
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error generating quotation: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def extract_checklist_items(form_data, checklist_type, session, tenant_id):
    """Extract billable items from checklist with auto-pricing"""
    items = []
    
    # Main door
    if form_data.get('door_style') and form_data.get('door_color'):
        price, pricelist_id, formula, needs_manual = find_price_for_item(
            session, tenant_id, 'door', checklist_type, form_data.get('door_color')
        )
        
        items.append({
            'item_name': 'Door',
            'description': f"{form_data.get('door_style')} - {form_data.get('door_name', '')}",
            'color': form_data.get('door_color', ''),
            'quantity': 1,
            'price': price,
            'needs_manual_pricing': needs_manual,
            'pricelist_id': pricelist_id
        })
    
    # Additional doors
    for idx, door in enumerate(form_data.get('additional_doors', [])):
        if door.get('door_style'):
            price, pricelist_id, formula, needs_manual = find_price_for_item(
                session, tenant_id, 'door', checklist_type
            )
            
            items.append({
                'item_name': f'Additional Door {idx + 1}',
                'description': door.get('door_style', ''),
                'color': door.get('door_color', ''),
                'quantity': int(door.get('quantity', 1)),
                'price': price,
                'needs_manual_pricing': needs_manual,
                'pricelist_id': pricelist_id
            })
    
    # Panels
    if form_data.get('end_panel_color'):
        price, pricelist_id, formula, needs_manual = find_price_for_item(
            session, tenant_id, 'panel', checklist_type
        )
        
        items.append({
            'item_name': 'End Panel',
            'description': 'End Panel',
            'color': form_data.get('end_panel_color'),
            'quantity': 1,
            'price': price,
            'needs_manual_pricing': needs_manual,
            'pricelist_id': pricelist_id
        })
    
    # Handles
    if form_data.get('handles_code'):
        price, pricelist_id, formula, needs_manual = find_price_for_item(
            session, tenant_id, 'handle', checklist_type
        )
        
        items.append({
            'item_name': 'Handles',
            'description': f"Code: {form_data.get('handles_code')}",
            'quantity': int(form_data.get('handles_quantity', 1)),
            'price': price,
            'needs_manual_pricing': needs_manual,
            'pricelist_id': pricelist_id
        })
    
    # Bedroom specific
    if checklist_type == 'bedroom':
        if form_data.get('bedside_cabinets_type'):
            price, pricelist_id, formula, needs_manual = find_price_for_item(
                session, tenant_id, 'bedside', checklist_type
            )
            
            items.append({
                'item_name': 'Bedside Cabinets',
                'description': form_data.get('bedside_cabinets_type'),
                'quantity': int(form_data.get('bedside_cabinets_qty', 1)),
                'price': price,
                'needs_manual_pricing': needs_manual,
                'pricelist_id': pricelist_id
            })
    
    # Kitchen specific
    elif checklist_type == 'kitchen':
        if form_data.get('worktop_material_type'):
            price, pricelist_id, formula, needs_manual = find_price_for_item(
                session, tenant_id, 'worktop', checklist_type
            )
            
            items.append({
                'item_name': 'Worktop',
                'description': form_data.get('worktop_material_type'),
                'color': form_data.get('worktop_material_color', ''),
                'quantity': 1,
                'price': price,
                'needs_manual_pricing': needs_manual,
                'pricelist_id': pricelist_id
            })
    
    current_app.logger.info(f"📊 Extracted {len(items)} items")
    
    return items


# ============================================================================
# SINGLE QUOTATION OPERATIONS
# ============================================================================

@quotation_bp.route('/quotations/<int:quotation_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
@require_tenant
def handle_quotation(quotation_id, tenant_id, employee_id):
    """Get, update, or delete a quotation"""
    session = SessionLocal()
    try:
        if request.method == 'GET':
            # Get quotation with items
            quote_query = text("""
                SELECT 
                    q.*,
                    c.client_company_name,
                    c.address as client_address,
                    c.client_phone
                FROM "StreemLyne_MT"."Quotations" q
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
                WHERE q.quotation_id = :quotation_id AND q.tenant_id = :tenant_id
            """)
            
            quote = session.execute(quote_query, {
                'quotation_id': quotation_id,
                'tenant_id': str(tenant_id)
            }).fetchone()
            
            if not quote:
                return jsonify({'error': 'Quotation not found'}), 404
            
            # Get items
            items_query = text("""
                SELECT * FROM "StreemLyne_MT"."Quotation_Items"
                WHERE quotation_id = :quotation_id
                ORDER BY item_id
            """)
            
            items = session.execute(items_query, {'quotation_id': quotation_id}).fetchall()
            
            result = {
                'quotation_id': quote.quotation_id,
                'reference_number': quote.reference_number,
                'client_id': quote.client_id,
                'client_name': quote.client_company_name,
                'client_address': quote.client_address,
                'client_phone': quote.client_phone,
                'project_id': quote.project_id,
                'total': float(quote.total) if quote.total else 0,
                'status': quote.status,
                'notes': quote.notes,
                'created_at': quote.created_at.isoformat() if quote.created_at else None,
                'items': [{
                    'item_id': i.item_id,
                    'item_name': i.item_name,
                    'description': i.description,
                    'color': i.color,
                    'quantity': i.quantity,
                    'amount': float(i.amount) if i.amount else 0,
                    'width': i.width,
                    'height': i.height,
                    'depth': i.depth,
                    'needs_manual_pricing': i.needs_manual_pricing
                } for i in items]
            }
            
            return jsonify(result), 200
        
        elif request.method == 'PUT':
            # Update quotation
            data = request.get_json()
            
            update_fields = []
            params = {'quotation_id': quotation_id, 'tenant_id': str(tenant_id)}
            
            if 'status' in data:
                update_fields.append("status = :status")
                params['status'] = data['status']
            if 'notes' in data:
                update_fields.append("notes = :notes")
                params['notes'] = data['notes']
            if 'total' in data:
                update_fields.append("total = :total")
                params['total'] = data['total']
            
            if not update_fields:
                return jsonify({'error': 'No fields to update'}), 400
            
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            
            update_query = text(f"""
                UPDATE "StreemLyne_MT"."Quotations"
                SET {', '.join(update_fields)}
                WHERE quotation_id = :quotation_id AND tenant_id = :tenant_id
            """)
            
            session.execute(update_query, params)
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Quotation updated'
            }), 200
        
        elif request.method == 'DELETE':
            # Delete items first
            delete_items = text("""
                DELETE FROM "StreemLyne_MT"."Quotation_Items"
                WHERE quotation_id = :quotation_id
            """)
            session.execute(delete_items, {'quotation_id': quotation_id})
            
            # Delete quotation
            delete_quote = text("""
                DELETE FROM "StreemLyne_MT"."Quotations"
                WHERE quotation_id = :quotation_id AND tenant_id = :tenant_id
            """)
            session.execute(delete_quote, {
                'quotation_id': quotation_id,
                'tenant_id': str(tenant_id)
            })
            
            session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Quotation deleted'
            }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error handling quotation: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


# ============================================================================
# DELETE QUOTATION ITEM
# ============================================================================

@quotation_bp.route('/quotations/<int:quotation_id>/items/<int:item_id>', methods=['DELETE'])
@token_required
@require_tenant
def delete_quotation_item(quotation_id, item_id, tenant_id, employee_id):
    """Delete a single quotation item and recalculate total"""
    session = SessionLocal()
    try:
        # Delete item
        delete_query = text("""
            DELETE FROM "StreemLyne_MT"."Quotation_Items"
            WHERE item_id = :item_id AND quotation_id = :quotation_id
        """)
        
        result = session.execute(delete_query, {
            'item_id': item_id,
            'quotation_id': quotation_id
        })
        
        if result.rowcount == 0:
            return jsonify({'error': 'Item not found'}), 404
        
        # Recalculate total
        new_total = calculate_quotation_total(session, quotation_id)
        
        update_total = text("""
            UPDATE "StreemLyne_MT"."Quotations"
            SET total = :total, updated_at = CURRENT_TIMESTAMP
            WHERE quotation_id = :quotation_id AND tenant_id = :tenant_id
        """)
        
        session.execute(update_total, {
            'total': new_total,
            'quotation_id': quotation_id,
            'tenant_id': str(tenant_id)
        })
        
        session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Item deleted',
            'new_total': new_total
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error deleting item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()