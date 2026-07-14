from flask import Blueprint, request, jsonify, current_app, send_file
from sqlalchemy import text
import json
from datetime import datetime
from io import BytesIO
from fpdf import FPDF

from ..db import SessionLocal
from .auth_helpers import token_required, require_tenant
from .pdf_helpers import PDF  # shared PDF class extracted below

checklist_bp = Blueprint("checklist", __name__)


# ==========================================
# CHECKLIST ROUTES
# ==========================================

@checklist_bp.route('/checklists/download-pdf', methods=['POST'])
def download_checklist_pdf():
    """Generate and download installation checklist PDF"""
    try:
        data = request.get_json(silent=True) or {}

        if not data:
            return jsonify({'error': 'Missing form data for PDF generation'}), 400

        form_data = data.get('formData', data)
        form_type = (form_data.get('form_type', '') or '').lower()
        is_kitchen = 'kitchen' in form_type

        pdf = PDF('P', 'mm', 'A4', show_header=False)
        pdf.doc_title = 'Kitchen Installation Checklist' if is_kitchen else 'Bedroom Installation Checklist'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=False, margin=20)

        FILL   = (240, 240, 240)
        GREEN  = (220, 242, 220)
        PURPLE = (243, 232, 255)
        ORANGE = (255, 237, 213)
        YELLOW = (254, 249, 195)
        PINK   = (252, 231, 243)
        BLUE   = (219, 234, 254)
        lh = 6

        PAGE_BOTTOM = pdf.h - 20
        current_section_color = [255, 255, 255]

        def check_space(needed=lh):
            if pdf.get_y() + needed > PAGE_BOTTOM:
                pdf.add_page()
                pdf.set_auto_page_break(auto=False, margin=20)

        def section_header(title, fill_color):
            current_section_color[0] = fill_color[0]
            current_section_color[1] = fill_color[1]
            current_section_color[2] = fill_color[2]
            check_space(20)
            pdf.set_fill_color(*fill_color)
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, title, 1, 1, 'L', 1)
            pdf.ln(1)

        def full_row(label, value):
            check_space(lh)
            val = str(value or 'N/A')
            pdf.set_fill_color(current_section_color[0], current_section_color[1], current_section_color[2])
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(50, lh, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 9)
            pdf.multi_cell(140, lh, val, 1, 'L', 1)
            pdf.set_x(10)

        def two_col(label1, val1, label2, val2):
            check_space(lh)
            v1 = str(val1 or 'N/A')
            v2 = str(val2 or 'N/A')
            pdf.set_fill_color(current_section_color[0], current_section_color[1], current_section_color[2])
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(40, lh, label1, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 9)
            pdf.cell(55, lh, v1[:35], 1, 0, 'L', 1)
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(40, lh, label2, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 9)
            pdf.cell(55, lh, v2[:35], 1, 1, 'L', 1)

        def sub_header(title):
            check_space(lh)
            pdf.set_fill_color(current_section_color[0], current_section_color[1], current_section_color[2])
            pdf.set_font('Arial', 'B', 9)
            pdf.cell(0, lh, title, 1, 1, 'L', 1)

        # ── Title ──────────────────────────────────────────────────────
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 8, 'KITCHEN INSTALLATION CHECKLIST' if is_kitchen else 'BEDROOM INSTALLATION CHECKLIST', 0, 1, 'C')
        pdf.ln(3)

        # ── Customer Information ────────────────────────────────────────
        section_header('Customer Information', BLUE)
        full_row('Customer Name:', form_data.get('customer_name', ''))
        full_row('Tel/Mobile:', form_data.get('customer_phone', ''))
        full_row('Address:', form_data.get('customer_address', ''))
        postcode = form_data.get('customer_postcode') or form_data.get('postcode', '')
        full_row('Postcode:', postcode)
        full_row('Room:', form_data.get('room', '')) 
        two_col('Survey Date:', form_data.get('survey_date', ''),
                'Installation Date:', form_data.get('installation_date', ''))
        pdf.ln(4)

        # ── 1. Material Specifications ──────────────────────────────────
        section_header('1. Material Specifications', GREEN)
        two_col('Door Style:', form_data.get('door_style', ''),
                'Door Type:', form_data.get('door_type', ''))
        two_col('Door Color:', form_data.get('door_color', ''),
                'Panel Color:', form_data.get('end_panel_color', ''))
        two_col('Plinth/Filler Color:', form_data.get('plinth_filler_color', ''),
                'Cabinet Color:', form_data.get('cabinet_color', ''))

        if (form_data.get('door_style', '') or '').lower() == 'vinyl':
            two_col('Door Manufacturer:', form_data.get('door_manufacturer', ''),
                    'Door Name:', form_data.get('door_name', ''))

        if not is_kitchen:
            two_col('Worktop Color:', form_data.get('worktop_material_color', ''),
                    'Worktop Code:', form_data.get('worktop_code', ''))

        additional_doors = form_data.get('additional_doors', [])
        if additional_doors:
            pdf.ln(2)
            sub_header('Additional Doors')
            for i, door in enumerate(additional_doors):
                sub_header(f'  Door {i + 1}')
                two_col('  Style:', door.get('door_style', ''),
                        'Type:', door.get('door_type', ''))
                two_col('  Color:', door.get('door_color', ''),
                        'Qty:', door.get('quantity', ''))
                two_col('  Panel Color:', door.get('panel_color', ''),
                        'Plinth Color:', door.get('plinth_color', ''))
                full_row('  Cabinet Color:', door.get('cabinet_color', ''))
        pdf.ln(4)

        # ── 2. Hardware Specifications ──────────────────────────────────
        section_header('2. Hardware Specifications', PURPLE)
        two_col('Handle Code:', form_data.get('handles_code', ''),
                'Handle Quantity:', form_data.get('handles_quantity', ''))
        full_row('Handle Size:', form_data.get('handles_size', ''))

        additional_handles = form_data.get('additional_handles', [])
        if additional_handles:
            sub_header('Additional Handles')
            for i, h in enumerate(additional_handles):
                sub_header(f'  Handle {i + 1}')
                two_col('  Code:', h.get('handles_code', ''),
                        'Quantity:', h.get('handles_quantity', ''))
                full_row('  Size:', h.get('handles_size', ''))

        if is_kitchen:
            full_row('Accessories:', form_data.get('accessories', ''))
            full_row('Lighting Spec:', form_data.get('lighting_spec', ''))
            two_col('Under Wall Unit Lights:', form_data.get('under_wall_unit_lights_color', ''),
                    'Profile Color:', form_data.get('under_wall_unit_lights_profile', ''))
            full_row('Under Worktop Lights:', form_data.get('under_worktop_lights_color', ''))
        pdf.ln(4)

        # ── 3. Worktop Specifications ───────────────────────────────────
        section_header('3. Worktop Specifications', ORANGE)
        two_col('Material Type:', form_data.get('worktop_material_type', ''),
                'Material Color:', form_data.get('worktop_material_color', ''))
        two_col('Worktop Code:', form_data.get('worktop_code', ''),
                'Size/Thickness:', form_data.get('worktop_size', ''))

        features = form_data.get('worktop_features', [])
        if features:
            full_row('Features:', ', '.join(features) if isinstance(features, list) else str(features))
        full_row('Other Details:', form_data.get('worktop_other_details', ''))

        additional_worktops = form_data.get('additional_worktops', [])
        if additional_worktops:
            pdf.ln(2)
            sub_header('Additional Worktops')
            for i, wt in enumerate(additional_worktops):
                sub_header(f'  Worktop {i + 1}')
                two_col('  Material:', wt.get('worktop_material_type', ''),
                        'Color:', wt.get('worktop_material_color', ''))
                two_col('  Code:', wt.get('worktop_code', ''),
                        'Size:', wt.get('worktop_size', ''))
                wt_features = wt.get('worktop_features', [])
                if wt_features:
                    full_row('  Features:', ', '.join(wt_features) if isinstance(wt_features, list) else str(wt_features))
                full_row('  Other Details:', wt.get('worktop_other_details', ''))
        pdf.ln(4)

        if is_kitchen:
            # ── 4. Appliances & Sink/Tap ────────────────────────────────
            section_header('4. Appliances & Sink/Tap', YELLOW)
            full_row('Appliances Customer Owned:', form_data.get('appliances_customer_owned', ''))

            appliance_labels = ['Oven', 'Microwave', 'Washing Machine', 'Dryer', 'HOB', 'Extractor', 'INTG Dishwasher']
            appliances = form_data.get('appliances', [])
            for i, label in enumerate(appliance_labels):
                app = appliances[i] if i < len(appliances) else {}
                if app.get('make') or app.get('model'):
                    two_col(f'{label} Make:', app.get('make', ''),
                            'Model:', app.get('model', ''))

            if form_data.get('integ_fridge_make'):
                two_col('INTG Fridge Make:', form_data.get('integ_fridge_make', ''),
                        'Model:', form_data.get('integ_fridge_model', ''))
            if form_data.get('integ_freezer_make'):
                two_col('INTG Freezer Make:', form_data.get('integ_freezer_make', ''),
                        'Model:', form_data.get('integ_freezer_model', ''))

            additional_appliances = form_data.get('additional_appliances', [])
            if additional_appliances:
                sub_header('Additional Appliances')
                for add_app in additional_appliances:
                    if not isinstance(add_app, dict):
                        continue
                    label = add_app.get('label', 'Appliance')
                    make  = add_app.get('make', '')
                    model = add_app.get('model', '')
                    if make or model:
                        two_col(f'{label} Make:', make, 'Model:', model)

            full_row('Sink & Tap Customer Owned:', form_data.get('sink_tap_customer_owned', ''))
            if form_data.get('sink_details'):
                two_col('Sink Details:', form_data.get('sink_details', ''),
                        'Sink Model:', form_data.get('sink_model', ''))
            if form_data.get('tap_details'):
                two_col('Tap Details:', form_data.get('tap_details', ''),
                        'Tap Model:', form_data.get('tap_model', ''))
            pdf.ln(4)

        else:
            # ── 4. Bedroom Furniture ────────────────────────────────────
            section_header('4. Bedroom Furniture Specifications', YELLOW)
            two_col('Bedside Cabinets:', form_data.get('bedside_cabinets_type', ''),
                    'Qty:', form_data.get('bedside_cabinets_qty', ''))
            two_col('Dresser/Desk:', form_data.get('dresser_desk', ''),
                    'Details:', form_data.get('dresser_desk_details', ''))
            two_col('Internal Mirror:', form_data.get('internal_mirror', ''),
                    'Details:', form_data.get('internal_mirror_details', ''))
            two_col('Mirror Type:', form_data.get('mirror_type', ''),
                    'Mirror Qty:', form_data.get('mirror_qty', ''))
            pdf.ln(4)

            # ── 5. Lighting ─────────────────────────────────────────────
            section_header('5. Lighting Specifications', PINK)
            two_col('Soffit Lights Type:', form_data.get('soffit_lights_type', ''),
                    'Color:', form_data.get('soffit_lights_color', ''))
            two_col('Gable Lights Type:', form_data.get('gable_lights_type', ''),
                    'Main Color:', form_data.get('gable_lights_main_color', ''))
            full_row('Gable Profile Color:', form_data.get('gable_lights_profile_color', ''))
            pdf.ln(4)

            # ── 6. Accessories & Floor Protection ───────────────────────
            section_header('6. Accessories & Floor Protection', FILL)
            full_row('Other/Misc/Accessories:', form_data.get('other_accessories', ''))
            floor_protection = form_data.get('floor_protection', [])
            full_row('Floor Protection:', ', '.join(floor_protection) if isinstance(floor_protection, list) else str(floor_protection or 'N/A'))
            pdf.ln(4)

        # ── Output ──────────────────────────────────────────────────────
        out = pdf.output(dest='S')
        if isinstance(out, str):
            out = out.encode('latin-1')
        buf = BytesIO(bytes(out))

        customer_name = (form_data.get('customer_name', 'Customer') or 'Customer').replace(' ', '_')
        checklist_type = 'Kitchen' if is_kitchen else 'Bedroom'
        filename = f"{checklist_type}_Checklist_{customer_name}.pdf"

        return send_file(buf, mimetype='application/pdf',
                         as_attachment=False, download_name=filename)

    except Exception as e:
        current_app.logger.exception(f"Checklist PDF generation failed: {e}")
        return jsonify({"error": f"Server failed to generate PDF: {str(e)}"}), 500


@checklist_bp.route('/checklists/save', methods=['POST'])
@token_required
@require_tenant
def save_checklist(tenant_id, employee_id):
    """Save checklist to Customer_Form_Submissions"""
    session = SessionLocal()
    try:
        data           = request.get_json(silent=True) or {}
        checklist_type = data.get('checklistType', 'unknown')
        client_id      = data.get('customerId') or data.get('clientId')

        if not client_id:
            return jsonify({'error': 'Missing client ID'}), 400

        # Verify client exists
        client = session.execute(
            text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE client_id = :client_id AND tenant_id = :tenant_id
            """),
            {'client_id': int(client_id), 'tenant_id': str(tenant_id)}
        ).fetchone()

        if not client:
            return jsonify({'error': 'Client not found'}), 404

        result = session.execute(
            text("""
                INSERT INTO "StreemLyne_MT"."Customer_Form_Submissions"
                (tenant_id, client_id, form_type, form_name, form_data,
                 token_used, submitted_by, submission_status)
                VALUES (:tenant_id, :client_id, :form_type, :form_name, :form_data,
                        '', :submitted_by, 'submitted')
                RETURNING form_submission_id
            """),
            {
                'tenant_id':    str(tenant_id),
                'client_id':    int(client_id),
                'form_type':    f"checklist_{checklist_type}",
                'form_name':    f"{checklist_type.title()} Checklist",
                'form_data':    json.dumps(data),
                'submitted_by': (
                    request.current_user.username
                    if hasattr(request, 'current_user') and hasattr(request.current_user, 'username')
                    else 'System'
                )
            }
        )

        form_id = result.fetchone().form_submission_id
        session.commit()

        current_app.logger.info(f"Checklist '{checklist_type}' saved for client {client_id}")

        return jsonify({
            "success":           True,
            "message":           f"{checklist_type.title()} Checklist saved successfully!",
            "form_submission_id": form_id
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error saving checklist: {e}")
        return jsonify({"error": f"Failed to save checklist: {str(e)}"}), 500
    finally:
        session.close()