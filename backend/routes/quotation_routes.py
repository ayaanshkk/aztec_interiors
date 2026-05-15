from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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
            } for i in items if (i.item_name and i.item_name.strip()) or (i.description and i.description.strip()) or (i.amount and float(i.amount) > 0)]
            )
        
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
                'id': q.quotation_id,  # ✅ CRITICAL: Frontend needs this for delete!
                'quotation_id': q.quotation_id,  # Keep for backward compatibility
                'reference_number': q.reference_number,
                'client_id': q.client_id,
                'customer_id': q.client_id,  # ✅ ADDED: Frontend also checks this
                'client_name': q.client_company_name,
                'customer_name': q.client_company_name,  # ✅ ADDED: Alternative field name
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
        print(f"Error fetching quotations: {e}")
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
            (tenant_id, client_id, project_id, reference_number, total, status, notes, employee_id,
             customer_name, customer_address, customer_phone, customer_email, vat_percentage)
            VALUES (:tenant_id, :client_id, :project_id, :reference_number, :total, :status, :notes, :employee_id,
                    :customer_name, :customer_address, :customer_phone, :customer_email, :vat_percentage)
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
            'employee_id': employee_id,
            'customer_name': data.get('customer_name', ''),
            'customer_address': data.get('customer_address', ''),
            'customer_phone': data.get('customer_phone', ''),
            'customer_email': data.get('customer_email', ''),
            'vat_percentage': data.get('vat_percentage', 20.0)
        })
        
        quotation_id = result.fetchone().quotation_id
        
        # Add items
        for item in items_data:
            item_insert = text("""
                INSERT INTO "StreemLyne_MT"."Quotation_Items"
                (quotation_id, item_name, description, color, quantity, amount,
                width, height, depth, needs_manual_pricing, pricelist_id,
                discount_percent, discounted_amount)
                VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                        :width, :height, :depth, :needs_manual, :pricelist_id,
                        :discount_percent, :discounted_amount)
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
                'pricelist_id': item.get('price_list_item_id'),
                'discount_percent': item.get('discount_percent', 0),
                'discounted_amount': item.get('discounted_amount', item.get('amount', 0))
            })
        
        session.commit()
        
        print(f"Quotation {ref_num} created")
        
        return jsonify({
            'quotation_id': quotation_id,
            'reference_number': ref_num,
            'message': 'Quotation created successfully'
        }), 201
        
    except Exception as e:
        session.rollback()
        print(f"Error creating quotation: {e}")
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
        print(f"📋 Generating quote from submission {form_submission_id}")
        
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
        
        # ✅ NEW: Extract door_type and room_type from form data
        door_type = form_data.get('door_type', 'Basic Slab')
        
        # Determine room type from checklist type
        room_type = 'Kitchen' if checklist_type == 'kitchen' else 'Bedroom'
        
        print(f"🏷️  Checklist Type: {checklist_type}")
        print(f"🚪 Door Type: {door_type}")
        print(f"🏠 Room Type: {room_type}")
        
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
        
        # Extract items with correct parameters
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
        
        for item in extracted_items:
            session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item['item'],
                'description': item['description'],
                'color': item.get('colour'),
                'quantity': item.get('qty', 1),
                'amount': item.get('price', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('pricelist_id')
            })
            
            total += item.get('price', 0) * item.get('qty', 1)
            
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
        
        print(f"✅ Quote {ref_num}: {matched_count} auto-priced, {manual_count} manual")
        
        # ✅ NEW: Include door_type and room_type in response
        return jsonify({
            'success': True,
            'quotation_id': quotation_id,
            'reference_number': ref_num,
            'items_count': len(extracted_items),
            'matched_items': matched_count,
            'manual_items': manual_count,
            'total': total,
            'checklist_type': checklist_type,
            'door_type': door_type,      # ✅ ADD THIS
            'room_type': room_type,      # ✅ ADD THIS
            'message': f'Quote generated: {matched_count} auto-priced, {manual_count} need manual pricing'
        }), 201
        
    except Exception as e:
        session.rollback()
        print(f"Error generating quotation: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

def find_price_by_code_and_door(session, tenant_id, item_code, door_type=None):
    """
    Find price from PriceList_Master by item code and optional door type
    Returns (price, pricelist_id, width, height, depth, needs_manual_pricing, description)
    """
    try:
        print(f"🔍 Looking up code: {item_code}, door_type: {door_type}")
        
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
            print(
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
        print(f"⚠️ No price found for code: {item_code} with door_type: {door_type}")
        return (0.0, None, None, None, None, True, None)  # Needs manual pricing
        
    except Exception as e:
        print(f"❌ Error finding price by code: {e}")
        return (0.0, None, None, None, None, True, None)


def extract_checklist_items(form_data, session, tenant_id):
    """
    Extract ONLY main components from checklist for quotation.
    WITH DIAGNOSTIC LOGGING to debug additional doors
    """
    items = []
    
    # ===== DIAGNOSTIC LOGGING START =====
    import json
    print("=" * 80)
    print("📋 BEDROOM CHECKLIST DEBUG")
    print("=" * 80)
    print(f"🔑 All keys: {list(form_data.keys())}")
    print(f"🚪 door_type: {form_data.get('door_type')}")
    print(f"🚪 door_color: {form_data.get('door_color')}")
    print(f"🚪 door_details: {form_data.get('door_details')}")
    print(f"🚪 door_style: {form_data.get('door_style')}")
    print(f"📄 FULL FORM DATA:")
    try:
        print(json.dumps(form_data, indent=2, default=str))
    except:
        print(str(form_data))
    print("=" * 80)
    # ===== DIAGNOSTIC LOGGING END =====
    
    # ===== 1. MAIN DOOR TYPE =====
    door_type = form_data.get('door_type', '').strip()
    door_color = form_data.get('door_color', '').strip()
    
    if door_type and door_type != 'N/A' and door_type != '':
        items.append({
            'item': f'Door - {door_type}',
            'description': '',
            'colour': door_color if door_color and door_color != 'N/A' else 'Colour',
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True
        })
        print(f"✅ Added main door: {door_type} ({door_color})")
    
    # ===== 1B. ADDITIONAL DOORS - TRY MULTIPLE FIELD NAMES =====
    # Try different possible field names
    additional_doors = None
    
    for field_name in ['door_details', 'additional_doors', 'extra_doors', 'doorDetails', 'additionalDoors']:
        if field_name in form_data:
            additional_doors = form_data.get(field_name, [])
            print(f"✅ Found additional doors in field: '{field_name}'")
            print(f"   Value: {additional_doors}")
            break
    
    if not additional_doors:
        print("⚠️ No additional doors field found")
    
    if additional_doors and isinstance(additional_doors, list):
        print(f"📦 Processing {len(additional_doors)} additional door entries")
        
        for idx, additional_door in enumerate(additional_doors):
            print(f"   Door {idx + 1}: {additional_door}")
            
            if not isinstance(additional_door, dict):
                print(f"   ⚠️ Not a dict, skipping")
                continue
            
            # Try multiple field name variations
            add_door_style = (
                additional_door.get('door_style') or 
                additional_door.get('doorStyle') or 
                additional_door.get('style') or ''
            ).strip()
            
            add_door_color = (
                additional_door.get('door_color') or 
                additional_door.get('doorColor') or 
                additional_door.get('color') or ''
            ).strip()
            
            add_quantity = (
                additional_door.get('quantity') or 
                additional_door.get('qty') or ''
            ).strip()
            
            print(f"   Extracted: style={add_door_style}, color={add_door_color}, qty={add_quantity}")
            
            # Skip if no door style
            if not add_door_style or add_door_style == 'N/A':
                print(f"   ⚠️ No door style, skipping")
                continue
            
            # Parse quantity
            qty = 1
            try:
                qty = int(add_quantity) if add_quantity and add_quantity != 'N/A' else 1
            except:
                qty = 1
            
            # Skip if quantity is 0
            if qty <= 0:
                print(f"   ⚠️ Quantity is 0, skipping")
                continue
            
            items.append({
                'item': f'Door - {add_door_style}',
                'description': '',
                'colour': add_door_color if add_door_color and add_door_color != 'N/A' else 'Colour',
                'qty': qty,
                'price': 0,
                'amount': 0,
                'pricelist_id': None,
                'needs_manual_pricing': True
            })
            print(f"   ✅ Added additional door: {add_door_style} ({add_door_color}) x{qty}")
    
    # ===== 2. HANDLES =====
    handles_code = form_data.get('handles_code', '').strip()
    handles_qty = form_data.get('handles_quantity', '').strip()
    
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
            'description': '',
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
    
    if worktop_type and worktop_type != 'N/A' and worktop_type != '':
        worktop_price, worktop_pricelist_id, _, needs_pricing = find_price_for_item(
            session, tenant_id, 'worktop', 'Worktops', f'{worktop_type}'
        )
        
        items.append({
            'item': f'Worktop - {worktop_type}',
            'description': '',
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
                    'description': '',  # ✅ BLANK
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
                'description': '',  # ✅ BLANK
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
                'description': '',  # ✅ BLANK
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
                'description': '',  # ✅ BLANK
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
                'description': '',  # ✅ BLANK
                'colour': 'Colour',
                'qty': 1,
                'price': tap_price,
                'amount': tap_price,
                'pricelist_id': tap_pricelist_id,
                'needs_manual_pricing': needs_pricing
            })
    
    print(f"📊 Total items extracted: {len(items)}")
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
        print(f"Error finding price for {item_type}: {e}")
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
        print(f"Error searching pricelist: {e}")
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
                'id': quote.quotation_id,
                'quotation_id': quote.quotation_id,
                'reference_number': quote.reference_number,
                'customer_id': str(quote.client_id),
                'customer_name': quote.customer_name or quote.client_company_name,  # ← Use saved customer_name first
                'customer_address': quote.customer_address or quote.client_address,  # ← Use saved customer_address first
                'customer_phone': quote.customer_phone or quote.client_phone,        # ← Use saved customer_phone first
                'customer_email': getattr(quote, 'customer_email', None),           # ← Add customer_email
                'vat_percentage': float(quote.vat_percentage) if hasattr(quote, 'vat_percentage') and quote.vat_percentage else 20.0,
                'client_id': quote.client_id,
                'client_name': quote.client_company_name,
                'client_address': quote.client_address,
                'client_phone': quote.client_phone,
                'project_id': quote.project_id,
                'total': float(quote.total) if quote.total else 0,
                'status': quote.status,
                'notes': quote.notes,
                'created_at': quote.created_at.isoformat() if quote.created_at else None,
                'updated_at': quote.updated_at.isoformat() if quote.updated_at else None,
                'items': [{
                    'id': i.item_id,
                    'item_id': i.item_id,
                    'item': i.item_name,
                    'item_name': i.item_name,
                    'description': i.description,
                    'color': i.color,
                    'quantity': i.quantity,
                    'amount': float(i.amount) if i.amount else 0,
                    'discount_type': getattr(i, 'discount_type', 'none'),
                    'discount_value': float(i.discount_value) if hasattr(i, 'discount_value') and i.discount_value else 0,
                    'discounted_total': float(i.discounted_amount) if hasattr(i, 'discounted_amount') and i.discounted_amount else float(i.amount),
                    'width': i.width,
                    'height': i.height,
                    'depth': i.depth,
                    'needs_manual_pricing': i.needs_manual_pricing,
                    'price_list_item_id': i.pricelist_id
                } for i in items if (i.item_name and i.item_name.strip()) or (i.description and i.description.strip()) or (i.amount and float(i.amount) > 0)]  # ← FILTER OUT EMPTY ITEMS
            }
            
            return jsonify(result), 200
        
        elif request.method == 'PUT':
            # Update quotation
            data = request.get_json()
            
            # ===== UPDATE QUOTATION METADATA =====
            update_fields = []
            params = {'quotation_id': quotation_id, 'tenant_id': str(tenant_id)}
            
            if 'customer_name' in data:
                update_fields.append("customer_name = :customer_name")
                params['customer_name'] = data['customer_name']
            if 'customer_address' in data:
                update_fields.append("customer_address = :customer_address")
                params['customer_address'] = data['customer_address']
            if 'customer_phone' in data:
                update_fields.append("customer_phone = :customer_phone")
                params['customer_phone'] = data['customer_phone']
            if 'customer_email' in data:
                update_fields.append("customer_email = :customer_email")
                params['customer_email'] = data['customer_email']
            if 'vat_percentage' in data:
                update_fields.append("vat_percentage = :vat_percentage")
                params['vat_percentage'] = data['vat_percentage']
            if 'status' in data:
                update_fields.append("status = :status")
                params['status'] = data['status']
            if 'notes' in data:
                update_fields.append("notes = :notes")
                params['notes'] = data['notes']
            
            # ✅ NEW: UPDATE ITEMS
            if 'items' in data:
                # Delete all existing items
                delete_items = text("""
                    DELETE FROM "StreemLyne_MT"."Quotation_Items"
                    WHERE quotation_id = :quotation_id
                """)
                session.execute(delete_items, {'quotation_id': quotation_id})
                
                # Insert new items
                item_insert = text("""
                    INSERT INTO "StreemLyne_MT"."Quotation_Items"
                    (quotation_id, item_name, description, color, quantity, amount,
                    width, height, depth, needs_manual_pricing, pricelist_id)
                    VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                            :width, :height, :depth, :needs_manual, :pricelist_id)
                """)
                
                total = 0.0
                for item in data['items']:
                    # Skip completely empty items
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    
                    item_amount = float(item.get('amount', 0))
                    item_qty = int(item.get('quantity', 1))
                    
                    session.execute(item_insert, {
                        'quotation_id': quotation_id,
                        'item_name': item.get('item', ''),
                        'description': item.get('description', ''),
                        'color': item.get('color', ''),
                        'quantity': item_qty,
                        'amount': item_amount,
                        'width': item.get('width'),
                        'height': item.get('height'),
                        'depth': item.get('depth'),
                        'needs_manual': item.get('needs_manual_pricing', False),
                        'pricelist_id': item.get('price_list_item_id'),
                        'discount_type': item.get('discount_type', 'none'),
                        'discount_value': item.get('discount_value', 0),
                        'discounted_amount': item.get('discounted_amount', item.get('amount', 0))
                    })
                    
                    total += item_amount * item_qty
                
                # Update total in quotation
                update_fields.append("total = :total")
                params['total'] = total
            elif 'total' in data:
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
                'message': 'Quotation updated successfully'
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
        print(f"Error handling quotation: {e}")
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
        print(f"Error deleting item: {e}")
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
        print(f"Error updating item: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@quotation_bp.route('/quotations/auto-price-lookup', methods=['POST'])
@token_required
@require_tenant
def auto_price_lookup(tenant_id, employee_id):
    """
    ENHANCED - Supports ALL categories with suffix system
    
    Quoting System:
    KITCHEN/BEDROOM:
    - 50B          = Carcass ONLY (£99.86) - UNLESS dropdown specifies door type
    - 50B + "Basic Slab" dropdown = £99.86 + £34.48 = £132.08 (complete unit)
    - 50B-BS       = Basic Slab door component ONLY (£34.48)
    
    FILLERS & END PANELS:
    - PL-BS        = Plinth Basic Slab (£41.02)
    - PL-AG        = Plinth Acrylic Gloss (£61.53)
    - CF-BS        = Ceiling Filler Basic Slab (£41.02)
    
    ACCESSORIES:
    - 542.35.163   = 500mm Pull Out Waste Bin (£278.21)
    - TANDEM600    = 600mm Saucepan Tandembox Drawer (£104.24)
    
    HANDLES:
    - GRAF256      = Graf 2 bar handle (£8.79)
    - GOLAB+H      = Gola System b+ profile (£83.00)
    """
    db_session = SessionLocal()
    try:
        data = request.get_json()
        description = data.get('description', '').strip().upper()  # Auto-uppercase
        door_type = data.get('door_type', '').strip()
        room_type = data.get('room_type', 'Kitchen').strip()
        brand = data.get('brand', '').strip()
        
        print(f"🔍 Smart lookup: description='{description}', door_type='{door_type}', room_type='{room_type}'")
        
        if not description:
            return jsonify({'found': False, 'error': 'description is required'}), 400
        
        import re
 
        # ========================================================================
        # SUFFIX DETECTION - Suffix means COMPONENT ONLY
        # ========================================================================
        
        # Check for suffix like "50B-BS", "PL-AG", "CF-BS", etc.
        suffix_pattern = r'^([A-Z0-9]+)-(BS|AG|VD|BG)$'
        suffix_match = re.match(suffix_pattern, description, re.IGNORECASE)
        
        door_component_only = False
        base_code = None
        component_door_type = None
        
        if suffix_match:
            base_code = suffix_match.group(1).upper()  # e.g., "50B", "PL", "CF"
            suffix = suffix_match.group(2).upper()      # e.g., "BS", "AG"
            
            # Map suffix to door type in database
            suffix_to_door_type = {
                'BS': 'Basic Slab',
                'AG': 'Acrylic Gloss/Matt',
                'VD': 'Vinyl Doors',
                'BG': 'Black Glass'
            }
            
            component_door_type = suffix_to_door_type.get(suffix)
            door_component_only = True
            
            print(f"🎯 SUFFIX DETECTED: '{description}' → Base: '{base_code}', Component: '{component_door_type}'")
        
        # ========================================================================
        # CATEGORY-SPECIFIC HANDLING
        # ========================================================================
        
        # Try direct item_code lookup first (works for all categories)
        search_code = base_code if base_code else description
        
        # Query for exact item_code match
        direct_query = text("""
            SELECT 
                item_code, 
                item_name, 
                door_type,
                base_price,
                width, 
                height, 
                depth, 
                category,
                pricelist_id,
                description as item_description
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
                AND UPPER(item_code) = UPPER(:item_code)
        """)
        
        results = db_session.execute(direct_query, {
            'tenant_id': str(tenant_id),
            'item_code': search_code
        }).fetchall()
        
        if not results:
            print(f"❌ No items found for code: {search_code}")
            return jsonify({
                'found': False,
                'error': f'No item found for code: {search_code}'
            }), 404
        
        # Get first result to determine category
        first_result = results[0]
        category = first_result.category
        item_code = first_result.item_code
        item_name = first_result.item_name
        
        print(f"✅ Found {len(results)} rows for '{item_code}' in category '{category}'")
        
        # ========================================================================
        # ACCESSORIES & HANDLES - Single price, no door types
        # ========================================================================
        
        if category in ['Accessories', 'Handles']:
            print(f"   📦 {category} category - single price lookup")
            
            # These categories only have one price (door_type = 'Standard')
            price_row = next((r for r in results if r.door_type == 'Standard'), None)
            
            if not price_row or not price_row.base_price:
                return jsonify({
                    'found': False,
                    'error': f'No price found for {item_code} in {category}'
                }), 404
            
            price = float(price_row.base_price)
            
            print(f"   💰 {category} Price: £{price:.2f}")
            
            return jsonify({
                'found': True,
                'price': price,
                'item_code': item_code,
                'item_name': item_name,
                'description': price_row.item_description or item_name,
                'door_type': 'Standard',
                'category': category,
                'width': price_row.width,
                'height': price_row.height,
                'depth': price_row.depth,
                'pricelist_id': price_row.pricelist_id
            }), 200
        
        # ========================================================================
        # FILLERS & END PANELS - 2 prices (Basic Slab, Acrylic Gloss)
        # ========================================================================
        
        if category == 'Fillers & End Panels':
            print(f"   🏗️ Fillers & End Panels - component pricing")
            
            # If suffix specified, use that door type
            if component_door_type:
                target_door_type = component_door_type
            elif door_type:
                # Map dropdown door type
                DOOR_TYPE_MAP = {
                    'basic slab': 'Basic Slab',
                    'acrylic gloss/matt': 'Acrylic Gloss/Matt',
                    'acrylic gloss': 'Acrylic Gloss/Matt',
                    'acrylic matt': 'Acrylic Gloss/Matt',
                }
                target_door_type = DOOR_TYPE_MAP.get(door_type.lower(), door_type)
            else:
                # Default to Basic Slab if nothing specified
                target_door_type = 'Basic Slab'
            
            price_row = next((r for r in results if r.door_type == target_door_type), None)
            
            if not price_row or not price_row.base_price:
                return jsonify({
                    'found': False,
                    'error': f'No {target_door_type} price found for {item_code}'
                }), 404
            
            price = float(price_row.base_price)
            
            print(f"   💰 {target_door_type}: £{price:.2f}")
            
            return jsonify({
                'found': True,
                'price': price,
                'item_code': item_code,
                'item_name': item_name,
                'description': f"{item_name} - {target_door_type}",
                'door_type': target_door_type,
                'category': category,
                'width': price_row.width,
                'height': price_row.height,
                'depth': price_row.depth,
                'pricelist_id': price_row.pricelist_id
            }), 200
        
        # ========================================================================
        # APPLIANCES - Brand-based pricing
        # ========================================================================
        
        if category == 'Appliances':
            print(f"   🔥 Appliance lookup")
            return lookup_appliance(db_session, tenant_id, description, brand)
        
        # ========================================================================
        # KITCHEN/BEDROOM - Carcass + Door component system
        # ========================================================================
        
        # At this point, category is Kitchen/Bedroom (Base Units, Wardrobes, etc.)
        
        # Door type mapping
        DOOR_TYPE_MAP = {
            'carcass only': 'Carcass Only',
            'basic slab': 'Basic Slab',
            'acrylic gloss/matt': 'Acrylic Gloss/Matt',
            'acrylic gloss': 'Acrylic Gloss/Matt',
            'acrylic matt': 'Acrylic Gloss/Matt',
            'vinyl': 'Vinyl Doors',
            'vinyl doors': 'Vinyl Doors',
            'black glass': 'Black Glass',
            'base cabinet only': 'Base Cabinet Only',
        }
        
        db_door_type = DOOR_TYPE_MAP.get(door_type.lower(), door_type) if door_type else None
        
        # ========================================================================
        # SUFFIX MODE - Return door component ONLY
        # ========================================================================
        
        if door_component_only and component_door_type:
            print(f"   🚪 MODE: {component_door_type} door component ONLY for {item_code}")
            
            door_row = next((r for r in results if r.door_type == component_door_type), None)
            
            if not door_row or not door_row.base_price:
                return jsonify({
                    'found': False,
                    'error': f'No {component_door_type} door component found for {item_code}'
                }), 404
            
            door_price = float(door_row.base_price)
            
            print(f"   💰 {component_door_type} Door ONLY: £{door_price:.2f}")
            
            return jsonify({
                'found': True,
                'price': door_price,
                'item_code': item_code,
                'item_name': item_name,
                'description': f"{component_door_type} Door for {item_name}",
                'door_type': component_door_type,
                'category': category,
                'width': first_result.width,
                'height': first_result.height,
                'depth': first_result.depth,
                'pricelist_id': door_row.pricelist_id,
                'component_only': True,
                'breakdown': {
                    'carcass': 0.0,
                    'door_component': door_price
                }
            }), 200
        
        # ========================================================================
        # STANDARD MODE - Carcass or Carcass + Door
        # ========================================================================
        
        # Get carcass price
        carcass_row = next((r for r in results if r.door_type == 'Carcass Only'), None)
        
        if not carcass_row or not carcass_row.base_price:
            return jsonify({'found': False, 'error': f'No carcass price found for {item_code}'}), 404
        
        carcass_price = float(carcass_row.base_price)
        
        # CASE 1: No door type specified OR "Carcass Only" selected
        if not db_door_type or db_door_type == 'Carcass Only':
            print(f"   🏗️ MODE: Carcass ONLY for {item_code}")
            print(f"   💰 Price: £{carcass_price:.2f}")
            
            return jsonify({
                'found': True,
                'price': carcass_price,
                'item_code': item_code,
                'item_name': item_name,
                'description': f"{item_name} - Carcass Only",
                'door_type': 'Carcass Only',
                'category': category,
                'width': first_result.width,
                'height': first_result.height,
                'depth': first_result.depth,
                'pricelist_id': carcass_row.pricelist_id,
                'breakdown': {
                    'carcass': carcass_price,
                    'door_component': 0.0
                }
            }), 200
        
        # CASE 2: Door type specified → Return carcass + door
        print(f"   🏗️ MODE: Complete unit - {item_code} + {db_door_type}")
        
        door_row = next((r for r in results if r.door_type == db_door_type), None)
        
        if not door_row or not door_row.base_price:
            print(f"   ⚠️ No door price found for {item_code} + {db_door_type}, returning carcass only")
            
            return jsonify({
                'found': True,
                'price': carcass_price,
                'item_code': item_code,
                'item_name': item_name,
                'description': f"{item_name} - {db_door_type} (door price not found)",
                'door_type': db_door_type,
                'category': category,
                'width': first_result.width,
                'height': first_result.height,
                'depth': first_result.depth,
                'pricelist_id': carcass_row.pricelist_id,
                'warning': f'No door component price found for {db_door_type}',
                'breakdown': {
                    'carcass': carcass_price,
                    'door_component': 0.0
                }
            }), 200
        
        door_component_price = float(door_row.base_price)
        final_price = carcass_price + door_component_price
        
        print(f"   💰 Complete: Carcass £{carcass_price:.2f} + Door £{door_component_price:.2f} = £{final_price:.2f}")
        
        return jsonify({
            'found': True,
            'price': final_price,
            'item_code': item_code,
            'item_name': item_name,
            'description': f"{item_name} - {db_door_type}",
            'door_type': db_door_type,
            'category': category,
            'width': first_result.width,
            'height': first_result.height,
            'depth': first_result.depth,
            'pricelist_id': door_row.pricelist_id,
            'breakdown': {
                'carcass': carcass_price,
                'door_component': door_component_price
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Error in smart lookup: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'found': False, 'error': str(e)}), 500
    finally:
        db_session.close()


def lookup_appliance(session, tenant_id, description, brand=None):
    """Appliance lookup - unchanged"""
    import re
    
    print(f"\n🔥 APPLIANCE LOOKUP")
    print(f"   Description: {description}")
    
    model_pattern = r'\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]{2,})\b'
    model_match = re.search(model_pattern, description, re.IGNORECASE)
    
    model_code = model_match.group(1).upper() if model_match else description.strip().upper()
    
    query = text("""
        SELECT 
            pricelist_id, item_code, item_name, description,
            base_price, brand, door_type, category
        FROM "StreemLyne_MT"."PriceList_Master"
        WHERE tenant_id = :tenant_id
          AND category = 'Appliances'
          AND UPPER(item_code) = :model_code
        LIMIT 1
    """)
    
    result = session.execute(query, {
        'tenant_id': str(tenant_id),
        'model_code': model_code
    }).fetchone()
    
    if result:
        series_info = ''
        if result.description:
            series_match = re.search(r'\(([^)]+)\)', result.description)
            if series_match:
                series_info = series_match.group(1)
        
        return jsonify({
            'found': True,
            'price': float(result.base_price),
            'item_code': result.item_code,
            'item_name': result.item_name,
            'description': result.description,
            'pricelist_id': result.pricelist_id,
            'brand': result.brand,
            'series_level': result.door_type,
            'series_info': series_info,
        }), 200
    
    return jsonify({
        'found': False,
        'error': f'No appliance found with model code: {model_code}'
    }), 404

@quotation_bp.route('/quotations/<int:quotation_id>/pdf', methods=['GET'])
@token_required
@require_tenant
def download_quotation_pdf(quotation_id, tenant_id, employee_id):
    """
    Generate and return quotation as PDF
    
    Returns:
        PDF file with quotation details matching Aztec Interiors design
    """
    db_session = SessionLocal()
    
    try:
        # Fetch quotation data
        from sqlalchemy import text
        
        query = text("""
            SELECT 
                q.quotation_id,
                q.customer_name,
                q.customer_address,
                q.customer_phone,
                q.customer_email,
                q.date,
                q.subtotal,
                q.vat,
                q.total,
                q.vat_percentage
            FROM "StreemLyne_MT"."Quotation_Master" q
            WHERE q.tenant_id = :tenant_id
                AND q.quotation_id = :quotation_id
        """)
        
        quotation = db_session.execute(query, {
            'tenant_id': str(tenant_id),
            'quotation_id': quotation_id
        }).fetchone()
        
        if not quotation:
            return jsonify({'error': 'Quotation not found'}), 404
        
        # Fetch quotation items
        items_query = text("""
            SELECT 
                item,
                description,
                colour,
                quantity,
                unit_price,
                amount,
                width,
                height,
                depth
            FROM "StreemLyne_MT"."Quotation_Items"
            WHERE tenant_id = :tenant_id
                AND quotation_id = :quotation_id
            ORDER BY item_id
        """)
        
        items = db_session.execute(items_query, {
            'tenant_id': str(tenant_id),
            'quotation_id': quotation_id
        }).fetchall()
        
        # Create PDF in memory
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Set up measurements
        margin = 15 * mm
        
        # ============================================================
        # COMPANY HEADER
        # ============================================================
        
        # Company Name
        pdf.setFont("Helvetica-Bold", 24)
        pdf.drawCentredString(width / 2, height - 40, "AZTEC INTERIORS")
        
        # Company Registration (Green background)
        pdf.setFillColorRGB(0.565, 0.933, 0.565)  # Light green
        pdf.rect(margin, height - 70, width - 2 * margin, 15 * mm, fill=True, stroke=False)
        
        pdf.setFillColorRGB(0, 0, 0)  # Black text
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(margin + 3 * mm, height - 55, "Registered to England No 5246881")
        pdf.drawString(margin + 3 * mm, height - 62, "VAT Reg No.686 8010 72")
        
        # Bank Details (Yellow background)
        pdf.setFillColorRGB(1, 1, 0.6)  # Light yellow
        pdf.rect(margin, height - 92, width - 2 * margin, 20 * mm, fill=True, stroke=False)
        
        pdf.setFillColorRGB(0, 0, 0)
        pdf.drawString(margin + 3 * mm, height - 78, "Acc name : Aztec Interiors Leicester LTD")
        pdf.drawString(margin + 3 * mm, height - 85, "Bank : HSBC")
        pdf.drawString(margin + 3 * mm, height - 92, "s/code: 40 28 06")
        pdf.drawString(margin + 3 * mm, height - 99, "acc no: 43820343")
        
        # Reference Note (Gray background)
        pdf.setFillColorRGB(0.94, 0.94, 0.94)  # Light gray
        pdf.rect(margin, height - 108, width - 2 * margin, 8 * mm, fill=True, stroke=False)
        
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin + 3 * mm, height - 103, "Please use your name and/or road name as reference:")
        
        # QUOTATION Title
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawCentredString(width / 2, height - 125, "QUOTATION")
        
        # ============================================================
        # CUSTOMER INFORMATION TABLE
        # ============================================================
        
        customer_y = height - 150
        
        # Customer info box
        customer_data = [
            ['DATE:', quotation.date or datetime.now().strftime('%Y-%m-%d')],
            ['NAME:', quotation.customer_name or ''],
            ['ADDRESS:', quotation.customer_address or ''],
            ['TEL:', quotation.customer_phone or ''],
        ]
        
        customer_table = Table(customer_data, colWidths=[40 * mm, (width - 2 * margin - 40 * mm)])
        customer_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 9),
            ('FONT', (1, 0), (1, -1), 'Helvetica', 9),
            ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.96, 0.96, 0.96)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3 * mm),
            ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ]))
        
        customer_table.wrapOn(pdf, width, height)
        customer_table.drawOn(pdf, margin, customer_y - 35 * mm)
        
        # ============================================================
        # ITEMS TABLE
        # ============================================================
        
        items_y = customer_y - 50 * mm
        
        # Table headers
        items_data = [['ITEM', 'DESCRIPTION', 'COLOUR', 'QTY', 'WIDTH', 'HEIGHT', 'DEPTH', 'PRICE', 'AMOUNT']]
        
        # Add items
        for item in items:
            items_data.append([
                item.item or '',
                item.description or '',
                item.colour or '',
                str(item.quantity or 1),
                str(item.width) if item.width else '—',
                str(item.height) if item.height else '—',
                str(item.depth) if item.depth else '—',
                f"£{float(item.unit_price or 0):.2f}",
                f"£{float(item.amount or 0):.2f}"
            ])
        
        items_table = Table(items_data, colWidths=[
            25 * mm,  # ITEM
            50 * mm,  # DESCRIPTION
            20 * mm,  # COLOUR
            12 * mm,  # QTY
            15 * mm,  # WIDTH
            15 * mm,  # HEIGHT
            15 * mm,  # DEPTH
            20 * mm,  # PRICE
            25 * mm   # AMOUNT
        ])
        
        items_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),  # Header
            ('FONT', (0, 1), (-1, -1), 'Helvetica', 8),       # Body
            ('BACKGROUND', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),             # Header centered
            ('ALIGN', (3, 1), (6, -1), 'CENTER'),             # QTY, WIDTH, HEIGHT, DEPTH centered
            ('ALIGN', (7, 1), (8, -1), 'RIGHT'),              # PRICE, AMOUNT right-aligned
            ('FONTNAME', (8, 1), (8, -1), 'Helvetica-Bold'),  # AMOUNT bold
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ]))
        
        # Calculate height needed for items table
        items_table_height = (len(items_data) * 6) * mm  # Approximate
        
        items_table.wrapOn(pdf, width, height)
        items_table.drawOn(pdf, margin, items_y - items_table_height)
        
        # ============================================================
        # TOTALS TABLE
        # ============================================================
        
        totals_y = items_y - items_table_height - 10 * mm
        totals_x = width - margin - 80 * mm  # Right-aligned, 80mm wide
        
        vat_percentage = quotation.vat_percentage or 20
        
        totals_data = [
            ['SUB TOTAL', f"£{float(quotation.subtotal):.2f}"],
            [f'VAT ({vat_percentage}%)', f"£{float(quotation.vat):.2f}"],
            ['TOTAL', f"£{float(quotation.total):.2f}"]
        ]
        
        totals_table = Table(totals_data, colWidths=[40 * mm, 40 * mm])
        totals_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 10),
            ('FONT', (1, 0), (1, 1), 'Helvetica', 10),
            ('FONT', (0, 2), (1, 2), 'Helvetica-Bold', 11),  # TOTAL row bold
            ('BACKGROUND', (0, 0), (0, -1), colors.Color(0.96, 0.96, 0.96)),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3 * mm),
            ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ]))
        
        totals_table.wrapOn(pdf, width, height)
        totals_table.drawOn(pdf, totals_x, totals_y - 30 * mm)
        
        # ============================================================
        # PAYMENT TERMS
        # ============================================================
        
        terms_y = totals_y - 50 * mm
        
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(margin, terms_y, "Only Bacs or Cash will be accepted on Delivery and Completion")
        pdf.drawString(margin, terms_y - 5 * mm, "NOTE: If you wish to proceed with this quote, you will be required to make")
        pdf.drawString(margin, terms_y - 10 * mm, "the full payment upfront")
        
        pdf.setFillColorRGB(1, 0, 0)  # Red text
        pdf.drawString(margin, terms_y - 18 * mm, "Please sign here to confirm.")
        pdf.setFillColorRGB(0, 0, 0)  # Reset to black
        
        # ============================================================
        # SIGNATURE SECTION
        # ============================================================
        
        signature_y = terms_y - 30 * mm
        
        pdf.setFont("Helvetica", 9)
        
        # Signature lines
        pdf.drawString(margin, signature_y, "Customer Signature:")
        pdf.line(margin + 45 * mm, signature_y, width - margin, signature_y)
        
        pdf.drawString(margin, signature_y - 8 * mm, "Customer Name:")
        pdf.line(margin + 45 * mm, signature_y - 8 * mm, width - margin, signature_y - 8 * mm)
        
        pdf.drawString(margin, signature_y - 16 * mm, "Date:")
        pdf.line(margin + 45 * mm, signature_y - 16 * mm, width - margin, signature_y - 16 * mm)
        
        # ============================================================
        # FINALIZE PDF
        # ============================================================
        
        pdf.showPage()
        pdf.save()
        
        buffer.seek(0)
        
        # Return PDF
        filename = f'Quotation_{quotation_id}_{quotation.customer_name.replace(" ", "_")}.pdf'
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=False,  # Display in browser, not force download
            download_name=filename
        )
        
    except Exception as e:
        print(f"❌ Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()