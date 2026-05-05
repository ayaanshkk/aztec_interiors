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


@quotation_bp.route('/quotations/debug-pricelist', methods=['GET'])
@token_required
@require_tenant
def debug_pricelist(tenant_id, employee_id):
    """Debug endpoint - see what's in your pricelist"""
    session = SessionLocal()
    try:
        # Get all unique categories
        cat_query = text("""
            SELECT DISTINCT category, COUNT(*) as count
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
            GROUP BY category
            ORDER BY category
        """)
        
        categories = session.execute(cat_query, {'tenant_id': str(tenant_id)}).fetchall()
        
        # Get sample items from each category
        all_items = []
        for cat in categories:
            items_query = text("""
                SELECT pricelist_id, item_name, category, base_price
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id AND category = :category
                LIMIT 3
            """)
            
            items = session.execute(items_query, {
                'tenant_id': str(tenant_id),
                'category': cat.category
            }).fetchall()
            
            all_items.extend([{
                'category': i.category,
                'item_name': i.item_name,
                'price': float(i.base_price)
            } for i in items])
        
        return jsonify({
            'total_categories': len(categories),
            'categories': [{'name': c.category, 'count': c.count} for c in categories],
            'sample_items': all_items
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

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
                'quantity': item.get('quantity') or 1,
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
            WHERE form_submission_id = :submission_id AND tenant_id = :tenant_id
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
        
        # ✅ FIXED: Extract items with correct parameters
        extracted_items = extract_checklist_items(form_data, session, tenant_id)
        
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
        
        # ✅ FIXED: Use correct field names from extracted items
        for item in extracted_items:
            session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item['item'],           # ← 'item' not 'item_name'
                'description': item['description'],
                'color': item.get('colour'),         # ← 'colour' not 'color'
                'quantity': item.get('qty', 1),      # ← 'qty' not 'quantity'
                'amount': item.get('price', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('pricelist_id')
            })
            
            total += item.get('price', 0) * item.get('qty', 1)  # ← use 'qty'
            
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

def find_price_by_code_and_door(session, tenant_id, item_code, door_type=None):
    """
    Find price from PriceList_Master by item code and optional door type
    Returns (price, pricelist_id, width, height, depth, needs_manual_pricing, description)
    """
    try:
        current_app.logger.info(f"🔍 Looking up code: {item_code}, door_type: {door_type}")
        
        # Build query based on whether door_type is specified
        if door_type and door_type != 'Base Cabinet Only':
            # Search for specific door type variation
            query = text("""
                SELECT 
                    pricelist_id,
                    item_name,
                    description,
                    base_price,
                    width,
                    height,
                    depth,
                    door_type
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND item_code = :item_code
                    AND door_type = :door_type
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'item_code': item_code.strip().upper(),
                'door_type': door_type
            }).fetchone()
        else:
            # Search for base cabinet (no door type or "Base Cabinet Only")
            query = text("""
                SELECT 
                    pricelist_id,
                    item_name,
                    description,
                    base_price,
                    width,
                    height,
                    depth,
                    door_type
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND item_code = :item_code
                    AND (door_type IS NULL OR door_type = 'Base Cabinet Only')
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'item_code': item_code.strip().upper()
            }).fetchone()
        
        if result:
            current_app.logger.info(
                f"✅ Found: {result.item_name} ({result.door_type or 'Base'}) - £{result.base_price}"
            )
            return (
                float(result.base_price),
                result.pricelist_id,
                result.width,
                result.height,
                result.depth,
                False,  # Has price - no manual pricing needed
                result.description or result.item_name
            )
        
        # No match found
        current_app.logger.warning(f"⚠️ No price found for code: {item_code} with door_type: {door_type}")
        return (0.0, None, None, None, None, True, None)  # Needs manual pricing
        
    except Exception as e:
        current_app.logger.error(f"❌ Error finding price by code: {e}")
        return (0.0, None, None, None, None, True, None)


def extract_checklist_items(form_data, session, tenant_id):
    """
    Extract ONLY main components from checklist for quotation.
    
    Main components:
    1. Door Type
    2. Handle Code
    3. Worktop Material Type
    4. Appliances (if not N/A)
    5. Sink (if not N/A)
    6. Tap (if not N/A)
    """
    items = []
    
    # ===== 1. DOOR TYPE =====
    door_type = form_data.get('door_type', '').strip()
    
    if door_type and door_type != 'N/A' and door_type != '':
        items.append({
            'item': f'Door - {door_type}',
            'description': '',
            'colour': 'Colour',
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True
        })
    
    # ===== 2. HANDLES =====
    handles_code = form_data.get('handles_code', '').strip()
    handles_qty = form_data.get('handles_quantity', '').strip()
    handles_size = form_data.get('handles_size', '').strip()
    
    if handles_code and handles_code != 'N/A' and handles_code != '':
        handle_price, handle_pricelist_id, _, needs_pricing = find_price_for_item(
            session, tenant_id, 'handle', 'Handles', handles_code
        )
        
        qty = 1
        try:
            qty = int(handles_qty) if handles_qty and handles_qty != 'N/A' else 1
        except:
            qty = 1
        
        items.append({
            'item': f'Handles - {handles_code}',
            'description': f'{handles_size} size' if handles_size and handles_size != 'N/A' else '-',
            'colour': 'Colour',
            'qty': qty,
            'price': handle_price,
            'amount': handle_price * qty,
            'pricelist_id': handle_pricelist_id,
            'needs_manual_pricing': needs_pricing
        })
    
    # ===== 3. WORKTOP =====
    worktop_type = form_data.get('worktop_material_type', '').strip()
    worktop_color = form_data.get('worktop_material_color', '').strip()
    worktop_size = form_data.get('worktop_size', '').strip()
    
    if worktop_type and worktop_type != 'N/A' and worktop_type != '':
        worktop_price, worktop_pricelist_id, _, needs_pricing = find_price_for_item(
            session, tenant_id, 'worktop', 'Worktops', f'{worktop_type} {worktop_size}'
        )
        
        description_parts = []
        if worktop_size and worktop_size != 'N/A':
            description_parts.append(f'{worktop_size} thickness')
        
        worktop_features = form_data.get('worktop_features', [])
        if worktop_features and isinstance(worktop_features, list):
            features = [f for f in worktop_features if f and f != 'N/A']
            if features:
                description_parts.append(', '.join(features))
        
        items.append({
            'item': f'Worktop - {worktop_type}',
            'description': ', '.join(description_parts) if description_parts else '-',
            'colour': worktop_color if worktop_color and worktop_color != 'N/A' else 'H1',
            'qty': 1,
            'price': worktop_price,
            'amount': worktop_price,
            'pricelist_id': worktop_pricelist_id,
            'needs_manual_pricing': needs_pricing
        })
    
    # ===== 4. APPLIANCES (ONLY IF NOT N/A) =====
    appliances_owned = form_data.get('appliances_customer_owned', '').strip()
    
    if appliances_owned and appliances_owned.lower() in ['yes', 'no']:
        appliances = form_data.get('appliances', [])
        
        if appliances and isinstance(appliances, list):
            standard_appliances = ["Oven", "Microwave", "Washing Machine", "Dryer", "HOB", "Extractor", "INTG Dishwasher"]
            
            for idx, app in enumerate(appliances):
                if not isinstance(app, dict):
                    continue
                
                make = app.get('make', '').strip()
                model = app.get('model', '').strip()
                
                if not make or make == 'N/A':
                    if not model or model == 'N/A':
                        continue
                
                appliance_name = standard_appliances[idx] if idx < len(standard_appliances) else f'Appliance {idx + 1}'
                
                appliance_price, appliance_pricelist_id, _, needs_pricing = find_price_for_item(
                    session, tenant_id, 'appliance', 'Appliances', appliance_name
                )
                
                items.append({
                    'item': f'Appliance - {appliance_name}',
                    'description': f'Make: {make}, Model: {model}',
                    'colour': 'Colour',
                    'qty': 1,
                    'price': appliance_price,
                    'amount': appliance_price,
                    'pricelist_id': appliance_pricelist_id,
                    'needs_manual_pricing': needs_pricing
                })
        
        # INTG Fridge
        integ_fridge_make = form_data.get('integ_fridge_make', '').strip()
        if integ_fridge_make and integ_fridge_make != 'N/A':
            qty = 1
            try:
                qty = int(form_data.get('integ_fridge_qty', '').strip() or 1)
            except:
                qty = 1
            
            fridge_price, fridge_pricelist_id, _, needs_pricing = find_price_for_item(
                session, tenant_id, 'appliance', 'Appliances', 'INTG Fridge'
            )
            
            items.append({
                'item': 'Appliance - INTG Fridge',
                'description': f'Make: {integ_fridge_make}, Model: {form_data.get("integ_fridge_model", "N/A")}',
                'colour': 'Colour',
                'qty': qty,
                'price': fridge_price,
                'amount': fridge_price * qty,
                'pricelist_id': fridge_pricelist_id,
                'needs_manual_pricing': needs_pricing
            })
        
        # INTG Freezer
        integ_freezer_make = form_data.get('integ_freezer_make', '').strip()
        if integ_freezer_make and integ_freezer_make != 'N/A':
            qty = 1
            try:
                qty = int(form_data.get('integ_freezer_qty', '').strip() or 1)
            except:
                qty = 1
            
            freezer_price, freezer_pricelist_id, _, needs_pricing = find_price_for_item(
                session, tenant_id, 'appliance', 'Appliances', 'INTG Freezer'
            )
            
            items.append({
                'item': 'Appliance - INTG Freezer',
                'description': f'Make: {integ_freezer_make}, Model: {form_data.get("integ_freezer_model", "N/A")}',
                'colour': 'Colour',
                'qty': qty,
                'price': freezer_price,
                'amount': freezer_price * qty,
                'pricelist_id': freezer_pricelist_id,
                'needs_manual_pricing': needs_pricing
            })
    
    # ===== 5. SINK (ONLY IF NOT N/A) =====
    sink_owned = form_data.get('sink_tap_customer_owned', '').strip()
    
    if sink_owned and sink_owned.lower() in ['yes', 'no']:
        sink_details = form_data.get('sink_details', '').strip()
        
        if sink_details and sink_details != 'N/A':
            sink_price, sink_pricelist_id, _, needs_pricing = find_price_for_item(
                session, tenant_id, 'sink', 'Sinks', sink_details
            )
            
            items.append({
                'item': 'Sink',
                'description': f'{sink_details}, Model: {form_data.get("sink_model", "N/A")}',
                'colour': 'Colour',
                'qty': 1,
                'price': sink_price,
                'amount': sink_price,
                'pricelist_id': sink_pricelist_id,
                'needs_manual_pricing': needs_pricing
            })
    
    # ===== 6. TAP (ONLY IF NOT N/A) =====
    if sink_owned and sink_owned.lower() in ['yes', 'no']:
        tap_details = form_data.get('tap_details', '').strip()
        
        if tap_details and tap_details != 'N/A':
            tap_price, tap_pricelist_id, _, needs_pricing = find_price_for_item(
                session, tenant_id, 'tap', 'Taps', tap_details
            )
            
            items.append({
                'item': 'Tap',
                'description': f'{tap_details}, Model: {form_data.get("tap_model", "N/A")}',
                'colour': 'Colour',
                'qty': 1,
                'price': tap_price,
                'amount': tap_price,
                'pricelist_id': tap_pricelist_id,
                'needs_manual_pricing': needs_pricing
            })
    
    return items
 
 
def find_price_for_item(session, tenant_id, item_type, category, search_term):
    """
    Find price for an item from PriceList_Master.
    
    Returns: (price, pricelist_id, dimension_formula, needs_manual_pricing)
    """
    from sqlalchemy import text, or_
    
    try:
        # Search in PriceList_Master
        query = text("""
            SELECT pricelist_id, base_price, dimension_formula, item_name, description
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
            AND category = :category
            AND (
                LOWER(item_name) LIKE LOWER(:search_term)
                OR LOWER(description) LIKE LOWER(:search_term)
            )
            LIMIT 1
        """)
        
        result = session.execute(query, {
            'tenant_id': str(tenant_id),
            'category': category,
            'search_term': f'%{search_term}%'
        }).fetchone()
        
        if result:
            return (
                float(result.base_price or 0),
                result.pricelist_id,
                result.dimension_formula,
                False  # Found in database
            )
        
        # Not found - return fallback prices
        fallback_prices = {
            'door': 0.0,
            'panel': 0.0,
            'handle': 0.0,      # ← Set to 0
            'worktop': 0.0,     # ← Set to 0
            'appliance': 0.0,
            'sink': 0.0,
            'tap': 0.0
        }
        
        return (
            fallback_prices.get(item_type, 0.0),
            None,
            None,
            True  # Needs manual pricing
        )
        
    except Exception as e:
        current_app.logger.error(f"Error finding price for {item_type}: {e}")
        return (0.0, None, None, True)
 
@quotation_bp.route('/pricelist/search', methods=['GET'])
@token_required
@require_tenant
def search_pricelist(tenant_id, employee_id):
    """
    Search pricelist by code and optional door type
    Query params: code (required), door_type (optional)
    
    Example: GET /api/pricelist/search?code=40R&door_type=Vinyl
    """
    session = SessionLocal()
    try:
        item_code = request.args.get('code', '').strip().upper()
        door_type = request.args.get('door_type', '').strip()
        
        if not item_code:
            return jsonify({'error': 'code parameter is required'}), 400
        
        # If door_type provided, search for that specific combination
        if door_type and door_type != 'Base Cabinet Only':
            query = text("""
                SELECT 
                    pricelist_id,
                    item_code,
                    item_name,
                    description,
                    base_price,
                    door_type,
                    width,
                    height,
                    depth,
                    category
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND item_code = :item_code
                    AND door_type = :door_type
            """)
            
            results = session.execute(query, {
                'tenant_id': str(tenant_id),
                'item_code': item_code,
                'door_type': door_type
            }).fetchall()
        else:
            # Return all variations for this code
            query = text("""
                SELECT 
                    pricelist_id,
                    item_code,
                    item_name,
                    description,
                    base_price,
                    door_type,
                    width,
                    height,
                    depth,
                    category
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND item_code = :item_code
                ORDER BY 
                    CASE door_type
                        WHEN 'Base Cabinet Only' THEN 1
                        WHEN 'Basic Slab' THEN 2
                        WHEN 'Vinyl' THEN 3
                        WHEN 'Acrylic Gloss/Matt' THEN 4
                        WHEN 'Black Glass' THEN 5
                        ELSE 6
                    END
            """)
            
            results = session.execute(query, {
                'tenant_id': str(tenant_id),
                'item_code': item_code
            }).fetchall()
        
        if not results:
            return jsonify({
                'found': False,
                'message': f'No pricing found for code: {item_code}'
            }), 404
        
        items = []
        for r in results:
            items.append({
                'pricelist_id': r.pricelist_id,
                'item_code': r.item_code,
                'item_name': r.item_name,
                'description': r.description,
                'price': float(r.base_price),
                'door_type': r.door_type,
                'width': r.width,
                'height': r.height,
                'depth': r.depth,
                'category': r.category
            })
        
        return jsonify({
            'found': True,
            'code': item_code,
            'items': items
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error searching pricelist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


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
                'id': quote.quotation_id,  # ✅ Changed from quotation_id
                'quotation_id': quote.quotation_id,  # Keep for backward compatibility
                'reference_number': quote.reference_number,
                'customer_id': str(quote.client_id),  # ✅ Changed from client_id
                'customer_name': quote.client_company_name,  # ✅ Changed from client_name
                'client_id': quote.client_id,  # Keep for backward compatibility
                'client_name': quote.client_company_name,  # Keep for backward compatibility
                'client_address': quote.client_address,
                'client_phone': quote.client_phone,
                'project_id': quote.project_id,
                'total': float(quote.total) if quote.total else 0,
                'status': quote.status,
                'notes': quote.notes,
                'created_at': quote.created_at.isoformat() if quote.created_at else None,
                'updated_at': quote.updated_at.isoformat() if quote.updated_at else None,  # ✅ Added
                'items': [{
                    'id': i.item_id,  # ✅ Changed from item_id
                    'item_id': i.item_id,  # Keep for backward compatibility
                    'item': i.item_name,  # ✅ Changed from item_name
                    'item_name': i.item_name,  # Keep for backward compatibility
                    'description': i.description,
                    'color': i.color,
                    'quantity': i.quantity,
                    'amount': float(i.amount) if i.amount else 0,
                    'width': i.width,
                    'height': i.height,
                    'depth': i.depth,
                    'needs_manual_pricing': i.needs_manual_pricing,
                    'price_list_item_id': i.pricelist_id  # ✅ Added
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

@quotation_bp.route('/quotations/<int:quotation_id>/items/<int:item_id>', methods=['PUT'])
@token_required
@require_tenant
def update_quotation_item(quotation_id, item_id, tenant_id, employee_id):
    """Update a single quotation item"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Build update fields
        update_fields = []
        params = {
            'item_id': item_id,
            'quotation_id': quotation_id
        }
        
        if 'width' in data:
            update_fields.append("width = :width")
            params['width'] = data['width']
        if 'height' in data:
            update_fields.append("height = :height")
            params['height'] = data['height']
        if 'depth' in data:
            update_fields.append("depth = :depth")
            params['depth'] = data['depth']
        if 'amount' in data:
            update_fields.append("amount = :amount")
            params['amount'] = data['amount']
        if 'quantity' in data:
            update_fields.append("quantity = :quantity")
            params['quantity'] = data['quantity']
        
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        
        # Update item
        update_query = text(f"""
            UPDATE "StreemLyne_MT"."Quotation_Items"
            SET {', '.join(update_fields)}
            WHERE item_id = :item_id AND quotation_id = :quotation_id
        """)
        
        result = session.execute(update_query, params)
        
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
            'message': 'Item updated',
            'new_total': new_total
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error updating item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@quotation_bp.route('/quotations/auto-price-lookup', methods=['POST'])
@token_required
@require_tenant
def auto_price_lookup(tenant_id, employee_id):
    """
    SMART auto-lookup price - tries multiple strategies:
    1. Exact item_code match (prefers Kitchen category)
    2. Width-based code generation (150mm → 15BPO, 15B)
    3. Description keyword search
    4. Width dimension match
    
    Returns best match with confidence score
    """
    db_session = SessionLocal()
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        door_type = data.get('door_type', '').strip()
        
        current_app.logger.info(f"🔍 Smart lookup: description='{description}', door_type='{door_type}'")
        
        if not description:
            return jsonify({'found': False, 'error': 'description is required'}), 400
        
        import re
        
        # ==================================================================
        # STRATEGY 1: Direct code match
        # Look for codes like "15BPO", "30B", "40B" directly in description
        # ==================================================================
        code_patterns = [
            r'\b(\d+BPO)\b',  # 15BPO, 30BPO
            r'\b(\d+BDL)\b',  # Drawerline (check BEFORE \d+B to avoid matching 40B instead of 40BDL)
            r'\b(\d+BC)\b',   # Corner bases
            r'\b(\d+BDD)\b',  # Dummy drawer
            r'\b(\d+BA)\b',   # Angled base
            r'\b(\d+B)\b',    # 15B, 30B, 40B (LAST - most generic)
        ]
        
        found_code = None
        for pattern in code_patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                found_code = match.group(1).upper()
                current_app.logger.info(f"✅ Strategy 1: Found code '{found_code}' in description")
                break
        
        # ==================================================================
        # STRATEGY 2: Intelligent keyword + width code generation
        # Detect special keywords: Drawerline, Corner, Dummy, Angled
        # ==================================================================
        width_mm = None
        mm_match = re.search(r'(\d+)\s*mm', description, re.IGNORECASE)
        if mm_match:
            width_mm = int(mm_match.group(1))
            current_app.logger.info(f"✅ Strategy 2: Parsed width {width_mm}mm")
        
        # Detect special unit types from description
        unit_type_suffix = ""
        if re.search(r'\bdrawerline\b', description, re.IGNORECASE):
            unit_type_suffix = "DL"
            current_app.logger.info(f"✅ Detected: Drawerline unit")
        elif re.search(r'\bcorner\b', description, re.IGNORECASE):
            unit_type_suffix = "C"
            current_app.logger.info(f"✅ Detected: Corner unit")
        elif re.search(r'\bdummy\b', description, re.IGNORECASE):
            unit_type_suffix = "DD"
            current_app.logger.info(f"✅ Detected: Dummy drawer unit")
        elif re.search(r'\bangled?\b', description, re.IGNORECASE):
            unit_type_suffix = "A"
            current_app.logger.info(f"✅ Detected: Angled unit")
        
        # ==================================================================
        # STRATEGY 3: Build search candidates with intelligent type detection
        # ==================================================================
        search_candidates = []
        
        # Add directly found code
        if found_code:
            search_candidates.append(found_code)
        
        # Add width-based codes WITH unit type suffix
        if width_mm:
            width_code = width_mm // 10
            
            # If special type detected (Drawerline, Corner, etc.), prioritize that code
            if unit_type_suffix:
                search_candidates.extend([
                    f"{width_code}B{unit_type_suffix}",  # e.g., 40BDL for Drawerline
                    f"{width_mm}B{unit_type_suffix}",    # e.g., 400BDL
                ])
            
            # Always add standard codes as fallback
            search_candidates.extend([
                f"{width_code}BPO",  # e.g., 15BPO
                f"{width_code}B",    # e.g., 15B
                f"{width_mm}B",      # e.g., 150B (some items use full width)
            ])
        
        current_app.logger.info(f"🔍 Search candidates: {search_candidates}")
        
        # ==================================================================
        # STRATEGY 4: Try each candidate with door type matching
        # ==================================================================
        
        # Map door types to database values
        DOOR_TYPE_MAP = {
            'basic slab': 'Basic Slab',  # ← CHANGED: Now maps to "Basic Slab" not "Base Cabinet Only"
            'acrylic gloss/matt': 'Acrylic Gloss/Matt',
            'acrylic gloss': 'Acrylic Gloss/Matt',
            'acrylic matt': 'Acrylic Gloss/Matt',
            'vinyl': 'Vinyl',
            'black glass': 'Black Glass',
        }
        
        db_door_type = DOOR_TYPE_MAP.get(door_type.lower(), door_type) if door_type else None
        
        result = None
        
        # Try exact code + door type match first (PREFER KITCHEN CATEGORY)
        if search_candidates and db_door_type:
            for code in search_candidates:
                query = text("""
                    SELECT 
                        pricelist_id, item_code, item_name, description,
                        base_price, door_type, width, height, depth, category
                    FROM "StreemLyne_MT"."PriceList_Master"
                    WHERE tenant_id = :tenant_id
                        AND UPPER(item_code) = UPPER(:item_code)
                        AND door_type = :door_type
                    ORDER BY 
                        CASE 
                            WHEN category = 'Kitchen' THEN 1
                            WHEN category = 'Base Units' THEN 2
                            ELSE 3
                        END
                    LIMIT 1
                """)
                
                result = db_session.execute(query, {
                    'tenant_id': str(tenant_id),
                    'item_code': code,
                    'door_type': db_door_type
                }).fetchone()
                
                if result:
                    current_app.logger.info(f"✅ Match: {code} + {db_door_type} (category: {result.category})")
                    break
        
        # If no match, try without door type (fallback) - STILL PREFER KITCHEN
        if not result and search_candidates:
            for code in search_candidates:
                query = text("""
                    SELECT 
                        pricelist_id, item_code, item_name, description,
                        base_price, door_type, width, height, depth, category
                    FROM "StreemLyne_MT"."PriceList_Master"
                    WHERE tenant_id = :tenant_id
                        AND UPPER(item_code) = UPPER(:item_code)
                    ORDER BY 
                        CASE 
                            WHEN category = 'Kitchen' THEN 1
                            WHEN category = 'Base Units' THEN 2
                            ELSE 3
                        END,
                        CASE 
                            WHEN door_type = :door_type THEN 1
                            ELSE 2
                        END
                    LIMIT 1
                """)
                
                result = db_session.execute(query, {
                    'tenant_id': str(tenant_id),
                    'item_code': code,
                    'door_type': db_door_type or 'Basic Slab'
                }).fetchone()
                
                if result:
                    current_app.logger.info(f"✅ Fallback match: {code} (category: {result.category})")
                    break
        
        # ==================================================================
        # STRATEGY 5: Description keyword search (PREFER KITCHEN)
        # "Base Unit 150mm" → search description field
        # ==================================================================
        if not result and width_mm:
            query = text("""
                SELECT 
                    pricelist_id, item_code, item_name, description,
                    base_price, door_type, width, height, depth, category
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND width = :width
                ORDER BY 
                    CASE 
                        WHEN category = 'Kitchen' THEN 1
                        WHEN category = 'Base Units' THEN 2
                        ELSE 3
                    END,
                    CASE 
                        WHEN door_type = :door_type THEN 1
                        ELSE 2
                    END,
                    base_price DESC
                LIMIT 1
            """)
            
            result = db_session.execute(query, {
                'tenant_id': str(tenant_id),
                'width': width_mm,
                'door_type': db_door_type or 'Basic Slab'
            }).fetchone()
            
            if result:
                current_app.logger.info(f"✅ Width match: {width_mm}mm → {result.item_code} (category: {result.category})")
        
        # ==================================================================
        # STRATEGY 6: Fuzzy description match (last resort)
        # ==================================================================
        if not result:
            # Extract key terms from description
            search_terms = re.findall(r'\b\w+\b', description.lower())
            search_terms = [t for t in search_terms if len(t) > 3][:3]  # Top 3 meaningful words
            
            if search_terms:
                like_clause = ' AND '.join([f"LOWER(item_name) LIKE '%{term}%'" for term in search_terms])
                
                query = text(f"""
                    SELECT 
                        pricelist_id, item_code, item_name, description,
                        base_price, door_type, width, height, depth, category
                    FROM "StreemLyne_MT"."PriceList_Master"
                    WHERE tenant_id = :tenant_id
                        AND ({like_clause})
                    ORDER BY 
                        CASE 
                            WHEN category = 'Kitchen' THEN 1
                            WHEN category = 'Base Units' THEN 2
                            ELSE 3
                        END,
                        CASE 
                            WHEN door_type = :door_type THEN 1
                            ELSE 2
                        END
                    LIMIT 1
                """)
                
                result = db_session.execute(query, {
                    'tenant_id': str(tenant_id),
                    'door_type': db_door_type or 'Basic Slab'
                }).fetchone()
                
                if result:
                    current_app.logger.info(f"✅ Fuzzy match: {search_terms} → {result.item_code}")
        
        # ==================================================================
        # RETURN RESULT
        # ==================================================================
        if result:
            current_app.logger.info(
                f"✅ FOUND: {result.item_name} ({result.door_type or 'No door'}) - £{result.base_price}"
            )
            return jsonify({
                'found': True,
                'price': float(result.base_price),
                'width': result.width,
                'height': result.height,
                'depth': result.depth,
                'item_code': result.item_code,
                'item_name': result.item_name,
                'door_type': result.door_type or 'Basic Slab',
                'pricelist_id': result.pricelist_id,
                'description': result.description
            }), 200
        else:
            current_app.logger.warning(
                f"⚠️ NO MATCH for: '{description}' (door: {door_type})"
            )
            return jsonify({
                'found': False,
                'error': f'No pricing found. Tried codes: {search_candidates}, width: {width_mm}mm'
            }), 404
        
    except Exception as e:
        current_app.logger.error(f"❌ Error in smart lookup: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'found': False, 'error': str(e)}), 500
    finally:
        db_session.close()