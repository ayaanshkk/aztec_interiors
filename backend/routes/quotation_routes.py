from email.quoprimime import quote
from unicodedata import category

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
        client_id = (
            request.args.get('client_id') or
            request.args.get('customer_id') or
            request.args.get('id')
        )
        if client_id:
            where_conditions.append("q.client_id = :client_id")
            params['client_id'] = int(client_id)
        else:
            return jsonify([]), 200
        
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
                 WHERE quotation_id = q.quotation_id) as items_count,
                (SELECT COALESCE(SUM(amount * quantity), 0) FROM "StreemLyne_MT"."Quotation_Items"
                 WHERE quotation_id = q.quotation_id
                ) as computed_subtotal,
                (
                    SELECT json_agg(json_build_object('section', section, 'total', section_total))
                    FROM (
                        SELECT section, SUM(amount * quantity) as section_total
                        FROM "StreemLyne_MT"."Quotation_Items"
                        WHERE quotation_id = q.quotation_id
                        GROUP BY section
                    ) s
                ) as section_totals_json
            FROM "StreemLyne_MT"."Quotations" q
            INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
            WHERE {where_clause}
            ORDER BY q.created_at DESC
        """)
        
        quotations = session.execute(query, params).fetchall()
        
        result = []
        for q in quotations:
            subtotal = float(q.computed_subtotal or 0)
            discount_pct = float(getattr(q, 'global_discount_percent', 0) or 0)
            vat_pct = float(getattr(q, 'vat_percentage', 20)) if getattr(q, 'vat_percentage', None) is not None else 20.0

            # Parse section discounts
            section_discounts_raw = getattr(q, 'section_discounts', None)
            section_discounts = {}
            if section_discounts_raw:
                try:
                    section_discounts = json.loads(section_discounts_raw) if isinstance(section_discounts_raw, str) else section_discounts_raw
                except:
                    section_discounts = {}

            # Apply section discounts using pre-aggregated section totals from SQL
            discounted_subtotal_result = session.execute(text("""
                SELECT COALESCE(SUM(discounted_amount), 0) as discounted_subtotal
                FROM "StreemLyne_MT"."Quotation_Items"
                WHERE quotation_id = :qid
            """), {'qid': q.quotation_id}).fetchone()

            subtotal_after_section_discounts = float(discounted_subtotal_result.discounted_subtotal or 0)

            subtotal_after_discount = subtotal_after_section_discounts - (subtotal_after_section_discounts * discount_pct / 100)
            vat_amount = subtotal_after_discount * (vat_pct / 100)
            computed_total = subtotal_after_discount + vat_amount

            result.append({
                'id': q.quotation_id,
                'quotation_id': q.quotation_id,
                'reference_number': q.reference_number,
                'client_id': q.client_id,
                'customer_id': q.client_id,
                'client_name': q.client_company_name,
                'customer_name': q.client_company_name,
                'project_id': q.project_id,
                'room_name': getattr(q, 'room_name', '') or '',
                'subtotal': subtotal,
                'discount_percent': discount_pct,
                'vat_percentage': vat_pct,
                'vat_amount': vat_amount,
                'total': computed_total,
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
        today_str = datetime.utcnow().strftime('%Y%m%d')
        seq_query = text("""
            SELECT COALESCE(MAX(
                CAST(NULLIF(REGEXP_REPLACE(reference_number, '^Q-\\d{8}-(\\d+)$', '\\1'), reference_number) AS INTEGER)
            ), 0) as max_seq
            FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tenant_id
              AND reference_number LIKE :pattern
        """)
        max_seq = session.execute(seq_query, {
            'tenant_id': str(tenant_id),
            'pattern': f'Q-{today_str}-%'
        }).fetchone().max_seq
        ref_num = f"Q-{today_str}-{max_seq + 1:03d}"
        
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
             customer_name, customer_address, customer_phone, customer_email, vat_percentage, door_type, room_type,
             carcass_colour, door_colour, panelwork_colour, door_style, room_name, section_discounts, filler_type)
            VALUES (:tenant_id, :client_id, :project_id, :reference_number, :total, :status, :notes, :employee_id,
                    :customer_name, :customer_address, :customer_phone, :customer_email, :vat_percentage, :door_type, :room_type,
                    :carcass_colour, :door_colour, :panelwork_colour, :door_style, :room_name, :section_discounts, :filler_type)
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
            'vat_percentage': data.get('vat_percentage', 20.0),
            'door_type': data.get('door_type', 'Carcass Only'),
            'room_type': data.get('room_type', 'Kitchen'),
            'carcass_colour': data.get('carcass_colour', ''),
            'door_colour': data.get('door_colour', ''),
            'panelwork_colour': data.get('panelwork_colour', ''),
            'door_style': data.get('door_style', ''),
            'room_name': data.get('room_name', ''),
            'section_discounts': json.dumps(data.get('section_discounts', {})),
            'filler_type': data.get('filler_type') or data.get('filler_door_type', 'Basic Slab'),

        })
        
        quotation_id = result.fetchone().quotation_id
        
        # Add items
        item_insert = text("""
            INSERT INTO "StreemLyne_MT"."Quotation_Items"
            (quotation_id, item_name, description, color, quantity, amount,
            width, height, depth, needs_manual_pricing, pricelist_id,
            discount_percent, discounted_amount, parent_item_id, section)
            VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                    :width, :height, :depth, :needs_manual, :pricelist_id,
                    :discount_percent, :discounted_amount, :parent_item_id, :section)
            RETURNING item_id
        """)

        for item in items_data:
            result = session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item.get('item', ''),
                'description': item.get('description', ''),
                'color': item.get('colour') or item.get('color') or '',
                'quantity': item.get('quantity') or 1,
                'amount': item.get('amount', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('price_list_item_id'),
                'discount_percent': item.get('discount_percent', 0),
                'discounted_amount': item.get('discounted_amount', float(item.get('amount', 0)) * int(item.get('quantity', 1))),
                'parent_item_id': None,
                'section': item.get('section', 'Furniture'),
            })

            parent_item_id = result.fetchone().item_id

            for sub in item.get('subItems', []):
                if not sub.get('item') and not sub.get('description') and not sub.get('amount'):
                    continue
                session.execute(item_insert, {
                    'quotation_id': quotation_id,
                    'item_name': sub.get('item', ''),
                    'description': sub.get('description', ''),
                    'color': sub.get('colour') or sub.get('color') or '',
                    'quantity': sub.get('quantity') or 1,
                    'amount': sub.get('amount', 0),
                    'width': sub.get('width'),
                    'height': sub.get('height'),
                    'depth': sub.get('depth'),
                    'needs_manual': sub.get('needs_manual_pricing', False),
                    'pricelist_id': sub.get('price_list_item_id'),
                    'discount_percent': sub.get('discount_percent', 0),
                    'discounted_amount': sub.get('discounted_amount', float(sub.get('amount', 0)) * int(sub.get('quantity', 1))),
                    'parent_item_id': parent_item_id,
                    'section': item.get('section', 'Furniture'),
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
            SELECT quotation_id FROM "StreemLyne_MT"."Quotations"
            WHERE tenant_id = :tenant_id
                AND reference_number LIKE :pattern
        """)

        existing = session.execute(existing_query, {
            'tenant_id': str(tenant_id),
            'pattern': f'%{form_submission_id}%'
        }).fetchone()

        existing_quotation_id = None
        if existing:
            existing_quotation_id = existing.quotation_id
            # Only delete items that came from the checklist auto-extraction.
            # Manually added items are preserved.
            session.execute(text("""
                DELETE FROM "StreemLyne_MT"."Quotation_Items"
                WHERE quotation_id = :qid AND source = 'checklist'
            """), {'qid': existing_quotation_id})
            session.flush()
            print(f"🔄 Cleared checklist-sourced items from quote {existing_quotation_id}, keeping manual items")
        
        # Parse form data
        form_data = json.loads(form.form_data) if isinstance(form.form_data, str) else form.form_data
        form_type = form_data.get('form_type', '').lower()
        checklist_type = 'kitchen' if 'kitchen' in form_type else 'bedroom'
        
        # ✅ NEW: Extract door_type and room_type from form data
        door_type_raw = form_data.get('door_type', '') or ''
        door_type_map = {
            'Slab': 'Basic Slab',
            'Basic Slab': 'Basic Slab',
            'Lacquered Slab': 'Acrylic Gloss/Matt',
            'Acrylic Gloss/Matt': 'Acrylic Gloss/Matt',
            'Vinyl': 'Vinyl Doors',
            'Vinyl doors': 'Vinyl Doors',
            'Black Glass': 'Black Glass',
            'Carcass Only (No Doors/Drawers)': 'Carcass Only',
            'Carcass Only': 'Carcass Only',
        }
        door_type = door_type_map.get(door_type_raw, door_type_raw or 'Basic Slab')
        
        # Determine room type from checklist type
        room_type = 'Kitchen' if checklist_type == 'kitchen' else 'Bedroom'
        
        print(f"🏷️  Checklist Type: {checklist_type}")
        print(f"🚪 Door Type: {door_type}")
        print(f"🏠 Room Type: {room_type}")
        
        # Generate reference
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        ref_num = f"Q-{timestamp}-{form_submission_id}"
        
        # Create quotation
        carcass_colour = (form_data.get('cabinet_color') or '').strip()
        door_colour = (form_data.get('door_color') or '').strip()
        panelwork_colour = (form_data.get('end_panel_color') or '').strip()
        door_style_val = (form_data.get('door_style') or '').strip()

        insert_query = text("""
            INSERT INTO "StreemLyne_MT"."Quotations"
            (tenant_id, client_id, reference_number, total, status, notes, employee_id,
             carcass_colour, door_colour, panelwork_colour, door_style, room_type, door_type)
            VALUES (:tenant_id, :client_id, :reference_number, 0, 'Draft', :notes, :employee_id,
                    :carcass_colour, :door_colour, :panelwork_colour, :door_style, :room_type, :door_type)
            RETURNING quotation_id
        """)
        
        result = session.execute(insert_query, {
            'tenant_id': str(tenant_id),
            'client_id': form.client_id,
            'reference_number': ref_num,
            'notes': f"Auto-generated from {checklist_type} checklist",
            'employee_id': employee_id,
            'carcass_colour': carcass_colour,
            'door_colour': door_colour,
            'panelwork_colour': panelwork_colour,
            'door_style': door_style_val,
            'room_type': room_type,
            'door_type': door_type,
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
             width, height, depth, needs_manual_pricing, pricelist_id, section)
            VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                    :width, :height, :depth, :needs_manual, :pricelist_id, :section)
        """)
        
        for item in extracted_items:
            session.execute(item_insert, {
                'quotation_id': quotation_id,
                'item_name': item['item'],
                'description': item['description'],
                'color': item.get('colour'),
                'quantity': item.get('qty', 1),
                'amount': item.get('amount', 0),
                'width': item.get('width'),
                'height': item.get('height'),
                'depth': item.get('depth'),
                'needs_manual': item.get('needs_manual_pricing', False),
                'pricelist_id': item.get('pricelist_id'),
                'section': item.get('section', 'Furniture'),
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
    
def _lookup_appliance_price(session, tenant_id, model_code):
    """
    Look up appliance price by exact item_code match.
    Returns (price, pricelist_id, description, needs_manual_pricing)
    """
    try:
        if not model_code or len(model_code.strip()) < 3:
            return (0.0, None, '', True)

        query = text("""
            SELECT pricelist_id, base_price, item_name, description, door_type
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
              AND category = 'Appliances'
              AND UPPER(TRIM(item_code)) = UPPER(TRIM(:model_code))
            LIMIT 1
        """)

        result = session.execute(query, {
            'tenant_id': str(tenant_id),
            'model_code': model_code.strip(),
        }).fetchone()

        if result and result.base_price:
            desc = result.description or result.item_name or ''
            print(f"✅ Appliance match: '{model_code}' → £{result.base_price} | {desc}")
            return (float(result.base_price), result.pricelist_id, desc, False)

        # ── Alias fallback ──────────────────────────────────────────────
        alias_query = text("""
            SELECT pricelist_id, base_price, item_name, description, door_type
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
              AND category = 'Appliances'
              AND alias_codes ILIKE :pattern
            LIMIT 1
        """)
        result = session.execute(alias_query, {
            'tenant_id': str(tenant_id),
            'pattern': f'%{model_code.strip()}%',
        }).fetchone()

        if result and result.base_price:
            desc = result.description or result.item_name or ''
            print(f"✅ Appliance alias match: '{model_code}' → £{result.base_price} | {desc}")
            return (float(result.base_price), result.pricelist_id, desc, False)

        print(f"⚠️  No appliance found for '{model_code}'")
        return (0.0, None, '', True)

    except Exception as e:
        print(f"Error looking up appliance '{model_code}': {e}")
        return (0.0, None, '', True)


def extract_checklist_items(form_data, session, tenant_id):
    """
    Extract items from checklist and categorise into correct quote sections.
 
    Section mapping:
    - Furniture     → Main door type + additional doors
    - Handles       → handles_code + additional_handles
    - Accessories   → accessories textarea (kitchen only)
    - Worktops      → worktop_code + additional_worktops
    - Appliances    → appliances list + integ fridge/freezer (kitchen only)
    - Sink and Tap  → sink_model/sink_details + tap_model/tap_details (kitchen only)
    """
    items = []
 
    form_type = form_data.get('form_type', '').lower()
    checklist_type = 'kitchen' if 'kitchen' in form_type else 'bedroom'
 
    print(f"📋 extract_checklist_items: form_type={form_type}, checklist_type={checklist_type}")
 
    # =========================================================================
    # 1. FURNITURE — Main door + additional doors
    # =========================================================================
    door_style = (form_data.get('door_style') or '').strip()
    door_type = form_data.get('door_type', '').strip()
    door_color = form_data.get('door_color', '').strip()
    panel_color = (form_data.get('end_panel_color') or '').strip()
    plinth_color = (form_data.get('plinth_filler_color') or '').strip()
    cabinet_color = (form_data.get('cabinet_color') or '').strip()

    if door_type and door_type not in ('N/A', ''):
        door_label = door_style if door_style and door_style not in ('N/A', '') else door_type
        items.append({
            'item': f'Door - {door_type}',
            'description': door_label,
            'colour': door_color if door_color and door_color != 'N/A' else '',
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True,
            'section': 'Furniture',
        })
        print(f"   [Furniture] Main door: {door_type} ({door_style}) — {door_color}")

    if panel_color and panel_color not in ('N/A', ''):
        items.append({
            'item': 'End Panel',
            'description': 'Panel colour',
            'colour': panel_color,
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True,
            'section': 'Fillers and End Panels',
        })
        print(f"   [Fillers and End Panels] Panel colour: {panel_color}")

    if plinth_color and plinth_color not in ('N/A', ''):
        items.append({
            'item': 'Plinth/Filler',
            'description': 'Plinth/filler colour',
            'colour': plinth_color,
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True,
            'section': 'Fillers and End Panels',
        })
        print(f"   [Fillers and End Panels] Plinth/Filler colour: {plinth_color}")

    if cabinet_color and cabinet_color not in ('N/A', ''):
        items.append({
            'item': 'Cabinet',
            'description': 'Cabinet colour',
            'colour': cabinet_color,
            'qty': 1,
            'price': 0,
            'amount': 0,
            'pricelist_id': None,
            'needs_manual_pricing': True,
            'section': 'Furniture',
        })
        print(f"   [Furniture] Cabinet colour: {cabinet_color}")
 
    additional_doors = form_data.get('additional_doors', [])
    if isinstance(additional_doors, list):
        for idx, door in enumerate(additional_doors):
            if not isinstance(door, dict):
                continue
            add_door_type = (door.get('door_type') or door.get('door_style') or '').strip()
            add_door_color = (door.get('door_color') or '').strip()
            add_qty_raw = str(door.get('quantity', '') or '').strip()
            if not add_door_type or add_door_type in ('N/A', ''):
                continue
            try:
                qty = int(add_qty_raw) if add_qty_raw and add_qty_raw != 'N/A' else 1
            except ValueError:
                qty = 1
            if qty <= 0:
                continue
            items.append({
                'item': f'Door - {add_door_type}',
                'description': '',
                'colour': add_door_color if add_door_color and add_door_color != 'N/A' else '',
                'qty': qty,
                'price': 0,
                'amount': 0,
                'pricelist_id': None,
                'needs_manual_pricing': True,
                'section': 'Furniture',
            })
            print(f"   [Furniture] Additional door {idx+1}: {add_door_type} ({add_door_color}) x{qty}")
 
    # =========================================================================
    # 2. HANDLES — handles_code + additional_handles
    # =========================================================================
    handles_code = form_data.get('handles_code', '').strip()
    handles_qty_raw = str(form_data.get('handles_quantity', '') or '').strip()
 
    if handles_code and handles_code not in ('N/A', ''):
        handle_price, handle_pricelist_id, _, needs_pricing, handle_desc = find_price_for_item(
            session, tenant_id, 'handle', 'Handles', handles_code
        )
        try:
            qty = int(handles_qty_raw) if handles_qty_raw and handles_qty_raw != 'N/A' else 1
        except ValueError:
            qty = 1
 
        items.append({
            'item': handles_code,
            'description': handle_desc,
            'colour': '',
            'qty': qty,
            'price': handle_price,
            'amount': handle_price,
            'pricelist_id': handle_pricelist_id,
            'needs_manual_pricing': needs_pricing,
            'section': 'Handles',
        })
        print(f"   [Handles] {handles_code} x{qty} → £{handle_price}")
 
    additional_handles = form_data.get('additional_handles', [])
    if isinstance(additional_handles, list):
        for idx, handle in enumerate(additional_handles):
            if not isinstance(handle, dict):
                continue
            add_code = (handle.get('handles_code') or '').strip()
            add_qty_raw = str(handle.get('handles_quantity', '') or '').strip()
            if not add_code or add_code in ('N/A', ''):
                continue
            add_price, add_pricelist_id, _, add_needs, add_desc = find_price_for_item(
                session, tenant_id, 'handle', 'Handles', add_code
            )
            try:
                add_qty = int(add_qty_raw) if add_qty_raw and add_qty_raw != 'N/A' else 1
            except ValueError:
                add_qty = 1
            items.append({
                'item': add_code,
                'description': add_desc,
                'colour': '',
                'qty': add_qty,
                'price': add_price,
                'amount': add_price,
                'pricelist_id': add_pricelist_id,
                'needs_manual_pricing': add_needs,
                'section': 'Handles',
            })
            print(f"   [Handles] Additional {idx+1}: {add_code} x{add_qty} → £{add_price}")
 
    # =========================================================================
    # 3. ACCESSORIES — Kitchen only
    # =========================================================================
    if checklist_type == 'kitchen':
        accessories_text = form_data.get('accessories', '').strip()
        if accessories_text and accessories_text not in ('N/A', ''):
            raw_entries = [a.strip() for a in accessories_text.replace('\n', ',').split(',') if a.strip()]
            for acc_entry in raw_entries:
                if not acc_entry or acc_entry in ('N/A', ''):
                    continue
                acc_price, acc_pricelist_id, _, acc_needs, acc_desc = find_price_for_item(
                    session, tenant_id, 'accessory', 'Accessories', acc_entry
                )
                items.append({
                    'item': acc_entry,
                    'description': acc_desc,
                    'colour': '',
                    'qty': 1,
                    'price': acc_price,
                    'amount': acc_price,
                    'pricelist_id': acc_pricelist_id,
                    'needs_manual_pricing': acc_needs,
                    'section': 'Accessories',
                })
                print(f"   [Accessories] {acc_entry} → £{acc_price}")
 
    # =========================================================================
    # 4. WORKTOPS — worktop_code + additional_worktops
    # =========================================================================
    def _add_worktop(code, color, label=''):
        code = (code or '').strip()
        color = (color or '').strip()
        if not code or code in ('N/A', ''):
            return
        wt_price, wt_pricelist_id, _, wt_needs, wt_desc = find_price_for_item(
            session, tenant_id, 'worktop', 'Worktops', code
        )
        items.append({
            'item': code,
            'description': wt_desc,
            'colour': color if color and color != 'N/A' else '',
            'qty': 1,
            'price': wt_price,
            'amount': wt_price,
            'pricelist_id': wt_pricelist_id,
            'needs_manual_pricing': wt_needs,
            'section': 'Worktops',
        })
        print(f"   [Worktops]{label} {code} ({color}) → £{wt_price}")
 
    _add_worktop(
        form_data.get('worktop_code', ''),
        form_data.get('worktop_material_color', '')
    )
 
    additional_worktops = form_data.get('additional_worktops', [])
    if isinstance(additional_worktops, list):
        for idx, wt in enumerate(additional_worktops):
            if not isinstance(wt, dict):
                continue
            _add_worktop(
                wt.get('worktop_code', ''),
                wt.get('worktop_material_color', ''),
                label=f' (additional {idx+1})'
            )
 
    # =========================================================================
    # 5. APPLIANCES — Kitchen only
    # =========================================================================
    if checklist_type == 'kitchen':
        appliances_owned = form_data.get('appliances_customer_owned', '').strip()
        print(f"🔍 All form_data keys: {list(form_data.keys())}")
 
        if appliances_owned and appliances_owned.lower() not in ('n/a', ''):
            standard_appliance_names = [
                "Oven", "Microwave", "Washing Machine", "Dryer",
                "HOB", "Extractor", "INTG Dishwasher"
            ]
            appliances = form_data.get('appliances', [])
 
            if isinstance(appliances, list):
                for idx, app in enumerate(appliances[:7]):
                    if not isinstance(app, dict):
                        continue
                    make = (app.get('make') or '').strip()
                    model = (app.get('model') or '').strip()
                    if (not make or make == 'N/A') and (not model or model == 'N/A'):
                        continue
 
                    appliance_name = standard_appliance_names[idx] if idx < len(standard_appliance_names) else f'Appliance {idx+1}'
                    lookup_code = model if model and model != 'N/A' else appliance_name
                    app_price, app_pricelist_id, app_desc, app_needs = _lookup_appliance_price(
                        session, tenant_id, lookup_code
                    )
                    items.append({
                        'item': model if model and model != 'N/A' else appliance_name,
                        'description': app_desc,
                        'colour': '',
                        'qty': 1,
                        'price': app_price,
                        'amount': app_price,
                        'pricelist_id': app_pricelist_id,
                        'needs_manual_pricing': app_needs,
                        'section': 'Appliances',
                    })
                    print(f"   [Appliances] {appliance_name}: {make} {model} → £{app_price}")

            additional_appliances = form_data.get('additional_appliances', [])
            if isinstance(additional_appliances, list):
                for add_app in additional_appliances:
                    if not isinstance(add_app, dict):
                        continue
                    add_label = (add_app.get('label') or '').strip()
                    add_make  = (add_app.get('make') or '').strip()
                    add_model = (add_app.get('model') or '').strip()
                    if (not add_make or add_make == 'N/A') and (not add_model or add_model == 'N/A'):
                        continue
                    lookup_code = add_model if add_model and add_model != 'N/A' else add_label
                    app_price, app_pricelist_id, app_desc, app_needs = _lookup_appliance_price(
                        session, tenant_id, lookup_code
                    )
                    items.append({
                        'item': add_model if add_model and add_model != 'N/A' else add_label,
                        'description': app_desc,
                        'colour': '',
                        'qty': 1,
                        'price': app_price,
                        'amount': app_price,
                        'pricelist_id': app_pricelist_id,
                        'needs_manual_pricing': app_needs,
                        'section': 'Appliances',
                    })
                    print(f"   [Appliances] Additional {add_label}: {add_make} {add_model} → £{app_price}")
 
            # INTG Fridge
            integ_fridge_make = form_data.get('integ_fridge_make', '').strip()
            integ_fridge_model = form_data.get('integ_fridge_model', '').strip()
            if integ_fridge_make and integ_fridge_make != 'N/A':
                try:
                    fridge_qty = int(str(form_data.get('integ_fridge_qty', '') or '').strip() or 1)
                except ValueError:
                    fridge_qty = 1
                lookup = integ_fridge_model if integ_fridge_model and integ_fridge_model != 'N/A' else 'INTG Fridge'
                f_price, f_pid, f_desc, f_needs = _lookup_appliance_price(session, tenant_id, lookup)
                items.append({
                    'item': lookup,
                    'description': f_desc,
                    'colour': '',
                    'qty': fridge_qty,
                    'price': f_price,
                    'amount': f_price,
                    'pricelist_id': f_pid,
                    'needs_manual_pricing': f_needs,
                    'section': 'Appliances',
                })
                print(f"   [Appliances] INTG Fridge: {integ_fridge_make} x{fridge_qty} → £{f_price}")
 
            # INTG Freezer
            integ_freezer_make = form_data.get('integ_freezer_make', '').strip()
            integ_freezer_model = form_data.get('integ_freezer_model', '').strip()
            if integ_freezer_make and integ_freezer_make != 'N/A':
                try:
                    freezer_qty = int(str(form_data.get('integ_freezer_qty', '') or '').strip() or 1)
                except ValueError:
                    freezer_qty = 1
                lookup = integ_freezer_model if integ_freezer_model and integ_freezer_model != 'N/A' else 'INTG Freezer'
                fz_price, fz_pid, fz_desc, fz_needs = _lookup_appliance_price(session, tenant_id, lookup)

                items.append({
                    'item': lookup,
                    'description': fz_desc,
                    'colour': '',
                    'qty': freezer_qty,
                    'price': fz_price,
                    'amount': fz_price,
                    'pricelist_id': fz_pid,
                    'needs_manual_pricing': fz_needs,
                    'section': 'Appliances',
                })
                print(f"   [Appliances] INTG Freezer: {integ_freezer_make} x{freezer_qty} → £{fz_price}")



            # Other / Misc Appliances
            other_appliances = form_data.get('other_appliances', '').strip()
            if other_appliances and other_appliances not in ('N/A', ''):
                other_codes = [c.strip() for c in other_appliances.split(',') if c.strip() and c.strip() != 'N/A']
                for code in other_codes:
                    o_price, o_pid, o_desc, o_needs = _lookup_appliance_price(session, tenant_id, code)
                    items.append({
                        'item': code,
                        'description': o_desc,
                        'colour': '',
                        'qty': 1,
                        'price': o_price,
                        'amount': o_price,
                        'pricelist_id': o_pid,
                        'needs_manual_pricing': o_needs,
                        'section': 'Appliances',
                    })
                    print(f"   [Appliances] Other/Misc: {code} → £{o_price}")
 
    # =========================================================================
    # 6. SINK AND TAP — Kitchen only
    # =========================================================================
    if checklist_type == 'kitchen':
        sink_owned = form_data.get('sink_tap_customer_owned', '').strip()
 
        if sink_owned and sink_owned.lower() not in ('n/a', ''):
            # Sink: prefer model code, fall back to details text
            sink_model = form_data.get('sink_model', '').strip()
            sink_details = form_data.get('sink_details', '').strip()
            sink_lookup = sink_model if sink_model and sink_model != 'N/A' else sink_details
 
            if sink_lookup and sink_lookup != 'N/A':
                sink_codes = [s.strip() for s in sink_lookup.split(',') if s.strip() and s.strip() != 'N/A']
                for sink_code in sink_codes:
                    sink_price, sink_pid, _, sink_needs, sink_desc = find_price_for_item(
                        session, tenant_id, 'sink', 'Sink and Tap', sink_code
                    )
                    items.append({
                        'item': sink_code,
                        'description': sink_desc,
                        'colour': '',
                        'qty': 1,
                        'price': sink_price,
                        'amount': sink_price,
                        'pricelist_id': sink_pid,
                        'needs_manual_pricing': sink_needs,
                        'section': 'Sink and Tap',
                    })
                    print(f"   [Sink and Tap] Sink: {sink_code} → £{sink_price}")
 
            # Tap: prefer model code, fall back to details text
            tap_model = form_data.get('tap_model', '').strip()
            tap_details = form_data.get('tap_details', '').strip()
            tap_lookup = tap_model if tap_model and tap_model != 'N/A' else tap_details
 
            if tap_lookup and tap_lookup != 'N/A':
                tap_codes = [t.strip() for t in tap_lookup.split(',') if t.strip() and t.strip() != 'N/A']
                for tap_code in tap_codes:
                    tap_price, tap_pid, _, tap_needs, tap_desc = find_price_for_item(
                        session, tenant_id, 'tap', 'Sink and Tap', tap_code
                    )
                    items.append({
                        'item': tap_code,
                        'description': tap_desc,
                        'colour': '',
                        'qty': 1,
                        'price': tap_price,
                        'amount': tap_price,
                        'pricelist_id': tap_pid,
                        'needs_manual_pricing': tap_needs,
                        'section': 'Sink and Tap',
                    })
                    print(f"   [Sink and Tap] Tap: {tap_code} → £{tap_price}")
 
    print(f"📊 Total items extracted: {len(items)}")
    return items
 
 
def find_price_for_item(session, tenant_id, item_type, category, search_term):
    from sqlalchemy import text

    try:
        if not search_term or len(search_term.strip()) < 2:
            print(f"⚠️  Skipping lookup for '{search_term}' (too short)")
            return (0.0, None, None, True, '')

        search_term = search_term.strip()

        # ── 1. Exact item_code match ──
        exact_query = text("""
            SELECT pricelist_id, base_price, dimension_formula, item_name, description
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
              AND category = :category
              AND UPPER(TRIM(item_code)) = UPPER(TRIM(:search_term))
              AND (door_type = 'Standard' OR door_type IS NULL)
            LIMIT 1
        """)

        result = session.execute(exact_query, {
            'tenant_id': str(tenant_id),
            'category': category,
            'search_term': search_term,
        }).fetchone()

        if result and result.base_price:
            desc = result.description or result.item_name or ''
            print(f"✅ Exact item_code match: '{search_term}' → £{result.base_price} | {desc}")
            return (float(result.base_price), result.pricelist_id, result.dimension_formula, False, desc)

        # ── 2. Fuzzy item_name / description match ──
        fuzzy_query = text("""
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

        result = session.execute(fuzzy_query, {
            'tenant_id': str(tenant_id),
            'category': category,
            'search_term': f'%{search_term}%',
        }).fetchone()

        if result and result.base_price:
            desc = result.description or result.item_name or ''
            print(f"✅ Fuzzy name match: '{search_term}' → £{result.base_price} | {desc}")
            return (float(result.base_price), result.pricelist_id, result.dimension_formula, False, desc)

        print(f"⚠️  No match found for '{search_term}' in category '{category}'")
        return (0.0, None, None, True, '')

    except Exception as e:
        print(f"Error finding price for {item_type} '{search_term}': {e}")
        return (0.0, None, None, True, '')
 
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

            def item_to_dict(i):
                return {
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
                    'discount_percent': float(i.discount_percent) if hasattr(i, 'discount_percent') and i.discount_percent else 0,
                    'discounted_total': float(i.discounted_amount) if hasattr(i, 'discounted_amount') and i.discounted_amount else float(i.amount or 0) * (i.quantity or 1),
                    'width': i.width,
                    'height': i.height,
                    'depth': i.depth,
                    'needs_manual_pricing': i.needs_manual_pricing,
                    'price_list_item_id': i.pricelist_id,
                    'parent_item_id': getattr(i, 'parent_item_id', None),
                    'section': getattr(i, 'section', None) or 'Furniture',
                }

            valid_items = [
                i for i in items
                if (i.item_name and i.item_name.strip()) or (i.description and i.description.strip()) or (i.amount and float(i.amount) > 0)
            ]

            top_level = [i for i in valid_items if not getattr(i, 'parent_item_id', None)]
            sub_items_map = {}
            for i in valid_items:
                pid = getattr(i, 'parent_item_id', None)
                if pid:
                    sub_items_map.setdefault(pid, []).append(item_to_dict(i))

            items_result = []
            for i in top_level:
                d = item_to_dict(i)
                if i.item_id in sub_items_map:
                    d['subItems'] = sub_items_map[i.item_id]
                items_result.append(d)

            # ✅ NEW: Compute subtotal/total from items (source of truth — matches PDF)
            section_discounts_raw = getattr(quote, 'section_discounts', None)
            section_discounts = {}
            if section_discounts_raw:
                try:
                    section_discounts = json.loads(section_discounts_raw) if isinstance(section_discounts_raw, str) else section_discounts_raw
                except:
                    pass

            # Compute subtotal per section, apply section discounts
            SECTIONS_ORDER = ['Furniture', 'Fillers and End Panels', 'Accessories', 'Handles', 'Appliances', 'Sink and Tap', 'Worktops', 'Fittings']
            subtotal_after_section_discounts = 0.0
            raw_subtotal = 0.0
            subtotal_after_section_discounts = sum(
                float(i.discounted_amount or 0) if (i.discounted_amount and float(i.discounted_amount) > 0)
                else float(i.amount or 0) * (i.quantity or 1)
                for i in valid_items
            )

            vat_pct_val = float(quote.vat_percentage) if hasattr(quote, 'vat_percentage') and quote.vat_percentage is not None else 20.0
            discount_pct_val = float(quote.global_discount_percent) if hasattr(quote, 'global_discount_percent') and quote.global_discount_percent is not None else 0.0
            subtotal_after_global_discount = subtotal_after_section_discounts - (subtotal_after_section_discounts * discount_pct_val / 100)
            vat_amount_val = subtotal_after_global_discount * (vat_pct_val / 100)
            computed_total = subtotal_after_global_discount + vat_amount_val
            subtotal = raw_subtotal
            
            result = {
                'id': quote.quotation_id,
                'quotation_id': quote.quotation_id,
                'reference_number': quote.reference_number,
                'customer_id': str(quote.client_id),
                'customer_name': quote.customer_name or quote.client_company_name,
                'customer_address': quote.customer_address or quote.client_address,
                'customer_phone': quote.customer_phone or quote.client_phone,
                'customer_email': getattr(quote, 'customer_email', None),
                'door_type': getattr(quote, 'door_type', 'Carcass Only'),
                'room_type': getattr(quote, 'room_type', 'Kitchen'),
                'room_name': getattr(quote, 'room_name', '') or '',
                'vat_percentage': vat_pct_val,
                'global_discount_percent': discount_pct_val,
                'carcass_colour': getattr(quote, 'carcass_colour', None) or '',
                'door_colour': getattr(quote, 'door_colour', None) or '',
                'panelwork_colour': getattr(quote, 'panelwork_colour', None) or '',
                'door_style': getattr(quote, 'door_style', None) or '',
                'client_id': quote.client_id,
                'client_name': quote.client_company_name,
                'client_address': quote.client_address,
                'client_phone': quote.client_phone,
                'project_id': quote.project_id,
                'subtotal': subtotal_after_section_discounts,
                'vat_amount': vat_amount_val,
                'discount_amount': subtotal_after_section_discounts * (discount_pct_val / 100),
                'total': computed_total,
                'section_discounts': section_discounts,
                'status': quote.status,
                'notes': quote.notes,
                'section_discounts': (json.loads(quote.section_discounts) if isinstance(quote.section_discounts, str) else quote.section_discounts) if getattr(quote, 'section_discounts', None) else {},
                'created_at': quote.created_at.isoformat() if quote.created_at else None,
                'updated_at': quote.updated_at.isoformat() if quote.updated_at else None,
                'items': items_result,
                'filler_type': getattr(quote, 'filler_type', None) or 'Basic Slab',
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
            if 'global_discount_percent' in data:
                update_fields.append("global_discount_percent = :global_discount_percent")
                params['global_discount_percent'] = data['global_discount_percent']
            if 'status' in data:
                update_fields.append("status = :status")
                params['status'] = data['status']
            if 'notes' in data:
                update_fields.append("notes = :notes")
                params['notes'] = data['notes']
            if 'door_type' in data:
                update_fields.append("door_type = :door_type")
                params['door_type'] = data['door_type']
            if 'room_type' in data:
                update_fields.append("room_type = :room_type")
                params['room_type'] = data['room_type']
            if 'filler_type' in data or 'filler_door_type' in data:
                update_fields.append("filler_type = :filler_type")
                params['filler_type'] = data.get('filler_type') or data.get('filler_door_type', 'Basic Slab')
            if 'carcass_colour' in data:
                update_fields.append("carcass_colour = :carcass_colour")
                params['carcass_colour'] = data['carcass_colour']
            if 'door_colour' in data:
                update_fields.append("door_colour = :door_colour")
                params['door_colour'] = data['door_colour']
            if 'panelwork_colour' in data:
                update_fields.append("panelwork_colour = :panelwork_colour")
                params['panelwork_colour'] = data['panelwork_colour']
            if 'door_style' in data:
                update_fields.append("door_style = :door_style")
                params['door_style'] = data['door_style']
            if 'room_name' in data:
                update_fields.append("room_name = :room_name")
                params['room_name'] = data['room_name']
            if 'section_discounts' in data:
                update_fields.append("section_discounts = :section_discounts")
                params['section_discounts'] = json.dumps(data.get('section_discounts', {}))
            
            # ✅ UPDATE ITEMS
            if 'items' in data:
                # Delete all existing items
                delete_items = text("""
                    DELETE FROM "StreemLyne_MT"."Quotation_Items"
                    WHERE quotation_id = :quotation_id
                """)
                session.execute(delete_items, {'quotation_id': quotation_id})
                
                # Insert new items - returns item_id for sub-item linking
                item_insert = text("""
                    INSERT INTO "StreemLyne_MT"."Quotation_Items"
                    (quotation_id, item_name, description, color, quantity, amount,
                    width, height, depth, needs_manual_pricing, pricelist_id,
                    discount_percent, discounted_amount, parent_item_id, section)
                    VALUES (:quotation_id, :item_name, :description, :color, :quantity, :amount,
                            :width, :height, :depth, :needs_manual, :pricelist_id,
                            :discount_percent, :discounted_amount, :parent_item_id, :section)
                    RETURNING item_id
                """)
                
                # ✅ CHANGED: this is now treated as the SUBTOTAL (pre-discount, pre-VAT)
                subtotal = 0.0
                for item in data['items']:
                    # Skip completely empty items
                    if not item.get('item') and not item.get('description') and not item.get('amount'):
                        continue
                    
                    item_amount = float(item.get('amount', 0))
                    item_qty = int(item.get('quantity', 1))
                    item_section = item.get('section', 'Furniture')
                    
                    result = session.execute(item_insert, {
                        'quotation_id': quotation_id,
                        'item_name': item.get('item', ''),
                        'description': item.get('description', ''),
                        'color': item.get('colour') or item.get('color') or '',
                        'quantity': item_qty,
                        'amount': item_amount,
                        'width': item.get('width'),
                        'height': item.get('height'),
                        'depth': item.get('depth'),
                        'needs_manual': item.get('needs_manual_pricing', False),
                        'pricelist_id': item.get('price_list_item_id'),
                        'discount_percent': item.get('discount_percent', 0),
                        'discounted_amount': item.get('discounted_amount', item_amount * item_qty),
                        'parent_item_id': None,
                        'section': item_section,
                    })
                    
                    parent_item_id = result.fetchone().item_id
                    subtotal += item_amount * item_qty

                    # Insert sub-items linked to this parent
                    for sub in item.get('subItems', []):
                        if not sub.get('item') and not sub.get('description') and not sub.get('amount'):
                            continue
                        
                        sub_amount = float(sub.get('amount', 0))
                        sub_qty = int(sub.get('quantity', 1))
                        
                        session.execute(item_insert, {
                            'quotation_id': quotation_id,
                            'item_name': sub.get('item', ''),
                            'description': sub.get('description', ''),
                            'color': sub.get('colour') or sub.get('color') or '',
                            'quantity': sub_qty,
                            'amount': sub_amount,
                            'width': sub.get('width'),
                            'height': sub.get('height'),
                            'depth': sub.get('depth'),
                            'needs_manual': sub.get('needs_manual_pricing', False),
                            'pricelist_id': sub.get('price_list_item_id'),
                            'discount_percent': sub.get('discount_percent', 0),
                            'discounted_amount': sub.get('discounted_amount', sub_amount * sub_qty),
                            'parent_item_id': parent_item_id,
                            'section': item_section,
                        })
                        
                        subtotal += sub_amount * sub_qty
                
                # ✅ CHANGED: store the item subtotal in the 'total' column
                # (kept as pre-VAT/pre-discount subtotal for consistency with create_quotation)
                update_fields.append("total = :total")
                params['total'] = subtotal
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
        DOOR_TYPE_DISPLAY = {
            'Basic Slab': 'Slab',
            'Acrylic Gloss/Matt': 'Lacquered Slab',
        }

        def display_door_type(dt):
            return DOOR_TYPE_DISPLAY.get(dt, dt)

        data = request.get_json()
        description = data.get('description', '').strip().upper()
        door_type = data.get('door_type', '').strip()
        filler_door_type = data.get('filler_door_type', '').strip() or door_type  # fallback to door_type
        room_type = data.get('room_type', 'Kitchen').strip()
        brand = data.get('brand', '').strip()
        current_items = data.get('current_items', [])
        
        print(f"🔍 Smart lookup: description='{description}', door_type='{door_type}', room_type='{room_type}'")
        
        if not description:
            return jsonify({'found': False, 'error': 'description is required'}), 400
        
        import re
 
        # ========================================================================
        # SUFFIX DETECTION - Suffix means COMPONENT ONLY
        # ========================================================================
        
        # Check for suffix like "50B-BS", "PL-AG", "CF-BS", etc.
        suffix_pattern = r'^([A-Z0-9]+)-(BS|S|AG|LS|T|VD|BG|BST|ST|AGT|LST|TT|VDT|BGT|C)$'
        suffix_match = re.match(suffix_pattern, description, re.IGNORECASE)
        print(f"   🔬 DEBUG: description='{description}', suffix_match={bool(suffix_match)}, groups={suffix_match.groups() if suffix_match else None}")

        
        door_component_only = False
        door_total_mode = False  # NEW: carcass + door combined
        base_code = None
        component_door_type = None
        
        if suffix_match:
            base_code = suffix_match.group(1).upper()
            suffix = suffix_match.group(2).upper()
            
            suffix_to_door_type = {
                'BS':  'Basic Slab',
                'S':   'Basic Slab',
                'AG':  'Acrylic Gloss/Matt',
                'LS':  'Acrylic Gloss/Matt',
                'T':   'Timber',
                'V':   'Vinyl Doors',
                'VD':  'Vinyl Doors',
                'BG':  'Black Glass',
                'BST': 'Basic Slab',
                'ST':  'Basic Slab',
                'AGT': 'Acrylic Gloss/Matt',
                'LST': 'Acrylic Gloss/Matt',
                'TT':  'Timber',
                'VDT': 'Vinyl Doors',
                'BGT': 'Black Glass',
                'C':   'Carcass Only',
            }
            
            component_door_type = suffix_to_door_type.get(suffix)
            
            if suffix == 'C':
                door_component_only = False
                door_total_mode = False
                component_door_type = None
            elif suffix == 'T':
                # Single 'T' = Timber component only, not total mode
                door_component_only = True
                door_total_mode = False
            elif suffix.endswith('T'):
                door_total_mode = True
                door_component_only = False
            else:
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
                description as item_description,
                CASE category
                    WHEN 'Fillers & End Panels' THEN 1
                    WHEN 'Base Units' THEN 2
                    WHEN 'Wall Units' THEN 2
                    WHEN 'Larder Units' THEN 2
                    WHEN 'Finishing' THEN 3
                    ELSE 4
                END as cat_priority
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
                AND UPPER(TRIM(item_code)) = UPPER(:item_code)
            ORDER BY cat_priority ASC
        """)
        
        results = db_session.execute(direct_query, {
            'tenant_id': str(tenant_id),
            'item_code': search_code
        }).fetchall()
        
        # ✅ Alias fallback — checks alias_codes column
        if not results:
            alias_query = text("""
                SELECT 
                    item_code, item_name, door_type, base_price,
                    width, height, depth, category, pricelist_id,
                    description as item_description,
                    CASE category
                        WHEN 'Fillers & End Panels' THEN 1
                        WHEN 'Base Units' THEN 2
                        WHEN 'Finishing' THEN 3
                        ELSE 4
                    END as cat_priority
                FROM "StreemLyne_MT"."PriceList_Master"
                WHERE tenant_id = :tenant_id
                    AND alias_codes ILIKE :pattern
                ORDER BY cat_priority ASC
            """)
            results = db_session.execute(alias_query, {
                'tenant_id': str(tenant_id),
                'pattern': f'%{search_code}%'
            }).fetchall()
            if results:
                print(f"✅ Found via alias: {search_code} → {results[0].item_code}")
        
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
        # DRAWER FRONTS - Component-only pricing, no carcass required
        # ========================================================================

        if item_code.upper().startswith(('KDF', 'BDF', 'DF')):
            print(f"   📐 Drawer front component lookup")

            if component_door_type:
                target_door_type = component_door_type
            else:
                DOOR_TYPE_MAP = {
                    'carcass only': 'Carcass Only',
                    'basic slab': 'Basic Slab',
                    'slab': 'Basic Slab',                        # ← ADD
                    'lacquered slab': 'Acrylic Gloss/Matt',       # ← ADD
                    'acrylic gloss/matt': 'Acrylic Gloss/Matt',
                    'acrylic gloss': 'Acrylic Gloss/Matt',
                    'acrylic matt': 'Acrylic Gloss/Matt',
                    'timber': 'Timber',
                    'vinyl': 'Vinyl Doors',
                    'vinyl doors': 'Vinyl Doors',
                    'black glass': 'Black Glass',
                    'base cabinet only': 'Base Cabinet Only',
                }

                target_door_type = DOOR_TYPE_MAP.get(door_type.lower() if door_type else '', 'Basic Slab')

            price_row = next((r for r in results if r.door_type == target_door_type), None)
            if not price_row or not price_row.base_price:
                price_row = next((r for r in results if r.door_type == 'Basic Slab'), None)
                target_door_type = 'Basic Slab'

            if not price_row or not price_row.base_price:
                return jsonify({'found': False, 'error': f'No price found for {item_code}'}), 404

            price = float(price_row.base_price)
            print(f"   💰 Drawer front {target_door_type}: £{price:.2f}")

            return jsonify({
                'found': True,
                'price': price,
                'item_code': item_code,
                'item_name': item_name,
                'description': item_name,
                'door_type': target_door_type,
                'category': category,
                'width': first_result.width,
                'height': first_result.height,
                'depth': first_result.depth,
                'pricelist_id': price_row.pricelist_id
            }), 200

        # ========================================================================
        # FITTINGS - Quantity calculated from current quote items
        # ========================================================================

        if category == 'Fittings':
            print(f"   🔧 Fittings category lookup")

            price_row = next((r for r in results if r.door_type == 'Standard'), None)
            if not price_row or not price_row.base_price:
                return jsonify({'found': False, 'error': f'No price found for {item_code}'}), 404

            unit_price = float(price_row.base_price)
            calculated_qty = 1  # default

            if current_items:
                code_upper = item_code.upper()
                import re as _re

                print(f"   🔍 ALL current_items: {[(i.get('item'), i.get('quantity')) for i in current_items]}")

                # ── Category mappings ──────────────────────────────────────────
                BUNIT_CATEGORIES = {
                    'Linen Press', 'Chest of drawers', 'Bedroom Wall Units', 'Bedroom Drawer Fronts'
                }
                ROBE_CATEGORIES = {
                    'Wardrobes'
                }
                KUNIT_CATEGORIES = {
                    'Base Units', 'Larder Units', 'Larder P/O', 'Wall Units', 'Misc',
                    'Finishing', 'Kitchen', 'Dresser Units', 'Top Box', 'Quad',
                    'Fillers & End Panels'
                }
                APPL_CATEGORIES = {'Appliances'}
                SINKTAP_CATEGORIES = {'Sink and Tap'}

                # ── Helper: get category for an item code from DB ──────────────
                def get_item_category(item_code_str):
                    if not item_code_str:
                        return None
                    try:
                        cat_query = text("""
                            SELECT category FROM "StreemLyne_MT"."PriceList_Master"
                            WHERE tenant_id = :tenant_id
                              AND UPPER(item_code) = UPPER(:item_code)
                            LIMIT 1
                        """)
                        cat_result = db_session.execute(cat_query, {
                            'tenant_id': str(tenant_id),
                            'item_code': item_code_str.strip()
                        }).fetchone()
                        return cat_result.category if cat_result else None
                    except:
                        return None

                # ── Existing regex patterns (kept as fallback) ─────────────────
                non_unit_exclusions = {
                    'WB', 'WT', 'WTP', 'WF', 'WEP', 'BF', 'BEP', 'TF', 'TEP',
                    'CF', 'CR', 'PL', 'SOF', 'IBP', 'IEP', 'TWEP',
                }

                robe_pattern = _re.compile(r'^\d+R(C|DCNR)?$')
                kitchen_larder_pattern = _re.compile(
                    r'^(\d+[BWLDTQ](\d+)?'
                    r'|[0-9]+BC(LM)?'
                    r'|[0-9]+B(LC|LCC|DC|A|DD|PO|PB|PW)'
                    r'|[0-9]+W(S|A|BI|C|DC|LC)?'
                    r'|[0-9]+WT?'
                    r'|[0-9]+SD[0-9]+DRW'
                    r'|[0-9]+MD[0-9]+DRW'
                    r'|[0-9]+TD[0-9]+DRW'
                    r'|[0-9]+[0-9]+DRW'
                    r'|LM[0-9]+[A-Z]*'
                    r'|LT[0-9]+[A-Z]*'
                    r'|[0-9]+TBS?'
                    r'|[0-9]+TBM'
                    r'|[0-9]+TBT'
                    r'|CRV[A-Z0-9]+'
                    r'|[0-9]+BR[0-9]+)$',
                    _re.IGNORECASE
                )
                bedroom_pattern = _re.compile(
                    r'^(\d+R(C|DCNR)?'
                    r'|[0-9]+BRS'
                    r'|BDF[0-9-]+'
                    r'|[0-9]+BDRW)$',
                    _re.IGNORECASE
                )

                if code_upper == 'APPL':
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip()
                        cat = get_item_category(item_c)
                        if cat in APPL_CATEGORIES:
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ APPL match via category: {item_c}")
                    if calculated_qty == 0:
                        return jsonify({'found': False, 'quantity': 0}), 404

                elif code_upper == 'ROBE':
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip()
                        cat = get_item_category(item_c)
                        if cat in ROBE_CATEGORIES:
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ ROBE match via category: {item_c}")
                            continue
                        # Fallback to regex
                        if robe_pattern.match(item_c.upper()):
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ ROBE match via regex: {item_c}")

                elif code_upper == 'KUNIT':
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip()
                        if item_c.upper() in non_unit_exclusions:
                            continue
                        cat = get_item_category(item_c)
                        if cat in KUNIT_CATEGORIES:
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ KUNIT match via category: {item_c} ({cat})")
                            continue
                        # Fallback to regex
                        if kitchen_larder_pattern.match(item_c.upper()):
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ KUNIT match via regex: {item_c}")

                elif code_upper == 'BUNIT':
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip()
                        cat = get_item_category(item_c)
                        if cat in BUNIT_CATEGORIES:
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ BUNIT match via category: {item_c} ({cat})")
                            continue
                        # Fallback to regex
                        if (bedroom_pattern.match(item_c.upper())
                                and not robe_pattern.match(item_c.upper())):
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ BUNIT match via regex: {item_c}")

                elif code_upper == 'SINKTAP':
                    # ✅ SINKTAP is always qty 1 — as long as at least one Sink and Tap item exists
                    has_sinktap = False
                    for i in current_items:
                        item_c = (i.get('item') or '').strip()
                        cat = get_item_category(item_c)
                        if cat in SINKTAP_CATEGORIES:
                            has_sinktap = True
                            print(f"   ✅ SINKTAP found via category: {item_c}")
                            break
                        # Fallback to description
                        if 'sink' in (i.get('description') or '').lower():
                            has_sinktap = True
                            break
                    
                    if not has_sinktap:
                        return jsonify({'found': False, 'quantity': 0}), 404
                    
                    calculated_qty = 1  # Always 1 regardless of how many sink/tap items
                    print(f"   ✅ SINKTAP qty fixed at 1")

                elif code_upper == 'WTJT':
                    calculated_qty = sum(
                        int(i.get('quantity', 1))
                        for i in current_items
                        if 'worktop' in (i.get('description') or '').lower()
                    )

                elif code_upper == 'FITDR':
                    DOOR_ITEM_CODES = {'FITDR', 'DR', 'DOOR'}
                    DOOR_CATEGORIES = {'Doors', 'Internal Doors', 'External Doors'}
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip().upper()
                        cat = get_item_category(item_c)
                        # Only match items explicitly categorised as doors
                        if cat in DOOR_CATEGORIES or item_c in DOOR_ITEM_CODES:
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ FITDR match: {item_c} ({cat})")

                elif code_upper == 'PANW':
                    panel_codes = {
                        'BEP', 'BF', 'CF', 'CR', 'IBP', 'IEP', 'PL',
                        'SOF', 'TEP', 'TF', 'TWEP', 'WEP', 'WF', 'WTP'
                    }
                    calculated_qty = 0
                    for i in current_items:
                        item_c = (i.get('item') or '').strip().upper()
                        cat = get_item_category(item_c)
                        if item_c in panel_codes or cat == 'Fillers & End Panels':
                            calculated_qty += int(i.get('quantity', 1))
                            print(f"   ✅ PANW match: {item_c} ({cat})")

                if calculated_qty <= 0:
                    calculated_qty = 1 if not current_items else 0

            print(f"   💰 Fitting: {item_name} — qty={calculated_qty}, unit=£{unit_price:.2f}, total=£{unit_price * calculated_qty:.2f}")

            if calculated_qty == 0:
                return jsonify({'found': False, 'quantity': 0}), 404

            return jsonify({
                'found': True,
                'price': unit_price,
                'quantity': calculated_qty,
                'item_code': item_code,
                'item_name': item_name,
                'description': price_row.item_description or item_name,
                'door_type': 'Standard',
                'category': category,
                'pricelist_id': price_row.pricelist_id,
                'is_fitting': True
            }), 200
        
        # ========================================================================
        # ACCESSORIES & HANDLES - Single price, no door types
        # ========================================================================
        
        if category in ['Accessories', 'Handles', 'Sink and Tap', 'Worktops']:
            print(f"   📦 {category} category - single price lookup")
            
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
            else:
                DOOR_TYPE_MAP = {
                    'basic slab': 'Basic Slab',
                    'slab': 'Basic Slab',
                    'lacquered slab': 'Acrylic Gloss/Matt',
                    'acrylic gloss/matt': 'Acrylic Gloss/Matt',
                    'acrylic gloss': 'Acrylic Gloss/Matt',
                    'acrylic matt': 'Acrylic Gloss/Matt',
                    'timber': 'Timber',
                    'vinyl': 'Vinyl Doors',
                    'vinyl doors': 'Vinyl Doors',
                    'black glass': 'Vinyl Doors',
                }
                target_door_type = DOOR_TYPE_MAP.get(filler_door_type.lower() if filler_door_type else '', 'Basic Slab')
            
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
                'description': f"{item_name} - {display_door_type(target_door_type)}",
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
            'slab': 'Basic Slab',                        # ← ADD
            'lacquered slab': 'Acrylic Gloss/Matt',       # ← ADD
            'acrylic gloss/matt': 'Acrylic Gloss/Matt',
            'acrylic gloss': 'Acrylic Gloss/Matt',
            'acrylic matt': 'Acrylic Gloss/Matt',
            'timber': 'Timber',
            'vinyl': 'Vinyl Doors',
            'vinyl doors': 'Vinyl Doors',
            'black glass': 'Black Glass',
            'base cabinet only': 'Base Cabinet Only',
        }
        
        if not (suffix_match and suffix_match.group(2).upper() == 'C'):
            db_door_type = DOOR_TYPE_MAP.get(door_type.lower(), door_type) if door_type else None
        if suffix_match and suffix_match.group(2).upper() == 'C':
            db_door_type = 'Carcass Only'
        print(f"   🚪 db_door_type resolved: '{db_door_type}' (from door_type='{door_type}')")
        
        # ========================================================================
        # SUFFIX MODE - Return door component ONLY
        # ========================================================================
        
        if (door_component_only or door_total_mode) and component_door_type:
            door_row = next((r for r in results if r.door_type == component_door_type), None)
            
            if not door_row or not door_row.base_price:
                return jsonify({
                    'found': False,
                    'error': f'No {component_door_type} door component found for {item_code}'
                }), 404
            
            door_price = float(door_row.base_price)

            if door_total_mode:
                # Carcass + door combined total
                carcass_row = next((r for r in results if r.door_type == 'Carcass Only'), None)
                carcass_price = float(carcass_row.base_price) if carcass_row and carcass_row.base_price else 0.0
                final_price = carcass_price + door_price
                
                print(f"   💰 TOTAL MODE: Carcass £{carcass_price:.2f} + {component_door_type} £{door_price:.2f} = £{final_price:.2f}")
                
                return jsonify({
                    'found': True,
                    'price': final_price,
                    'item_code': item_code,
                    'item_name': item_name,
                    'description': f"{item_name} - {display_door_type(component_door_type)} (Total)",
                    'door_type': component_door_type,
                    'category': category,
                    'width': first_result.width,
                    'height': first_result.height,
                    'depth': first_result.depth,
                    'pricelist_id': door_row.pricelist_id,
                    'component_only': False,
                    'breakdown': {
                        'carcass': carcass_price,
                        'door_component': door_price
                    }
                }), 200
            else:
                # Door component only
                print(f"   💰 {component_door_type} Door ONLY: £{door_price:.2f}")
                
                return jsonify({
                    'found': True,
                    'price': door_price,
                    'item_code': item_code,
                    'item_name': item_name,
                    'description': f"{display_door_type(component_door_type)} Door for {item_name}",
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
        valid_door_types = {'Basic Slab', 'Acrylic Gloss/Matt', 'Timber', 'Vinyl Doors', 'Black Glass', 'Base Cabinet Only'}
        if not db_door_type or db_door_type == 'Carcass Only' or db_door_type not in valid_door_types:
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
        print(f"   🏗️ MODE: Auto-total - {item_code} + {db_door_type}")
        
        door_row = next((r for r in results if r.door_type == db_door_type), None)
        
        if not door_row or not door_row.base_price:
            print(f"   ⚠️ No door price found for {item_code} + {db_door_type}, returning carcass only")
            
            return jsonify({
                'found': True,
                'price': carcass_price,
                'item_code': item_code,
                'item_name': item_name,
                'description': f"{item_name} - {display_door_type(db_door_type)} (door price not found)",
                'door_type': db_door_type,
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
            'description': f"{item_name} - {display_door_type(db_door_type)}",
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
    import re
    
    print(f"\n🔥 APPLIANCE LOOKUP")
    print(f"   Description: {description}")
    
    model_pattern = r'\b([A-Z]{1,}[0-9]{2,}[A-Z0-9]{2,})\b'
    model_match = re.search(model_pattern, description, re.IGNORECASE)
    model_code = model_match.group(1).upper() if model_match else description.strip().upper()
    
    # ✅ Try exact item_code match first
    query = text("""
        SELECT  
            pricelist_id, item_code, item_name, description,
            base_price, brand, door_type, category
        FROM "StreemLyne_MT"."PriceList_Master"
        WHERE tenant_id = :tenant_id
          AND category = 'Appliances'
          AND UPPER(TRIM(item_code)) = :model_code
        LIMIT 1
    """)
    
    result = session.execute(query, {
        'tenant_id': str(tenant_id),
        'model_code': model_code
    }).fetchone()
    
    # ✅ NEW: If not found by item_code, check alias_codes
    if not result:
        alias_query = text("""
            SELECT 
                pricelist_id, item_code, item_name, description,
                base_price, brand, door_type, category
            FROM "StreemLyne_MT"."PriceList_Master"
            WHERE tenant_id = :tenant_id
              AND category = 'Appliances'
              AND alias_codes ILIKE :pattern
            LIMIT 1
        """)
        result = session.execute(alias_query, {
            'tenant_id': str(tenant_id),
            'pattern': f'%{model_code}%'
        }).fetchone()
        if result:
            print(f"✅ Found via alias: {model_code} → {result.item_code}")
    
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
def download_quotation_pdf(quotation_id):
    """Generate and return quotation as PDF — no auth needed for window.open()"""
    db_session = SessionLocal()
    try:
        from io import BytesIO
        from flask import send_file, current_app, jsonify
        from sqlalchemy import text

        # ── Fetch quotation ───────────────────────────────────────────────
        quotation = db_session.execute(
            text("""
                SELECT
                    q.quotation_id,
                    q.reference_number,
                    q.customer_name,
                    q.customer_address,
                    q.customer_phone,
                    q.customer_email,
                    q.created_at,
                    q.total,
                    q.vat_percentage,
                    q.global_discount_percent,
                    q.carcass_colour,
                    q.door_colour,
                    q.door_style,
                    q.panelwork_colour,
                    q.section_discounts,
                    q.room_name,
                    c.client_company_name,
                    c.address        AS client_address,
                    c.client_phone   AS client_phone_num
                FROM "StreemLyne_MT"."Quotations" q
                INNER JOIN "StreemLyne_MT"."Client_Master" c ON q.client_id = c.client_id
                WHERE q.quotation_id = :qid
            """),
            {'qid': quotation_id}
        ).fetchone()

        if not quotation:
            return jsonify({'error': 'Quotation not found'}), 404

        # ── Parse section discounts ───────────────────────────────────────
        section_discounts_raw = getattr(quotation, 'section_discounts', None)
        section_discounts = (json.loads(section_discounts_raw) if isinstance(section_discounts_raw, str) else section_discounts_raw) if section_discounts_raw else {}

        # ── Fetch items ───────────────────────────────────────────────────
        items = db_session.execute(
            text("""
                SELECT item_id, item_name, description, color, quantity, amount, 
                       parent_item_id, section, discount_percent, discounted_amount
                FROM "StreemLyne_MT"."Quotation_Items"
                WHERE quotation_id = :qid
                ORDER BY item_id
            """),
            {'qid': quotation_id}
        ).fetchall()

        # ── PDF setup ─────────────────────────────────────────────────────
        from .pdf_helpers import PDF

        FILL   = (230, 230, 230)
        YELLOW = (255, 255, 180)
        GREEN  = (180, 230, 180)
        lh     = 6

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'QUOTATION'
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        # ── Registration + bank details ───────────────────────────────────
        pdf.set_fill_color(*GREEN)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Registered to England No 5246881', 1, 1, 'C', 1)
        pdf.ln(1)

        pdf.set_fill_color(*YELLOW)
        pdf.set_font('Arial', '', 9)
        pdf.cell(0, 5,
            'Acc name: Atelier Luxe Interiors LTD  |  Bank: ClearBank  |  Sort Code: 04 06 05  |  Acc No: 31621197',
            1, 1, 'C', 1)
        pdf.ln(1)

        pdf.set_fill_color(*FILL)
        pdf.cell(0, 5, 'Please use your name and/or road name as reference', 1, 1, 'C', 1)
        pdf.ln(4)

        # ── Customer info ─────────────────────────────────────────────────
        cust_name    = quotation.customer_name    or quotation.client_company_name or 'N/A'
        cust_address = quotation.customer_address or quotation.client_address      or 'N/A'
        cust_phone   = quotation.customer_phone   or quotation.client_phone_num    or 'N/A'
        date_str     = quotation.created_at.strftime('%d/%m/%Y') if quotation.created_at else 'N/A'


        room_name_val = getattr(quotation, 'room_name', None) or ''
        header_rows = [
            ('DATE:',             date_str),
            ('NAME:',             cust_name),
            ('ADDRESS:',          cust_address),
            ('TEL:',              cust_phone),
        ]
        if room_name_val:
            header_rows.append(('ROOM NAME:', room_name_val))
        header_rows += [
            ('CARCASS COLOUR:',   getattr(quotation, 'carcass_colour', None) or 'N/A'),
            ('DOOR COLOUR:',      getattr(quotation, 'door_colour', None) or 'N/A'),
            ('PANELWORK COLOUR:', getattr(quotation, 'panelwork_colour', None) or 'N/A'),
            ('DOOR STYLE:',       getattr(quotation, 'door_style', None) or 'N/A'),
        ]
        for label, value in header_rows:
            pdf.set_font('Arial', 'B', 9)
            pdf.set_fill_color(*FILL)
            pdf.cell(45, lh, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 9)
            pdf.cell(145, lh, value, 1, 1, 'L')

        pdf.ln(5)

        # ── Items table ───────────────────────────────────────────────────
        headers = ['ITEM',  'DESCRIPTION', 'COLOUR', 'QTY']
        widths  = [35,       118,            22,       15]

        SECTIONS = ['Furniture', 'Fillers and End Panels', 'Accessories', 'Handles', 'Appliances', 'Sink and Tap', 'Worktops', 'Fittings']

        valid_items = [
            i for i in items
            if (i.item_name or '').strip() or (i.description or '').strip() or (i.amount and float(i.amount) > 0)
        ]
        top_level = [i for i in valid_items if not getattr(i, 'parent_item_id', None)]
        sub_map = {}
        for i in valid_items:
            pid = getattr(i, 'parent_item_id', None)
            if pid:
                sub_map.setdefault(pid, []).append(i)

        pdf.set_font('Arial', '', 9)
        subtotal_after_section_discounts = 0.0

        def draw_row(name, desc, color, qty, amount, discount_pct=0, discounted_amt=None, indent=False):
            clean_desc = (desc or '').strip()
            for suffix in [' - Standard', ' - Carcass Only', '- Standard', '- Carcass Only']:
                if clean_desc.endswith(suffix):
                    clean_desc = clean_desc[:-len(suffix)].strip()
            clean_desc = clean_desc.encode('latin-1', errors='ignore').decode('latin-1')
            clean_name = (name or '').encode('latin-1', errors='ignore').decode('latin-1')
            display_name = ('   - ' + clean_name) if indent else clean_name
            line_h = 5
            # Calculate how many lines the description needs
            pdf.set_font('Arial', '', 9)
            desc_width = widths[1] - 2
            # Estimate lines needed
            chars_per_line = int(desc_width / 2.1)
            num_lines = max(1, -(-len(clean_desc) // chars_per_line))  # ceiling division
            row_h = max(8, num_lines * line_h + 2)
            x0, y0 = pdf.get_x(), pdf.get_y()
            # Draw border cells at fixed height
            pdf.cell(widths[0], row_h, display_name[:22], 1, 0, 'L')
            pdf.cell(widths[1], row_h, '', 1, 0, 'L')
            pdf.cell(widths[2], row_h, color or '', 1, 0, 'C')
            pdf.cell(widths[3], row_h, str(int(qty or 1)), 1, 1, 'C')
            # Write description with multi_cell inside the description box
            pdf.set_xy(x0 + widths[0] + 1, y0 + 1)
            pdf.multi_cell(desc_width, line_h, clean_desc, 0, 'L')
            pdf.set_xy(x0, y0 + row_h)
            raw = float(amount or 0) * int(qty or 1)
            if discounted_amt is not None and float(discounted_amt) > 0:
                return float(discounted_amt)
            return raw

        def draw_section_header(section_name):
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 7, section_name, 0, 1, 'L')
            pdf.set_fill_color(*FILL)
            pdf.set_font('Arial', 'B', 9)
            for h, w in zip(headers, widths):
                pdf.cell(w, 8, h, 1, 0, 'C', 1)
            pdf.ln()
            pdf.set_font('Arial', '', 9)

        ROW_H = 8
        PAGE_BOTTOM = pdf.h - 35

        for section in SECTIONS:
            section_items = [i for i in top_level if (getattr(i, 'section', None) or 'Furniture') == section]
            if not section_items:
                continue

            header_h = 7 + 8
            # Estimate space needed: header + at least 3 rows (or all items if fewer)
            min_rows_to_keep_together = min(len(section_items), 3)
            space_needed = header_h + (ROW_H * min_rows_to_keep_together)
            if pdf.get_y() + space_needed > pdf.h - 35:
                pdf.add_page()
            draw_section_header(section)

            section_raw = 0.0
            section_subtotal = 0.0  # after per-item discounts

            for item in section_items:
                if pdf.get_y() + ROW_H * 2 > PAGE_BOTTOM:
                    pdf.add_page()

                lt = draw_row(
                    item.item_name or '',
                    item.description or '',
                    item.color,
                    item.quantity,
                    item.amount,
                    discount_pct=float(item.discount_percent or 0),
                    discounted_amt=item.discounted_amount,
                )
                section_raw += round(float(item.amount or 0) * int(item.quantity or 1), 2)
                section_subtotal += round(lt, 2)
                for sub in sub_map.get(item.item_id, []):
                    if pdf.get_y() + ROW_H > PAGE_BOTTOM:
                        pdf.add_page()
                    slt = draw_row(
                        sub.item_name or '',
                        sub.description or '',
                        sub.color,
                        sub.quantity,
                        sub.amount,
                        discount_pct=float(sub.discount_percent or 0),
                        discounted_amt=sub.discounted_amount,
                        indent=True,
                    )
                    section_raw += round(float(sub.amount or 0) * int(sub.quantity or 1), 2)
                    section_subtotal += round(slt, 2)
            sec_discount_amt = round(section_raw - section_subtotal, 2)

            sec_discount_amt = section_raw - section_subtotal
            sec_discount_pct = (sec_discount_amt / section_raw * 100) if section_raw > 0 else 0
            subtotal_after_section_discounts = round(subtotal_after_section_discounts + round(section_subtotal, 2), 2)

            # ── Section totals display ────────────────────────────────────
            pdf.ln(1)
            sec_tx = 120

            pdf.set_font('Arial', '', 8)
            pdf.set_x(sec_tx)
            pdf.cell(45, 5, f'{section} Subtotal:', 0, 0, 'R')
            pdf.cell(25, 5, f'£{section_raw:.2f}', 0, 1, 'R')

            if sec_discount_amt > 0.005:
                pdf.set_font('Arial', '', 8)
                pdf.set_x(sec_tx)
                pdf.cell(45, 5, f'Section Discount ({sec_discount_pct:.1f}%):', 0, 0, 'R')
                pdf.set_text_color(200, 0, 0)
                pdf.cell(25, 5, f'-£{sec_discount_amt:.2f}', 0, 1, 'R')
                pdf.set_text_color(0, 0, 0)

            pdf.set_font('Arial', 'B', 8)
            pdf.set_fill_color(220, 220, 220)
            pdf.set_x(sec_tx)
            pdf.cell(45, 5, f'{section} Total:', 1, 0, 'R', 1)
            pdf.cell(25, 5, f'£{section_subtotal:.2f}', 1, 1, 'R', 1)
            pdf.ln(4)

        # ── Totals ────────────────────────────────────────────────────────
        if pdf.get_y() > pdf.h - 100:
            pdf.add_page()
        pdf.ln(3)
        discount_pct    = float(quotation.global_discount_percent) if quotation.global_discount_percent is not None else 0.0
        discount_amount = subtotal_after_section_discounts * (discount_pct / 100)
        subtotal_after_discount = subtotal_after_section_discounts - discount_amount
        vat_pct    = float(quotation.vat_percentage) if quotation.vat_percentage is not None else 20.0
        vat_amount = subtotal_after_discount * (vat_pct / 100)
        total      = subtotal_after_discount + vat_amount
        tx         = 105

        totals_rows = [('SUB TOTAL:', f"£{subtotal_after_section_discounts:.2f}")]
        if discount_pct > 0:
            totals_rows.append((f'DISCOUNT ({discount_pct:.0f}%):', f"-£{discount_amount:.2f}"))
        totals_rows.append((f'VAT ({vat_pct:.0f}%):', f"£{vat_amount:.2f}"))

        for label, value in totals_rows:
            pdf.set_x(tx)
            pdf.set_font('Arial', '', 10)
            pdf.cell(50, lh, label, 0, 0, 'R')
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(35, lh, value, 0, 1, 'R')

        pdf.set_x(tx)
        pdf.set_fill_color(*FILL)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(50, 8, 'TOTAL:', 'T', 0, 'R', 1)
        pdf.cell(35, 8, f"£{total:.2f}", 'T', 1, 'R', 1)
        pdf.ln(8)

        # ── Payment terms ─────────────────────────────────────────────────
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(0, 5, 'Only Bacs or Cash will be accepted on Delivery and Completion', 0, 1, 'L')
        pdf.cell(0, 5, 'NOTE: If you wish to proceed with this quote, full payment is required upfront.', 0, 1, 'L')
        pdf.ln(4)

        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 5, 'Please sign here to confirm.', 0, 1, 'L')
        pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

        # ── Signature section ─────────────────────────────────────────────
        pdf.set_font('Arial', '', 9)
        for label in ['Customer Signature:', 'Customer Name:', 'Date:']:
            pdf.cell(45, 6, label, 0, 0, 'L')
            pdf.cell(145, 6, '', 'B', 1, 'L')
            pdf.ln(2)

        # ── Return PDF ────────────────────────────────────────────────────
        out  = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf  = BytesIO(bytes(out))
        ref  = quotation.reference_number or str(quotation_id)
        name = f"Quotation_{ref}_{cust_name.replace(' ', '_')}.pdf"

        return send_file(buf, mimetype='application/pdf',
                         as_attachment=False, download_name=name)

    except Exception as e:
        current_app.logger.exception(f"Quotation PDF generation failed: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()