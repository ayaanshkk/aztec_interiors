from flask import Blueprint, request, jsonify, current_app
from backend.db import SessionLocal
from backend.models import CustomerFormData, Customer, Quotation, QuotationItem, PriceListItem
from backend.routes.auth_helpers import token_required
import json
from datetime import datetime

quotation_bp = Blueprint('quotations', __name__)

# Helper function to get current user's email
def get_current_user_email(data=None):
    if hasattr(request, 'current_user') and hasattr(request.current_user, 'email'):
        return request.current_user.email
    return data.get('created_by', 'System') if isinstance(data, dict) else 'System'


@quotation_bp.route('/quotations', methods=['GET', 'POST', 'OPTIONS'])
@token_required
def handle_quotations():
    """GET all quotations or POST to create a new quotation"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        if request.method == 'POST':
            data = request.json
            
            # Generate reference number
            ref_num = f"Q-{datetime.utcnow().strftime('%Y%m%d')}-{session.query(Quotation).count() + 1}"
            
            quotation = Quotation(
                customer_id=data.get('customer_id'),
                reference_number=ref_num,
                total=0,
                status=data.get('status', 'Draft'),
                notes=data.get('notes', '')
            )
            session.add(quotation)
            session.flush()

            items = data.get('items', [])
            for item in items:
                q_item = QuotationItem(
                    quotation_id=quotation.id,
                    item=item.get('item', ''),
                    description=item.get('description', ''),
                    quantity=item.get('quantity', 1),
                    amount=item.get('amount', 0)
                )
                session.add(q_item)
            session.commit()
            return jsonify({'id': quotation.id, 'message': 'Quotation created successfully'}), 201

        # GET all quotations
        quotations = session.query(Quotation).order_by(Quotation.created_at.desc()).all()
        return jsonify([q.to_dict(include_items=True) for q in quotations])
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error in /quotations: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@quotation_bp.route('/quotations/generate-from-checklist/<string:form_submission_id>', methods=['POST', 'OPTIONS'])
@token_required
def generate_quote_from_checklist(form_submission_id):
    """Generate quotation from checklist - auto-extracts items"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        current_app.logger.info(f"📋 Generating quote from checklist: {form_submission_id}")
        
        # Get form submission
        form_submission = session.query(CustomerFormData).filter_by(id=form_submission_id).first()
        if not form_submission:
            current_app.logger.error(f"❌ Form submission not found: {form_submission_id}")
            return jsonify({'error': 'Form submission not found'}), 404
        
        # Parse form data
        form_data = json.loads(form_submission.form_data) if isinstance(form_submission.form_data, str) else form_submission.form_data
        
        # Detect checklist type
        form_type = form_data.get('form_type', '').lower()
        checklist_type = 'kitchen' if 'kitchen' in form_type else 'bedroom'
        
        current_app.logger.info(f"📊 Detected checklist type: {checklist_type}")
        
        # Get customer
        customer = session.query(Customer).filter_by(id=form_submission.customer_id).first()
        if not customer:
            current_app.logger.error(f"❌ Customer not found: {form_submission.customer_id}")
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Get project_id from form submission if it exists
        project_id = form_submission.project_id if hasattr(form_submission, 'project_id') else None
        
        # Create quotation
        ref_num = f"Q-{datetime.utcnow().strftime('%Y%m%d')}-{str(form_submission_id)[:8]}"
        quotation = Quotation(
            customer_id=form_submission.customer_id,
            project_id=project_id,  # ✅ Save project association
            reference_number=ref_num,
            total=0,
            status='Draft',
            notes=f"Auto-generated from {checklist_type} checklist",
        )
        session.add(quotation)
        session.flush()
        
        current_app.logger.info(f"✅ Quotation created with ID: {quotation.id}, Project ID: {project_id}")
        
        # Extract items from checklist
        extracted_items = extract_checklist_items(form_data, checklist_type)
        
        current_app.logger.info(f"📦 Extracted {len(extracted_items)} items from checklist")
        
        # Add items to quotation
        total = 0
        for item_data in extracted_items:
            quote_item = QuotationItem(
                quotation_id=quotation.id,
                item=item_data['item_name'],
                description=item_data['description'],
                color=item_data.get('color', ''),
                quantity=item_data.get('quantity', 1),
                width=item_data.get('width'),
                height=item_data.get('height'),
                depth=item_data.get('depth'),
                amount=item_data.get('price', 0),
                needs_manual_pricing=item_data.get('needs_manual_pricing', False)
            )
            session.add(quote_item)
            total += quote_item.amount * quote_item.quantity
        
        quotation.total = total
        session.commit()
        
        current_app.logger.info(f"✅ Quote generation complete: {ref_num} with {len(extracted_items)} items")
        
        return jsonify({
            'success': True,
            'quotation_id': quotation.id,
            'reference_number': quotation.reference_number,
            'items_count': len(extracted_items),
            'total': float(total),
            'checklist_type': checklist_type,
            'project_id': project_id,  # ✅ Return project_id
            'message': f'Quote generated with {len(extracted_items)} items. Opening PDF preview...'
        }), 201
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"❌ Error generating quotation: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@quotation_bp.route('/quotations/<int:quotation_id>/match-prices', methods=['POST', 'OPTIONS'])
@token_required
def match_item_price(quotation_id):
    """Match quote item with price list based on dimensions"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        data = request.json
        item_id = data.get('item_id')
        width = data.get('width')
        height = data.get('height')
        depth = data.get('depth')
        
        # Get quotation item
        quote_item = session.query(QuotationItem).filter_by(
            id=item_id,
            quotation_id=quotation_id
        ).first()
        
        if not quote_item:
            return jsonify({'error': 'Quote item not found'}), 404
        
        # Get quotation to determine category
        quotation = session.query(Quotation).filter_by(id=quotation_id).first()
        if not quotation:
            return jsonify({'error': 'Quotation not found'}), 404
        
        # Determine category from notes or assume bedroom
        category = 'bedroom'  # Default
        if quotation.notes and 'kitchen' in quotation.notes.lower():
            category = 'kitchen'
        
        # Find matching price list item
        query = session.query(PriceListItem).filter_by(category=category)
        
        if width:
            query = query.filter_by(width=width)
        if height:
            query = query.filter_by(height=height)
        if depth:
            query = query.filter_by(depth=depth)
        
        matched_item = query.first()
        
        if matched_item:
            # Update quote item
            quote_item.amount = float(matched_item.base_price)
            quote_item.price_list_item_id = matched_item.id
            quote_item.needs_manual_pricing = False
            quote_item.width = width
            quote_item.height = height
            quote_item.depth = depth
            
            # Recalculate total
            items = session.query(QuotationItem).filter_by(quotation_id=quotation_id).all()
            total = sum(item.amount * item.quantity for item in items)
            quotation.total = total
            
            session.commit()
            
            return jsonify({
                'success': True,
                'matched_item': {
                    'code': matched_item.item_code,
                    'name': matched_item.item_name,
                    'price': float(matched_item.base_price)
                },
                'new_amount': float(quote_item.amount),
                'new_total': float(total)
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'No matching item found in price list'
            }), 404
    
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error matching price: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def extract_checklist_items(form_data: dict, checklist_type: str) -> list:
    """Extract billable items from checklist"""
    items = []
    
    # DOORS - Main door
    if form_data.get('door_style') and form_data.get('door_color'):
        door_desc = f"{form_data.get('door_style')} - {form_data.get('door_manufacturer', '')} {form_data.get('door_name', '')}".strip()
        
        items.append({
            'item_name': 'Door',
            'description': door_desc,
            'color': form_data.get('door_color', ''),
            'price': 0,
            'quantity': 1,
            'needs_manual_pricing': True,
        })
    
    # ADDITIONAL DOORS
    for idx, door in enumerate(form_data.get('additional_doors', [])):
        if door.get('door_style'):
            door_desc = f"{door.get('door_style')} - {door.get('door_manufacturer', '')} {door.get('door_name', '')}".strip()
            qty = int(door.get('quantity', 1)) if door.get('quantity') else 1
            
            items.append({
                'item_name': f'Additional Door {idx + 1}',
                'description': door_desc,
                'color': door.get('door_color', ''),
                'quantity': qty,
                'price': 0,
                'needs_manual_pricing': True,
            })
    
    # PANELS
    if form_data.get('end_panel_color'):
        items.append({
            'item_name': 'End Panel',
            'description': 'End Panel',
            'color': form_data.get('end_panel_color'),
            'price': 0,
            'needs_manual_pricing': True,
        })
    
    # PLINTH/FILLER
    if form_data.get('plinth_filler_color'):
        items.append({
            'item_name': 'Plinth/Filler',
            'description': 'Plinth/Filler',
            'color': form_data.get('plinth_filler_color'),
            'price': 0,
            'needs_manual_pricing': True,
        })
    
    # HANDLES
    if form_data.get('handles_code'):
        qty = int(form_data.get('handles_quantity', 1)) if form_data.get('handles_quantity') else 1
        items.append({
            'item_name': 'Handles',
            'description': f"Code: {form_data.get('handles_code')} - Size: {form_data.get('handles_size', 'N/A')}",
            'quantity': qty,
            'price': 0,
            'needs_manual_pricing': True,
        })
    
    # BEDROOM SPECIFIC
    if checklist_type == 'bedroom':
        if form_data.get('bedside_cabinets_type'):
            qty = int(form_data.get('bedside_cabinets_qty', 1)) if form_data.get('bedside_cabinets_qty') else 1
            items.append({
                'item_name': 'Bedside Cabinets',
                'description': form_data.get('bedside_cabinets_type'),
                'quantity': qty,
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        if form_data.get('dresser_desk') == 'yes':
            items.append({
                'item_name': 'Dresser/Desk',
                'description': form_data.get('dresser_desk_details', 'Dresser/Desk'),
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        if form_data.get('mirror_type'):
            qty = int(form_data.get('mirror_qty', 1)) if form_data.get('mirror_qty') else 1
            items.append({
                'item_name': 'Mirror',
                'description': form_data.get('mirror_type'),
                'quantity': qty,
                'price': 0,
                'needs_manual_pricing': True,
            })
    
    # KITCHEN SPECIFIC
    elif checklist_type == 'kitchen':
        if form_data.get('worktop_material_type'):
            items.append({
                'item_name': 'Worktop',
                'description': f"{form_data.get('worktop_material_type')} - {form_data.get('worktop_size', '')}",
                'color': form_data.get('worktop_material_color', ''),
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        # APPLIANCES
        appliance_names = ["Oven", "Microwave", "Washing Machine", "Dryer", "HOB", "Extractor", "INTG Dishwasher"]
        for idx, appliance in enumerate(form_data.get('appliances', [])):
            if appliance.get('make') or appliance.get('model'):
                name = appliance_names[idx] if idx < len(appliance_names) else f'Appliance {idx + 1}'
                items.append({
                    'item_name': name,
                    'description': f"{appliance.get('make', '')} {appliance.get('model', '')}".strip(),
                    'price': 0,
                    'needs_manual_pricing': True,
                })
        
        # INTEGRATED APPLIANCES
        if form_data.get('integ_fridge_make') or form_data.get('integ_fridge_model'):
            qty = int(form_data.get('integ_fridge_qty', 1)) if form_data.get('integ_fridge_qty') else 1
            items.append({
                'item_name': 'Integrated Fridge',
                'description': f"{form_data.get('integ_fridge_make', '')} {form_data.get('integ_fridge_model', '')}".strip(),
                'quantity': qty,
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        if form_data.get('integ_freezer_make') or form_data.get('integ_freezer_model'):
            qty = int(form_data.get('integ_freezer_qty', 1)) if form_data.get('integ_freezer_qty') else 1
            items.append({
                'item_name': 'Integrated Freezer',
                'description': f"{form_data.get('integ_freezer_make', '')} {form_data.get('integ_freezer_model', '')}".strip(),
                'quantity': qty,
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        if form_data.get('sink_details'):
            items.append({
                'item_name': 'Sink',
                'description': f"{form_data.get('sink_details')} - {form_data.get('sink_model', '')}",
                'price': 0,
                'needs_manual_pricing': True,
            })
        
        if form_data.get('tap_details'):
            items.append({
                'item_name': 'Tap',
                'description': f"{form_data.get('tap_details')} - {form_data.get('tap_model', '')}",
                'price': 0,
                'needs_manual_pricing': True,
            })
    
    return items