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
    """Generate and download remedial checklist PDF"""
    try:
        data = request.get_json(silent=True) or {}

        if not data or not data.get('items'):
            return jsonify({'error': 'Missing form data for PDF generation'}), 400

        pdf = PDF('P', 'mm', 'A4')
        pdf.doc_title = 'Remedial Checklist'
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font('Arial', '', 10)

        HEADER_FILL_LIGHT = (230, 230, 230)
        HEADER_FILL_DARK  = (200, 200, 200)
        col_width   = 190 / 2
        line_height = 6

        # ── Customer details block ─────────────────────────────────────
        pdf.set_fill_color(*HEADER_FILL_LIGHT)
        pdf.set_draw_color(0, 0, 0)

        def info_row(label, value):
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(col_width, line_height, label, 1, 0, 'L', 1)
            pdf.set_font('Arial', '', 10)
            pdf.cell(col_width, line_height, value or 'N/A', 1, 1, 'L', 0)

        info_row('CUSTOMER NAME:',    data.get('customerName', 'N/A'))

        # Address may be multi-line
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(col_width, line_height, 'CUSTOMER ADDRESS:', 1, 0, 'L', 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(col_width, line_height, data.get('customerAddress', 'N/A'), 'LRT', 'L', 0)
        end_y = pdf.get_y()
        pdf.set_xy(10, end_y - line_height)
        pdf.cell(col_width, line_height, '', 'B', 0, 'L')
        pdf.set_y(end_y)

        info_row('CUSTOMER TEL NO.:', data.get('customerPhone', 'N/A'))
        info_row('DATE:',             data.get('date', 'N/A'))
        info_row('FITTERS:',          data.get('fitters', 'N/A'))
        pdf.ln(10)

        # ── Items table ────────────────────────────────────────────────
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 5, 'Items Required for Remedial Action', 0, 1, 'L')
        pdf.ln(1)

        headers = ['NO', 'ITEM', 'REMEDIAL ACTION', 'COLOUR', 'SIZE', 'QTY']
        widths  = [10,   50,     60,                 25,       25,     20]

        pdf.set_fill_color(*HEADER_FILL_DARK)
        pdf.set_font('Arial', 'B', 9)
        for h, w in zip(headers, widths):
            pdf.cell(w, 7, h, 1, 0, 'C', 1)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        pdf.set_fill_color(255, 255, 255)

        for index, item in enumerate(data.get('items', [])):
            if not item.get('item') and not item.get('remedialAction'):
                continue

            row_data = [
                str(index + 1),
                item.get('item', ''),
                item.get('remedialAction', ''),
                item.get('colour', ''),
                item.get('size', ''),
                str(item.get('qty', '')),
            ]

            x_start = pdf.get_x()
            y_start = pdf.get_y()

            # Measure heights for text-wrapping columns
            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', False, dry_run=True)
            h_item = pdf.get_y() - y_start

            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', False, dry_run=True)
            h_action = pdf.get_y() - y_start

            row_h = max(5, h_item, h_action)
            pdf.set_xy(x_start, y_start)

            for i, (txt, w) in enumerate(zip(row_data, widths)):
                align = 'C' if i == 0 or i >= 3 else 'L'
                if i in [1, 2]:
                    x = pdf.get_x()
                    y = pdf.get_y()
                    pdf.cell(w, row_h, '', 1, 0, align, 0)
                    pdf.set_xy(x + w, y)
                else:
                    pdf.cell(w, row_h, txt, 1, 0, align, 0)

            # Write the text content of wrapping columns
            pdf.set_xy(x_start + widths[0], y_start)
            pdf.multi_cell(widths[1], 4, row_data[1], 0, 'L', 0)

            pdf.set_xy(x_start + widths[0] + widths[1], y_start)
            pdf.multi_cell(widths[2], 4, row_data[2], 0, 'L', 0)

            pdf.set_y(y_start + row_h)

        pdf_output = pdf.output(dest='S')
        pdf_file   = BytesIO(pdf_output)

        customer_name = data.get('customerName', 'Customer').replace(' ', '_')
        date_str      = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        filename      = f"Remedial_Checklist_{customer_name}_{date_str}.pdf"

        return send_file(pdf_file, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)

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