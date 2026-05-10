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
                        'pricelist_id': item.get('price_list_item_id')
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
    SMART auto-lookup price with BEDROOM category detection
    
    Priority:
    1. Detect category from description (robe, wardrobe, linen press, etc.)
    2. Exact item_code match in detected category
    3. Width-based code generation with bedroom suffixes
    4. Fallback to Kitchen if no category detected
    """
    db_session = SessionLocal()
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        door_type = data.get('door_type', '').strip()
        brand = data.get('brand', '').strip()
        
        print(f"🔍 Smart lookup: description='{description}', door_type='{door_type}'")
        print(f"   Description: '{description}'")
        print(f"   Door Type: '{door_type}'")
        print(f"   Brand: '{brand}'")
        
        if not description:
            return jsonify({'found': False, 'error': 'description is required'}), 400
        
        import re

        appliance_keywords = [
            'hob', 'oven', 'hood', 'microwave', 'fridge', 'freezer', 
            'dishwasher', 'washing', 'washer', 'dryer', 'extractor',
            'combi', 'warming drawer'
        ]
        
        description_lower = description.lower()
        is_appliance = any(keyword in description_lower for keyword in appliance_keywords)
        
        # Also check for model number pattern (e.g., PCR9A5I90, BFL523MB0B)
        model_pattern = r'\b[A-Z]{2,}[0-9]{2,}[A-Z0-9]{2,}\b'
        has_model_number = bool(re.search(model_pattern, description, re.IGNORECASE))
        
        if is_appliance or has_model_number:
            print(f"   🔥 DETECTED: APPLIANCE")
            return lookup_appliance(db_session, tenant_id, description, brand)
        
        # ==================================================================
        # NEW: CATEGORY DETECTION
        # ==================================================================
        category_keywords = {
            'Wardrobes': ['robe', 'wardrobe', 'corner robe', 'diagonal corner'],
            'Linen Press': ['linen press', 'linen', 'press'],
            'Wall Units': ['bridging', 'wall unit'],
            'Chest of drawers': ['drawer', 'chest', 'bdrw'],
        }
        
        detected_category = None
        description_lower = description.lower()
        
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in description_lower:
                    detected_category = category
                    print(f"🏷️ Detected category: {detected_category}")
                    break
            if detected_category:
                break
        
        # ==================================================================
        # STRATEGY 1: Direct code match
        # ==================================================================
        code_patterns = [
            r'\b(\d+R)\b',        # 40R, 50R, 60R (bedroom robes)
            r'\b(\d+RC)\b',       # 80RC, 90RC (corner robes)
            r'\b(\d+RDCNR)\b',    # 90RDCNR (diagonal corner)
            r'\b(\d+RLP)\b',      # 40RLP, 50RLP (linen press)
            r'\b(\d+BRS)\b',      # 40BRS, 50BRS (bridging)
            r'\b(\d+BDRW)\b',     # 403BDRW, 402BDRW (chest)
            r'\b(\d+BPO)\b',      # 15BPO, 30BPO (kitchen pull-out)
            r'\b(\d+BDL)\b',      # Drawerline
            r'\b(\d+BC)\b',       # Corner bases
            r'\b(\d+BDD)\b',      # Dummy drawer
            r'\b(\d+BA)\b',       # Angled base
            r'\b(\d+B)\b',        # 15B, 30B, 40B (generic base)
        ]
        
        found_code = None
        for pattern in code_patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                found_code = match.group(1).upper()
                print(f"✅ Found code '{found_code}' in description")
                break
        
        # ==================================================================
        # STRATEGY 2: Width parsing
        # ==================================================================
        width_mm = None
        mm_match = re.search(r'(\d+)\s*mm', description, re.IGNORECASE)
        if mm_match:
            width_mm = int(mm_match.group(1))
            print(f"✅ Parsed width {width_mm}mm")
        
        # Detect kitchen unit type suffix
        unit_type_suffix = ""
        if re.search(r'\bdrawerline\b', description, re.IGNORECASE):
            unit_type_suffix = "DL"
        elif re.search(r'\bdummy\b', description, re.IGNORECASE):
            unit_type_suffix = "DD"
        elif re.search(r'\bangled?\b', description, re.IGNORECASE):
            unit_type_suffix = "A"
        
        # ==================================================================
        # STRATEGY 3: Build search candidates WITH BEDROOM CODES
        # ==================================================================
        search_candidates = []
        
        if found_code:
            search_candidates.append(found_code)
        
        if width_mm:
            width_code = width_mm // 10
            
            # ==== BEDROOM-SPECIFIC CODE GENERATION ====
            if 'linen press' in description_lower or ('linen' in description_lower and 'press' in description_lower):
                # Linen press codes: 40RLP, 50RLP, etc.
                search_candidates.extend([
                    f"{width_code}RLP",
                    f"{width_mm}RLP",
                ])
                print(f"🛏️ Generated linen press codes: {width_code}RLP")
            
            elif 'bridging' in description_lower:
                # Bridging codes: 40BRS, 50BRS, etc.
                search_candidates.extend([
                    f"{width_code}BRS",
                    f"{width_mm}BRS",
                ])
                print(f"🛏️ Generated bridging codes: {width_code}BRS")
            
            elif 'corner robe' in description_lower or ('corner' in description_lower and 'robe' in description_lower):
                # Corner robe codes: 80RC, 90RC, etc.
                search_candidates.extend([
                    f"{width_code}RC",
                    f"{width_mm}RC",
                ])
                print(f"🛏️ Generated corner robe codes: {width_code}RC")
            
            elif 'diagonal' in description_lower:
                # Diagonal corner: 90RDCNR
                search_candidates.append(f"{width_code}RDCNR")
                print(f"🛏️ Generated diagonal corner code: {width_code}RDCNR")
            
            elif 'robe' in description_lower or 'wardrobe' in description_lower:
                # Standard robe codes: 40R, 50R, etc.
                search_candidates.extend([
                    f"{width_code}R",
                    f"{width_mm}R",
                ])
                print(f"🛏️ Generated robe codes: {width_code}R")
            
            elif 'drawer' in description_lower or 'chest' in description_lower:
                # Chest of drawers codes: 403BDRW, 402BDRW, 405BDRW
                # Try to detect drawer count from description
                drawer_count = None
                if '3 x' in description_lower or 'three' in description_lower or '3x' in description_lower or '3 drawer' in description_lower:
                    drawer_count = 3
                elif '2 x' in description_lower or 'two' in description_lower or '2x' in description_lower or '2 drawer' in description_lower:
                    drawer_count = 2
                elif '5 x' in description_lower or 'five' in description_lower or '5x' in description_lower or '5 drawer' in description_lower:
                    drawer_count = 5
                
                if drawer_count:
                    search_candidates.extend([
                        f"{width_code}{drawer_count}BDRW",
                        f"{width_mm}{drawer_count}BDRW",
                    ])
                    print(f"🛏️ Generated chest codes: {width_code}{drawer_count}BDRW")
                else:
                    # Try all variants if count not specified
                    for count in [2, 3, 5]:
                        search_candidates.extend([
                            f"{width_code}{count}BDRW",
                        ])
                    print(f"🛏️ Generated multiple chest codes for width {width_code}")
            
            # ==== KITCHEN CODE GENERATION (FALLBACK) ====
            if unit_type_suffix:
                search_candidates.extend([
                    f"{width_code}B{unit_type_suffix}",
                    f"{width_mm}B{unit_type_suffix}",
                ])
            
            # Generic kitchen codes
            search_candidates.extend([
                f"{width_code}BPO",
                f"{width_code}B",
                f"{width_mm}B",
            ])
        
        print(f"🔍 Search candidates: {search_candidates}")
        
        # ==================================================================
        # Door type mapping
        # ==================================================================
        DOOR_TYPE_MAP = {
            'basic slab': 'Basic Slab',
            'acrylic gloss/matt': 'Acrylic Gloss/Matt',
            'acrylic gloss': 'Acrylic Gloss/Matt',
            'acrylic matt': 'Acrylic Gloss/Matt',
            'vinyl': 'Vinyl',
            'black glass': 'Black Glass',
        }
        
        db_door_type = DOOR_TYPE_MAP.get(door_type.lower(), door_type) if door_type else None
        
        result = None
        
        # ==================================================================
        # STRATEGY 4A: Category-specific code match (BEDROOM FIRST!)
        # ==================================================================
        if detected_category and search_candidates and db_door_type:
            for code in search_candidates:
                query = text("""
                    SELECT 
                        pricelist_id, item_code, item_name, description,
                        base_price, door_type, width, height, depth, category
                    FROM "StreemLyne_MT"."PriceList_Master"
                    WHERE tenant_id = :tenant_id
                        AND category = :category
                        AND UPPER(item_code) = UPPER(:item_code)
                        AND door_type = :door_type
                    LIMIT 1
                """)
                
                result = db_session.execute(query, {
                    'tenant_id': str(tenant_id),
                    'category': detected_category,
                    'item_code': code,
                    'door_type': db_door_type
                }).fetchone()
                
                if result:
                    print(f"✅ Category match: {code} in {detected_category}")
                    break
        
        # ==================================================================
        # STRATEGY 4B: Try exact code + door type (Kitchen priority)
        # ==================================================================
        if not result and search_candidates and db_door_type:
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
                    print(f"✅ Code match: {code} + {db_door_type}")
                    break
        
        # ==================================================================
        # STRATEGY 5A: Width match in detected category
        # ==================================================================
        if not result and detected_category and width_mm:
            query = text("""
                SELECT 
                    pricelist_id, item_code, item_name, description,
                    base_price, door_type, width, height, depth, category
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND category = :category
                    AND width = :width
                ORDER BY 
                    CASE 
                        WHEN door_type = :door_type THEN 1
                        ELSE 2
                    END,
                    base_price DESC
                LIMIT 1
            """)
            
            result = db_session.execute(query, {
                'tenant_id': str(tenant_id),
                'category': detected_category,
                'width': width_mm,
                'door_type': db_door_type or 'Basic Slab'
            }).fetchone()
            
            if result:
                print(f"✅ Category width match: {width_mm}mm in {detected_category}")
        
        # ==================================================================
        # STRATEGY 5B: Width match (Kitchen priority fallback)
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
                print(f"✅ Width fallback match: {width_mm}mm")
        
        # ==================================================================
        # RETURN RESULT
        # ==================================================================
        if result:
            print(
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
            print(
                f"⚠️ NO MATCH for: '{description}' (door: {door_type})"
            )
            return jsonify({
                'found': False,
                'error': f'No pricing found. Tried codes: {search_candidates}, width: {width_mm}mm, category: {detected_category}'
            }), 404
        
    except Exception as e:
        print(f"❌ Error in smart lookup: {e}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'found': False, 'error': str(e)}), 500
    finally:
        db_session.close()

def lookup_appliance(session, tenant_id, description, brand=None):
    """
    Lookup appliance from PriceList_Master
    
    Strategy:
    1. Extract model number from description
    2. Search by model number (item_code)
    3. If brand provided, filter by brand
    4. Fallback: Search by product name (item_name)
    """
    import re
    
    print(f"\n🔥 APPLIANCE LOOKUP")
    print(f"   Description: {description}")
    print(f"   Brand: {brand}")
    
    # ====================================================================
    # STRATEGY 1: Extract model number from description
    # ====================================================================
    # Model numbers like: PCR9A5I90, BFL523MB0B, KIR81NSE0G
    model_pattern = r'\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]{2,})\b'
    model_match = re.search(model_pattern, description, re.IGNORECASE)
    
    model_number = None
    if model_match:
        model_number = model_match.group(1).upper()
        print(f"   ✅ Extracted model number: {model_number}")
    
    # ====================================================================
    # STRATEGY 2: Search by model number (item_code)
    # ====================================================================
    if model_number:
        if brand:
            # Search with brand filter
            query = text("""
                SELECT pricelist_id, item_code, item_name, description,
                       base_price, width, height, depth, door_type, brand
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                  AND category = 'Appliances'
                  AND UPPER(item_code) = :model_number
                  AND UPPER(brand) = UPPER(:brand)
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'model_number': model_number,
                'brand': brand
            }).fetchone()
        else:
            # Search without brand filter
            query = text("""
                SELECT pricelist_id, item_code, item_name, description,
                       base_price, width, height, depth, door_type, brand
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                  AND category = 'Appliances'
                  AND UPPER(item_code) = :model_number
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'model_number': model_number
            }).fetchone()
        
        if result:
            print(f"   ✅ FOUND by model: {result.item_name} - £{result.base_price}")
            
            # Extract series from description (e.g., "S6", "S4", "S2")
            series = None
            series_match = re.search(r'\(([^)]+)\)', result.description or '')
            if series_match:
                series = series_match.group(1)
            
            return jsonify({
                'found': True,
                'price': float(result.base_price),
                'item_code': result.item_code,
                'item_name': result.item_name,
                'description': result.description,
                'pricelist_id': result.pricelist_id,
                'brand': result.brand,
                'series': series,
                'door_type': result.door_type  # This is "Low"/"Mid"/"High" for appliances
            }), 200
    
    # ====================================================================
    # STRATEGY 3: Fallback - Search by product name (fuzzy match)
    # ====================================================================
    # Extract product type from description (e.g., "HOB", "Oven", "Fridge")
    product_keywords = {
        'HOB': ['hob'],
        'Oven': ['oven'],
        'Hood': ['hood', 'extractor'],
        'Microwave': ['microwave'],
        'Fridge': ['fridge'],
        'Freezer': ['freezer'],
        'Dishwasher': ['dishwasher'],
        'Washing Machine': ['washing machine', 'washing'],
        'Washer Dryer': ['washer dryer', 'washer/dryer']
    }
    
    product_name = None
    description_lower = description.lower()
    
    for product, keywords in product_keywords.items():
        for keyword in keywords:
            if keyword in description_lower:
                product_name = product
                break
        if product_name:
            break
    
    if product_name:
        print(f"   🔍 Searching by product name: {product_name}")
        
        if brand:
            query = text("""
                SELECT pricelist_id, item_code, item_name, description,
                       base_price, width, height, depth, door_type, brand
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                  AND category = 'Appliances'
                  AND LOWER(item_name) LIKE LOWER(:product_pattern)
                  AND UPPER(brand) = UPPER(:brand)
                ORDER BY base_price ASC
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'product_pattern': f'%{product_name}%',
                'brand': brand
            }).fetchone()
        else:
            query = text("""
                SELECT pricelist_id, item_code, item_name, description,
                       base_price, width, height, depth, door_type, brand
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                  AND category = 'Appliances'
                  AND LOWER(item_name) LIKE LOWER(:product_pattern)
                ORDER BY base_price ASC
                LIMIT 1
            """)
            
            result = session.execute(query, {
                'tenant_id': str(tenant_id),
                'product_pattern': f'%{product_name}%'
            }).fetchone()
        
        if result:
            print(f"   ✅ FOUND by product name: {result.item_name} - £{result.base_price}")
            
            series = None
            series_match = re.search(r'\(([^)]+)\)', result.description or '')
            if series_match:
                series = series_match.group(1)
            
            return jsonify({
                'found': True,
                'price': float(result.base_price),
                'item_code': result.item_code,
                'item_name': result.item_name,
                'description': result.description,
                'pricelist_id': result.pricelist_id,
                'brand': result.brand,
                'series': series,
                'door_type': result.door_type
            }), 200
    
    # ====================================================================
    # NOT FOUND
    # ====================================================================
    print(f"   ❌ NO MATCH for appliance: {description}")
    return jsonify({
        'found': False,
        'error': f'No appliance found matching: {description}'
    }), 404